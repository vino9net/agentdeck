import asyncio
import logging
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import (
    BaseHTTPMiddleware,
)
from starlette.templating import Jinja2Templates

from agentdeck.api import sessions as sessions_routes
from agentdeck.api.router import api_router
from agentdeck.config import get_settings
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

logger = structlog.get_logger()

_POLL_RE = re.compile(r"/api/v1/sessions/[^/]+/output")


def _infer_agent_type(session_id: str) -> AgentType:
    """Infer agent type from session ID prefix."""
    for t in AgentType:
        if session_id.startswith(f"agent-{t.value}-"):
            return t
    return AgentType.CLAUDE


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


async def _capture_loop(mgr: SessionManager) -> None:
    """Background task: capture scrollback for all sessions."""
    settings = get_settings()
    interval = settings.capture_interval_s
    while True:
        await asyncio.sleep(interval)
        for sid in mgr.active_session_ids():
            try:
                await mgr.capture_to_log(sid)
            except Exception:
                logger.debug("capture_failed", session_id=sid)


@asynccontextmanager
async def lifespan(
    app: FastAPI,
) -> AsyncGenerator[None]:
    settings = get_settings()
    _install_access_log_filter()
    logger.info("starting_up", version=settings.app_version)

    tmux = TmuxBackend(
        pane_width=settings.tmux_pane_width,
        pane_height=settings.tmux_pane_height,
        scrollback_lines=settings.tmux_scrollback_lines,
    )

    state_dir = Path(settings.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    recent_dirs_path = state_dir / "recent_dirs.txt"

    output_log = AgentOutputLog(settings.db_path)

    mgr = SessionManager(
        tmux=tmux,
        recent_dirs_path=recent_dirs_path,
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
        agent_type = _infer_agent_type(session_id)
        mgr.register_existing_session(
            session_id=session_id,
            working_dir=(working_dir or settings.default_working_dir),
            agent_type=agent_type,
        )
        live_ids.add(session_id)

    # Rehydrate dead sessions from output log
    for sid in output_log.session_ids():
        if sid in live_ids:
            continue
        mgr.register_dead_session(
            session_id=sid,
            working_dir="(unknown)",
            ended_at=output_log.latest_ts(sid),
        )

    # Share templates with modules that need them
    sessions_routes.templates = templates

    # Start background output capture
    capture_task = asyncio.create_task(_capture_loop(mgr))

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


@app.get("/")
async def index(request: Request):  # type: ignore[no-untyped-def]
    """Serve the main PWA page."""
    session = request.query_params.get("session")
    logger.debug("page_load", session=session)
    settings = get_settings()
    sessions = await request.app.state.session_manager.list_sessions()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "sessions": [s.model_dump() for s in sessions],
            "default_working_dir": settings.default_working_dir,
            "session_refresh_ms": settings.session_refresh_ms,
        },
    )
