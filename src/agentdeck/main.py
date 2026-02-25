import asyncio
import json
import logging
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import (
    BaseHTTPMiddleware,
)
from starlette.responses import FileResponse
from starlette.templating import Jinja2Templates

from agentdeck.api import sessions as sessions_routes
from agentdeck.api.router import api_router
from agentdeck.config import get_settings
from agentdeck.notifications.push import PushNotifier
from agentdeck.notifications.store import (
    PushSubscriptionStore,
)
from agentdeck.notifications.vapid import (
    load_or_create_vapid_keys,
)
from agentdeck.sessions.agent_output_log import (
    AgentOutputLog,
)
from agentdeck.sessions.manager import (
    SessionManager,
)
from agentdeck.sessions.models import AgentType
from agentdeck.sessions.tmux_backend import (
    TmuxBackend,
)
from agentdeck.sessions.ui_state_detector import (
    UIStateDetector,
)

logger = structlog.get_logger()

_POLL_RE = re.compile(r"/api/v1/sessions/[^/]+/output")

load_dotenv()


def _infer_agent_type(session_id: str) -> AgentType:
    """Infer agent type from session ID prefix."""
    for t in AgentType:
        if session_id.startswith(f"agent-{t.value}-"):
            return t
    return AgentType.CLAUDE


def _normalize_whitelist_dirs(paths: list[str]) -> list[Path]:
    """Normalize configured whitelist directories."""
    normalized: list[Path] = []
    for raw in paths:
        if not raw or not raw.strip():
            continue
        try:
            path = Path(raw).expanduser().resolve()
        except Exception:
            logger.warning("invalid_rehydrate_whitelist_dir", path=raw)
            continue
        normalized.append(path)
    return normalized


def _is_whitelisted_session_dir(
    working_dir: str | None,
    whitelist_dirs: list[Path],
) -> bool:
    """True when working_dir is equal to or under a whitelist dir."""
    if not whitelist_dirs:
        return True
    if not working_dir:
        return False
    try:
        path = Path(working_dir).expanduser().resolve()
    except Exception:
        return False
    return any(path == allowed or allowed in path.parents for allowed in whitelist_dirs)


class _SamplePollingAccess(logging.Filter):
    """Show only 1-in-N access log lines for output polling."""

    def __init__(self, every: int = 60) -> None:
        super().__init__()
        self.every = every
        self._count = 0

    def filter(self, record: logging.LogRecord) -> bool:
        args = getattr(record, "args", None)
        if isinstance(args, tuple) and len(args) >= 3:
            path = args[2]
            if isinstance(path, str) and _POLL_RE.search(path):
                self._count += 1
                return (self._count % self.every) == 0
        return True


def _install_access_log_filter() -> None:
    uv_logger = logging.getLogger("uvicorn.access")
    filt = _SamplePollingAccess(every=30)
    uv_logger.addFilter(filt)


PKG_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PKG_DIR / "templates"
STATIC_DIR = PKG_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


async def _send_push(
    notifier: PushNotifier,
    sid: str,
    state: str,
    public_url: str,
) -> None:
    """Fire-and-forget push delivery in a thread."""
    try:
        await asyncio.to_thread(
            notifier.check_and_notify,
            sid,
            state,
            public_url,
        )
    except Exception:
        logger.debug("push_send_failed", session_id=sid)


async def _capture_loop(
    mgr: SessionManager,
    tmux: TmuxBackend | None = None,
    notifier: PushNotifier | None = None,
    public_url: str = "",
) -> None:
    """Background task: capture scrollback + push notify."""
    settings = get_settings()
    interval = settings.capture_interval_s
    detector = UIStateDetector()
    prev_pane: dict[str, str] = {}
    while True:
        await asyncio.sleep(interval)
        for sid in mgr.active_session_ids():
            try:
                await mgr.capture_to_log(sid)
            except Exception:
                logger.debug("capture_failed", session_id=sid)
                continue

            if notifier is None or tmux is None:
                continue
            try:
                pane = await asyncio.to_thread(tmux.capture_pane, sid)
                combined = prev_pane.get(sid, "") + "\n" + pane
                tail = "\n".join(combined.split("\n")[-20:])
                parsed = detector.parse(tail)
                prev_pane[sid] = pane
                asyncio.create_task(
                    _send_push(
                        notifier,
                        sid,
                        parsed.state,
                        public_url,
                    )
                )
            except Exception:
                logger.debug(
                    "notify_check_failed",
                    session_id=sid,
                )


@asynccontextmanager
async def lifespan(
    app: FastAPI,
) -> AsyncGenerator[None]:
    settings = get_settings()
    _install_access_log_filter()
    logger.info("starting_up", version=settings.app_version)
    rehydrate_whitelist = _normalize_whitelist_dirs(settings.rehydrate_dir_whitelist)

    tmux = TmuxBackend(
        pane_width=settings.tmux_pane_width,
        pane_height=settings.tmux_pane_height,
        scrollback_lines=settings.tmux_scrollback_lines,
    )

    state_dir = Path(settings.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    output_log = AgentOutputLog(settings.db_path)

    mgr = SessionManager(
        tmux=tmux,
        recent_dirs=settings.recent_dirs,
        state_config_path=state_dir / "config.json",
        output_log=output_log,
        capture_tail_lines=settings.capture_tail_lines,
    )
    app.state.session_manager = mgr
    app.state.output_log = output_log

    # Rehydrate live sessions from tmux
    existing_sessions = await asyncio.to_thread(tmux.list_sessions)
    live_ids: set[str] = set()
    for session_id in existing_sessions:
        if not session_id.startswith("agent-"):
            continue
        working_dir = await asyncio.to_thread(tmux.get_session_path, session_id)
        if not _is_whitelisted_session_dir(working_dir, rehydrate_whitelist):
            logger.info(
                "rehydrate_session_skipped_not_whitelisted",
                session_id=session_id,
                working_dir=working_dir,
            )
            continue
        agent_type = _infer_agent_type(session_id)
        final_dir = working_dir or settings.default_working_dir
        mgr.register_existing_session(
            session_id=session_id,
            working_dir=final_dir,
            agent_type=agent_type,
        )
        live_ids.add(session_id)
        logger.info(
            "rehydrate_session",
            session_id=session_id,
            working_dir=final_dir,
            agent_type=agent_type.value,
        )

    # Rehydrate dead sessions from output log
    for sid in output_log.session_ids():
        if sid in live_ids:
            continue
        mgr.register_dead_session(
            session_id=sid,
            working_dir="(unknown)",
            ended_at=output_log.latest_ts(sid),
        )

    # Push notifications
    push_store = PushSubscriptionStore(settings.push_subs_path)
    try:
        vapid_public_key, vapid_pem = load_or_create_vapid_keys(settings.state_dir)
        notifier: PushNotifier | None = PushNotifier(
            store=push_store,
            vapid_private_key_path=vapid_pem,
            vapid_claims={"sub": "mailto:admin@localhost"},
        )
        app.state.vapid_public_key = vapid_public_key
        logger.info("push_notifications_enabled")
    except Exception:
        logger.warning("push_notifications_disabled")
        notifier = None
        app.state.vapid_public_key = ""
    app.state.push_store = push_store
    app.state.push_notifier = notifier

    # Share templates with modules that need them
    sessions_routes.templates = templates

    # Start background output capture
    capture_task = asyncio.create_task(
        _capture_loop(
            mgr,
            tmux=tmux,
            notifier=notifier,
            public_url=settings.agentdeck_url,
        )
    )

    yield

    capture_task.cancel()
    try:
        await capture_task
    except asyncio.CancelledError:
        pass
    output_log.close()
    logger.info("shutting_down")


class _NoCacheStaticMiddleware(BaseHTTPMiddleware):
    """Add no-cache headers to static file responses."""

    async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    application.add_middleware(_NoCacheStaticMiddleware)
    application.include_router(api_router, prefix="/api/v1")
    application.mount(
        "/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="static",
    )
    return application


app = create_app()


def _load_snippets(state_dir: str) -> dict:
    """Read prompt_snippets.json from state dir."""
    path = Path(state_dir) / "prompt_snippets.json"
    if not path.exists():
        return {"global": [], "directories": {}}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"global": [], "directories": {}}


@app.get("/sw.js")
async def service_worker() -> FileResponse:
    """Serve service worker from root scope."""
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache",
            "Service-Worker-Allowed": "/",
        },
    )


@app.get("/")
async def index(request: Request):  # type: ignore[no-untyped-def]
    """Serve the main PWA page."""
    session = request.query_params.get("session")
    logger.debug("page_load", session=session)
    settings = get_settings()
    sessions = await request.app.state.session_manager.list_sessions()
    snippets = _load_snippets(settings.state_dir)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "sessions": [s.model_dump() for s in sessions],
            "default_working_dir": settings.default_working_dir,
            "session_refresh_ms": settings.session_refresh_ms,
            "prompt_snippets": snippets,
            "public_url": settings.agentdeck_url,
            "confirm_image_upload": settings.confirm_image_upload,
        },
    )
