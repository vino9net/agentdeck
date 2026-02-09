"""REST API for session management."""

import html
import json
import re
from pathlib import Path

import structlog
from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, Response
from markupsafe import Markup
from starlette.templating import Jinja2Templates

from agentdeck.sessions.models import (
    DebugRequest,
    SendInput,
    SendSelection,
    SessionCreate,
    SessionInfo,
)

logger = structlog.get_logger()

router = APIRouter()

# Set by main.py during startup
templates: Jinja2Templates | None = None

_HRULE_RE = re.compile(r"^[\s]*[─╌╍┄┅┈┉━]{3,}[\s]*$")

# Status-bar tokens right-aligned with long space runs; collapse them.
#   "? for shortcuts"
#   "82% context left"
#   "shift+tab to cycle"
_STATUS_BAR_RE = re.compile(
    r"\s{3,}(\?\s+for\s+shortcuts"
    r"|\d+% context left"
    r"|shift\+tab to cycle)"
)

# Box-drawing detection patterns
_TABLE_TOP_RE = re.compile(r"^[│┌][─┬]+[┐│]?\s*$")
_TABLE_SEP_RE = re.compile(r"^[│├][─┼]+[┤│]?\s*$")
_TABLE_BOT_RE = re.compile(r"^[│└][─┴]+[┘│]?\s*$")
_PANEL_TOP_RE = re.compile(r"^[╭┌][─]+[╮┐]\s*$")
_PANEL_BOT_RE = re.compile(r"^[╰└][─]+[╯┘]\s*$")
_PANEL_MID_RE = re.compile(r"^│(.*)│\s*$")


def _escape_cell(text: str) -> str:
    """Escape HTML and insert <wbr> after underscores."""
    escaped = html.escape(text)
    return escaped.replace("_", "_<wbr>")


def _split_table_row(line: str) -> list[str]:
    """Split a table data row by │ separators."""
    stripped = line.strip()
    if stripped.startswith("│"):
        stripped = stripped[1:]
    if stripped.endswith("│"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("│")]


def _render_table(lines: list[str]) -> str:
    """Convert box-drawing table lines to an HTML table."""
    rows: list[list[str]] = []
    for line in lines:
        s = line.strip()
        # Skip border/separator lines
        if _TABLE_TOP_RE.match(s) or _TABLE_SEP_RE.match(s) or _TABLE_BOT_RE.match(s):
            continue
        if "│" in s:
            rows.append(_split_table_row(s))

    if not rows:
        return ""

    parts = ['<table class="terminal-table">']
    # First row is header
    parts.append("<thead><tr>")
    for cell in rows[0]:
        parts.append(f"<th>{_escape_cell(cell)}</th>")
    parts.append("</tr></thead>")
    # Remaining rows are body
    if len(rows) > 1:
        parts.append("<tbody>")
        for row in rows[1:]:
            parts.append("<tr>")
            for cell in row:
                parts.append(f"<td>{_escape_cell(cell)}</td>")
            parts.append("</tr>")
        parts.append("</tbody>")
    parts.append("</table>")
    return "".join(parts)


def _render_panel(lines: list[str]) -> str:
    """Convert box-drawing panel lines to an HTML div.

    Inner content is fed back through _convert_blocks() so
    nested tables, hrules, etc. are rendered properly.
    """
    content_lines: list[str] = []
    for line in lines:
        m = _PANEL_MID_RE.match(line)
        if m:
            text = m.group(1)
            if text.endswith(" "):
                text = text[:-1]
            if text.startswith(" "):
                text = text[1:]
            content_lines.append(text)
    inner = "\n".join(_convert_blocks(content_lines))
    return f'<div class="terminal-panel">{inner}</div>'


def _is_table_top(line: str) -> bool:
    s = line.strip()
    return bool(_TABLE_TOP_RE.match(s)) and "┬" in s


def _is_panel_top(line: str) -> bool:
    s = line.strip()
    return bool(_PANEL_TOP_RE.match(s)) and "┬" not in s


def _convert_blocks(lines: list[str]) -> list[str]:
    """Scan lines for box-drawing blocks, convert to HTML."""
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Check for multi-column table start
        if _is_table_top(line):
            block = [line]
            j = i + 1
            while j < len(lines):
                block.append(lines[j])
                if _TABLE_BOT_RE.match(lines[j].strip()):
                    break
                j += 1
            rendered = _render_table(block)
            if rendered:
                result.append(rendered)
            else:
                result.extend(html.escape(ln) for ln in block)
            i = j + 1
            continue

        # Check for panel start
        if _is_panel_top(line):
            block = [line]
            j = i + 1
            while j < len(lines):
                block.append(lines[j])
                if _PANEL_BOT_RE.match(lines[j].strip()):
                    break
                j += 1
            result.append(_render_panel(block))
            i = j + 1
            continue

        # Headless panel: │...│ lines without a top border
        # (top border was in a previous chunk)
        if _PANEL_MID_RE.match(line):
            block = [line]
            j = i + 1
            while j < len(lines):
                if _PANEL_BOT_RE.match(lines[j].strip()):
                    block.append(lines[j])
                    break
                if _PANEL_MID_RE.match(lines[j]):
                    block.append(lines[j])
                    j += 1
                else:
                    break
            else:
                # Reached end without bottom border
                j = i + len(block)
            if block and (j < len(lines) or _PANEL_BOT_RE.match(block[-1].strip())):
                result.append(_render_panel(block))
                i = j + 1
                continue
            # Not a panel — fall through

        # Regular line — hrule or escaped text
        if _HRULE_RE.match(line):
            result.append('<hr class="terminal-hr">')
        else:
            escaped = html.escape(line)
            # Collapse long space runs before status-bar tokens
            escaped = _STATUS_BAR_RE.sub(r"  \1", escaped)
            result.append(escaped)
        i += 1

    return result


def _terminal_to_html(raw: str) -> Markup:
    """Convert raw terminal text to HTML.

    Handles horizontal rules, box-drawing tables, and panels.
    """
    lines = raw.split("\n")
    parts = _convert_blocks(lines)
    return Markup("\n".join(parts))  # noqa: S704


def _mgr(request: Request):  # type: ignore[no-untyped-def]
    return request.app.state.session_manager


@router.post("", status_code=201)
async def create_session(body: SessionCreate, request: Request) -> SessionInfo:
    """Create a new agent session."""
    try:
        return await _mgr(request).create_session(
            working_dir=body.working_dir,
            agent_type=body.agent_type,
            title=body.title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
async def list_sessions(
    request: Request,
) -> list[SessionInfo]:
    """List all active sessions."""
    return await _mgr(request).list_sessions()


@router.get("/slash-commands")
async def list_slash_commands(
    request: Request,
    session_id: str | None = None,
) -> list[dict[str, object]]:
    """List slash commands for the session's agent."""
    mgr = _mgr(request)
    agent = mgr._get_agent(session_id) if session_id else None
    commands = agent.slash_commands if agent else []
    return [
        {
            "text": text,
            "enter": enter,
            "confirm": confirm,
            "nav": nav,
        }
        for text, enter, confirm, nav in commands
    ]


@router.get("/recent-dirs")
async def list_recent_dirs(request: Request) -> list[str]:
    """List recently used working directories."""
    return _mgr(request).list_recent_dirs()


@router.get("/{session_id}")
async def get_session(session_id: str, request: Request) -> SessionInfo:
    """Get details for a session."""
    try:
        return await _mgr(request).get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{session_id}/input")
async def send_input(
    session_id: str,
    body: SendInput,
    request: Request,
) -> dict[str, str]:
    """Send input text or shortcut to a session."""
    try:
        await _mgr(request).send_input(session_id, body.text)
        return {"status": "sent"}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{session_id}/select")
async def send_selection(
    session_id: str,
    body: SendSelection,
    request: Request,
) -> dict[str, str]:
    """Select an option in a Claude Code prompt."""
    try:
        await _mgr(request).send_selection(
            session_id,
            body.item_number,
            body.freeform_text,
        )
        return {"status": "selected"}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{session_id}/debug", status_code=201)
async def debug_session(
    session_id: str,
    body: DebugRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> SessionInfo:
    """Spawn a debug session to analyze the current session."""
    mgr = _mgr(request)
    try:
        original = await mgr.get_session(session_id)
        output = await mgr.capture_output(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    server_dir = str(Path(__file__).resolve().parents[3])
    new_session = await mgr.create_session(
        working_dir=server_dir,
        title="debug",
    )
    background_tasks.add_task(
        mgr.send_debug_prompt,
        new_session.session_id,
        body.description,
        output.content,
        original.agent_type,
    )
    return new_session


_ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg"}
_EXT_MAP = {"image/png": "png", "image/jpeg": "jpg"}


@router.post("/{session_id}/image")
async def paste_image(
    session_id: str,
    file: UploadFile,
    request: Request,
) -> dict[str, str]:
    """Upload an image and paste it into the session."""
    ct = file.content_type or ""
    if ct not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image type: {ct}",
        )

    ext = _EXT_MAP[ct]
    fmt = "jpeg" if ext == "jpg" else "png"
    tmp_dir = Path("./tmp")
    tmp_dir.mkdir(exist_ok=True)
    tmp_path = tmp_dir / f"paste-{session_id}.{ext}"

    try:
        data = await file.read()
        tmp_path.write_bytes(data)

        mgr = _mgr(request)
        try:
            await mgr.paste_image(session_id, str(tmp_path.resolve()), fmt)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return {"status": "pasted"}
    finally:
        tmp_path.unlink(missing_ok=True)


@router.delete("/{session_id}")
async def kill_session(
    session_id: str,
    request: Request,
) -> dict[str, str]:
    """Kill or remove a session.

    Alive sessions are force-killed immediately.
    Dead sessions are removed from tracking.
    """
    mgr = _mgr(request)
    try:
        info = await mgr.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if info.is_alive:
        await mgr.kill_session(session_id)
        return {"status": "killed"}

    mgr.remove_dead_session(session_id)
    return {"status": "removed"}


@router.get("/{session_id}/output")
async def get_output(
    session_id: str,
    request: Request,
    force: bool = False,
    mode: str = "live",
    before: float | None = None,
    limit: int = 50,
) -> Response:
    """Capture terminal output or read history.

    mode=live (default): returns HTML fragment from the
        live tmux pane. 200 when changed, 204 when not.
    mode=history: returns JSON chunks from AgentOutputLog.
        Use `before` (unix timestamp) to paginate backwards.
    """
    if mode == "history":
        return await _get_history(session_id, request, before, limit)

    mgr = _mgr(request)

    # Dead sessions have no live tmux pane
    try:
        info = await mgr.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not info.is_alive:
        return HTMLResponse(
            content=(
                '<div class="text-center text-base-content/50 py-8">Session ended</div>'
            )
        )

    try:
        output = await mgr.capture_output(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not force and not output.changed and output.content:
        return Response(status_code=204)

    safe_content = _terminal_to_html(output.content)
    if templates is not None:
        html_str = templates.get_template("partials/terminal.html").render(
            content=safe_content, session_id=session_id
        )
    else:
        html_str = f'<pre id="terminal-output">{safe_content}</pre>'

    # Parse UI state and append as OOB swap
    parsed = mgr.parse_output(output.content)
    if output.changed:
        logger.debug(
            "ui_state",
            session=session_id,
            state=parsed.state,
            items=len(parsed.items),
        )
    if parsed.auto_response:
        logger.info(
            "auto_response",
            session=session_id,
            response=parsed.auto_response,
        )
        try:
            await mgr.send_raw_keys(session_id, parsed.auto_response)
        except Exception:
            logger.warning(
                "auto_response_failed",
                session=session_id,
            )
    state_json = json.dumps(parsed.model_dump())
    escaped = html.escape(state_json, quote=True)
    oob_div = (
        f'<div id="ui-state-data" hx-swap-oob="true"'
        f' data-state="{escaped}"'
        f' style="display:none"></div>'
    )
    html_str += oob_div

    return HTMLResponse(content=html_str)


async def _get_history(
    session_id: str,
    request: Request,
    before: float | None,
    limit: int,
) -> Response:
    """Read historical output chunks from AgentOutputLog."""
    output_log = getattr(request.app.state, "output_log", None)
    if output_log is None:
        raise HTTPException(status_code=503, detail="Output log not available")

    limit = min(limit, 200)
    page = output_log.read(session_id, before=before, limit=limit)
    logger.debug(
        "history_load",
        session_id=session_id,
        before=before,
        limit=limit,
        chunks=len(page.chunks),
        earliest_ts=page.earliest_ts,
    )
    return Response(
        content=json.dumps(
            {
                "chunks": [
                    {
                        "ts": c.ts,
                        "content": str(_terminal_to_html(c.content)),
                    }
                    for c in page.chunks
                ],
                "earliest_ts": page.earliest_ts,
            }
        ),
        media_type="application/json",
    )
