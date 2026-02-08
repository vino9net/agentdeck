"""Session manager - orchestrates tmux and agents."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import structlog

from agentdeck.agents.base import BaseAgent
from agentdeck.agents.claude_code import ClaudeCodeAgent
from agentdeck.agents.codex import CodexAgent
from agentdeck.sessions.agent_output_log import AgentOutputLog
from agentdeck.sessions.clipboard import copy_image_to_clipboard
from agentdeck.sessions.models import (
    AgentType,
    ParsedOutput,
    SessionInfo,
    SessionOutput,
    UIState,
)
from agentdeck.sessions.tmux_backend import (
    TmuxBackend,
)
from agentdeck.sessions.ui_state_detector import UIStateDetector

logger = structlog.get_logger()

AGENT_REGISTRY: dict[AgentType, type[BaseAgent]] = {
    AgentType.CLAUDE: ClaudeCodeAgent,
    AgentType.CODEX: CodexAgent,
}


class SessionManager:
    """Async orchestrator for agent sessions.

    Wraps synchronous TmuxBackend calls in
    asyncio.to_thread() to keep FastAPI responsive.
    """

    def __init__(
        self,
        tmux: TmuxBackend,
        recent_dirs_path: Path,
        output_log: AgentOutputLog | None = None,
        capture_tail_lines: int = 300,
    ) -> None:
        self._tmux = tmux
        self._agents: dict[str, BaseAgent] = {}
        self._sessions: dict[str, SessionInfo] = {}
        self._last_output: dict[str, str] = {}
        self._recent_dirs_path = recent_dirs_path
        self._parser = UIStateDetector()
        self._output_log = output_log
        self._capture_tail_lines = capture_tail_lines
        self._last_tail: dict[str, list[str]] = {}
        self._last_history_size: dict[str, int] = {}

    async def create_session(
        self,
        working_dir: str,
        agent_type: AgentType = AgentType.CLAUDE,
        title: str | None = None,
    ) -> SessionInfo:
        """Create a new agent session.

        Args:
            working_dir: Must be an existing directory.
            agent_type: Which agent to launch.

        Returns:
            SessionInfo with the new session details.

        Raises:
            ValueError: If working_dir doesn't exist.
        """
        path = Path(working_dir).expanduser().resolve()
        if not path.is_dir():
            msg = f"Directory not found: {working_dir}"
            raise ValueError(msg)

        is_git = (path / ".git").is_dir()
        if not is_git:
            logger.warning(
                "not_a_git_repo",
                working_dir=str(path),
            )

        agent_cls = AGENT_REGISTRY.get(agent_type)
        if agent_cls is None:
            msg = f"Unsupported agent: {agent_type}"
            raise ValueError(msg)

        agent = agent_cls()
        session_id = self._build_session_id(path, title, agent_type)
        command = agent.launch_command(str(path))

        await asyncio.to_thread(
            self._tmux.create_session,
            session_id,
            command,
        )

        info = SessionInfo(
            session_id=session_id,
            agent_type=agent_type,
            working_dir=str(path),
        )
        self._sessions[session_id] = info
        self._agents[session_id] = agent
        await asyncio.to_thread(self._record_recent_dir, str(path))
        return info

    async def send_input(self, session_id: str, text: str) -> None:
        """Send text or shortcut to a session.

        The shortcut engine checks if the text matches
        a shortcut first. If not, sends as literal text.

        Args:
            session_id: Target session.
            text: User input or shortcut name.
        """
        self._require_alive_session(session_id)

        agent = self._get_agent(session_id)
        expanded = agent.expand_shortcut(text)
        if expanded is not None:
            keys, enter = expanded
            logger.info(
                "shortcut_expanded",
                session=session_id,
                shortcut=text,
                keys=keys,
            )
            await asyncio.to_thread(
                self._tmux.send_keys,
                session_id,
                keys,
                enter=enter,
            )
        else:
            await asyncio.to_thread(
                self._tmux.send_keys,
                session_id,
                text,
                enter=False,
                literal=True,
            )
            await asyncio.sleep(0.15)
            await asyncio.to_thread(
                self._tmux.send_keys,
                session_id,
                "Enter",
                enter=False,
            )

    async def capture_output(self, session_id: str) -> SessionOutput:
        """Capture pane content and diff against last.

        Args:
            session_id: Target session.

        Returns:
            SessionOutput with content and changed flag.
        """
        self._require_session(session_id)

        content = await asyncio.to_thread(self._tmux.capture_pane, session_id)
        previous = self._last_output.get(session_id, "")
        changed = content != previous
        self._last_output[session_id] = content

        return SessionOutput(
            session_id=session_id,
            content=content,
            changed=changed,
        )

    def active_session_ids(self) -> list[str]:
        """Session IDs that are alive (for capture loop)."""
        return [sid for sid, info in self._sessions.items() if info.is_alive]

    _FINGERPRINT_SIZE = 5

    async def capture_to_log(self, session_id: str) -> None:
        """Capture scrollback delta and append to AgentOutputLog.

        Only captures scrollback (lines above the visible pane).
        Skips capture when nothing has scrolled since last time.
        On process death, does a final full capture and cleans up.
        """
        if self._output_log is None:
            return

        dead = await asyncio.to_thread(self._tmux.is_process_dead, session_id)
        if dead:
            logger.info(
                "capture_process_dead",
                session=session_id,
            )
            await self._capture_final(session_id)
            return

        history_size = await asyncio.to_thread(self._tmux.get_history_size, session_id)
        prev_size = self._last_history_size.get(session_id)
        if prev_size is not None and history_size == prev_size:
            return  # nothing scrolled

        lines = await asyncio.to_thread(self._tmux.capture_scrollback, session_id)
        scrollback = lines[:history_size]

        if not scrollback:
            self._last_history_size[session_id] = history_size
            return

        prev = self._last_tail.get(session_id)
        if prev is None:
            new_lines = scrollback
        else:
            idx = self._find_overlap(prev, scrollback)
            new_lines = scrollback[idx:] if idx >= 0 else scrollback

        if new_lines:
            self._output_log.append(session_id, new_lines)
        self._last_tail[session_id] = scrollback
        self._last_history_size[session_id] = history_size

    async def _capture_final(self, session_id: str) -> None:
        """Final full capture on process death."""
        lines = await asyncio.to_thread(self._tmux.capture_scrollback, session_id)
        prev = self._last_tail.get(session_id)
        if prev:
            idx = self._find_overlap(prev, lines)
            new_lines = lines[idx:] if idx >= 0 else lines
        else:
            new_lines = lines

        if new_lines and self._output_log is not None:
            self._output_log.append(session_id, new_lines)

        logger.info(
            "capture_final",
            session=session_id,
            total_lines=len(lines),
            new_lines=len(new_lines) if new_lines else 0,
            had_prev=prev is not None,
        )

        await asyncio.to_thread(self._tmux.kill_session, session_id)
        self._mark_dead(session_id)
        self._last_tail.pop(session_id, None)
        self._last_history_size.pop(session_id, None)
        self._last_output.pop(session_id, None)
        self._agents.pop(session_id, None)

    def _find_overlap(
        self,
        previous: list[str],
        current: list[str],
    ) -> int:
        """Find where new content starts in current capture.

        Takes the last few lines of the previous capture as a
        fingerprint and scans current for a matching sequence.

        Returns:
            Index in current after the overlap, or -1 if the
            fingerprint was not found.
        """
        fp_size = min(self._FINGERPRINT_SIZE, len(previous))
        if fp_size == 0:
            return 0
        fingerprint = previous[-fp_size:]
        limit = len(current) - fp_size + 1
        for i in range(limit):
            if current[i : i + fp_size] == fingerprint:
                return i + fp_size
        return -1

    def parse_output(self, raw: str) -> ParsedOutput:
        """Parse raw terminal output into UI state."""
        return self._parser.parse(raw)

    async def send_raw_keys(
        self, session_id: str, keys: str, *, enter: bool = False
    ) -> None:
        """Send raw keys to a session without shortcut expansion."""
        self._require_alive_session(session_id)
        await asyncio.to_thread(
            self._tmux.send_keys,
            session_id,
            keys,
            enter=enter,
            literal=True,
        )

    async def paste_image(self, session_id: str, path: str, fmt: str) -> None:
        """Copy image to clipboard and paste into session.

        Args:
            session_id: Target session.
            path: Absolute path to the image file.
            fmt: Image format — "png" or "jpeg".
        """
        self._require_alive_session(session_id)
        await asyncio.to_thread(copy_image_to_clipboard, path, fmt)
        await asyncio.sleep(0.1)
        await asyncio.to_thread(
            self._tmux.send_keys,
            session_id,
            "C-v",
            enter=False,
        )

    async def send_selection(
        self,
        session_id: str,
        item_number: int,
        freeform_text: str | None = None,
    ) -> None:
        """Select an option in a numbered prompt.

        Arrow-navigable lists (›/❯ marker): send Up/Down + Enter.
        Non-navigable lists (no marker): type the number + Enter.

        Args:
            session_id: Target session.
            item_number: 1-based item number to select.
            freeform_text: Text to type for freeform options.
        """
        self._require_alive_session(session_id)

        raw = await asyncio.to_thread(self._tmux.capture_pane, session_id)
        parsed = self._parser.parse(raw)

        # Find target index (0-based) from item_number
        target_index = None
        for i, item in enumerate(parsed.items):
            if item.number == item_number:
                target_index = i
                break

        if target_index is None:
            msg = f"Item {item_number} not found in selection"
            raise ValueError(msg)

        if parsed.arrow_navigable:
            # Arrow-driven: move cursor then press Enter
            delta = target_index - parsed.selected_index
            key = "Down" if delta > 0 else "Up"
            for _ in range(abs(delta)):
                await asyncio.to_thread(
                    self._tmux.send_keys,
                    session_id,
                    key,
                    enter=False,
                )
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.15)
            await asyncio.to_thread(
                self._tmux.send_keys,
                session_id,
                "Enter",
                enter=False,
            )
        else:
            # Number-input: type the digit then Enter
            await asyncio.to_thread(
                self._tmux.send_keys,
                session_id,
                str(item_number),
                enter=False,
                literal=True,
            )
            await asyncio.sleep(0.15)
            await asyncio.to_thread(
                self._tmux.send_keys,
                session_id,
                "Enter",
                enter=False,
            )

        # For freeform: wait then type the text
        if freeform_text:
            await asyncio.sleep(0.2)
            await asyncio.to_thread(
                self._tmux.send_keys,
                session_id,
                freeform_text,
                enter=True,
                literal=True,
            )

    async def kill_session(self, session_id: str) -> None:
        """Kill a session and mark it dead.

        Args:
            session_id: Session to kill.
        """
        self._require_session(session_id)
        await asyncio.to_thread(self._tmux.kill_session, session_id)
        self._mark_dead(session_id)
        self._last_output.pop(session_id, None)
        self._last_history_size.pop(session_id, None)
        self._last_tail.pop(session_id, None)
        self._agents.pop(session_id, None)

    async def list_sessions(self) -> list[SessionInfo]:
        """List all tracked sessions.

        Only polls tmux for sessions still marked alive.
        Auto-detects tmux death and marks them dead.
        """
        for sid, info in self._sessions.items():
            if not info.is_alive:
                continue
            alive = await asyncio.to_thread(self._tmux.is_alive, sid)
            if not alive:
                self._mark_dead(sid)
        return list(self._sessions.values())

    async def get_session(self, session_id: str) -> SessionInfo:
        """Get info for a specific session."""
        self._require_session(session_id)
        info = self._sessions[session_id]
        if info.is_alive:
            alive = await asyncio.to_thread(self._tmux.is_alive, session_id)
            if not alive:
                self._mark_dead(session_id)
        return info

    def _get_agent(self, session_id: str) -> BaseAgent:
        """Get the agent for a session, falling back to Claude."""
        agent = self._agents.get(session_id)
        if agent is not None:
            return agent
        info = self._sessions.get(session_id)
        agent_type = info.agent_type if info else AgentType.CLAUDE
        cls = AGENT_REGISTRY.get(agent_type, ClaudeCodeAgent)
        agent = cls()
        self._agents[session_id] = agent
        return agent

    def _require_session(self, session_id: str) -> None:
        """Raise if session_id is not tracked."""
        if session_id not in self._sessions:
            msg = f"Unknown session: {session_id}"
            raise KeyError(msg)

    def _require_alive_session(self, session_id: str) -> None:
        """Raise if session is not tracked or is dead."""
        self._require_session(session_id)
        if not self._sessions[session_id].is_alive:
            msg = f"Session ended: {session_id}"
            raise ValueError(msg)

    def _mark_dead(self, session_id: str) -> None:
        """Mark a session as dead."""
        info = self._sessions.get(session_id)
        if info and info.is_alive:
            info.is_alive = False
            info.ended_at = time.time()

    def _build_session_id(
        self,
        path: Path,
        title: str | None,
        agent_type: AgentType = AgentType.CLAUDE,
    ) -> str:
        """Generate a session id from the directory name.

        Uses the first 20 chars of the directory name. If a session
        for the same directory already exists or the id collides,
        adds a numeric suffix. Non-claude agents get a prefix,
        e.g. "agent-codex-myproject".
        """
        name_source = title.strip() if title else path.name
        base_name = self._slug_dir_name(name_source)[:20] or "session"
        base = f"agent-{agent_type.value}-{base_name}"
        working_dir = str(path)
        has_same_dir = any(
            info.working_dir == working_dir for info in self._sessions.values()
        )
        if not has_same_dir and base not in self._sessions:
            return base

        suffix = 2
        while True:
            candidate = f"{base}-{suffix}"
            if candidate not in self._sessions:
                return candidate
            suffix += 1

    def register_existing_session(
        self,
        session_id: str,
        working_dir: str,
        agent_type: AgentType = AgentType.CLAUDE,
    ) -> None:
        """Register a tmux session that already exists."""
        self._sessions[session_id] = SessionInfo(
            session_id=session_id,
            agent_type=agent_type,
            working_dir=working_dir,
        )

    def remove_dead_session(self, session_id: str) -> None:
        """Soft-delete a dead session and its log data."""
        self._require_session(session_id)
        info = self._sessions[session_id]
        if info.is_alive:
            msg = f"Session is still alive: {session_id}"
            raise ValueError(msg)
        if self._output_log is not None:
            self._output_log.soft_delete(session_id)
        self._sessions.pop(session_id, None)
        self._last_output.pop(session_id, None)
        self._agents.pop(session_id, None)

    def register_dead_session(
        self,
        session_id: str,
        working_dir: str,
        ended_at: float | None = None,
        agent_type: AgentType = AgentType.CLAUDE,
    ) -> None:
        """Register a session that is no longer alive."""
        self._sessions[session_id] = SessionInfo(
            session_id=session_id,
            agent_type=agent_type,
            working_dir=working_dir,
            is_alive=False,
            ended_at=ended_at,
        )

    def _slug_dir_name(self, name: str) -> str:
        """Sanitize directory name for tmux session ids."""
        result: list[str] = []
        for ch in name.strip().lower():
            if ch.isalnum():
                result.append(ch)
            elif ch in {"-", "_"}:
                result.append(ch)
            else:
                result.append("-")
        slug = "".join(result).strip("-")
        return slug or "session"

    def list_recent_dirs(self) -> list[str]:
        """Return recent working directories, newest first."""
        return self._load_recent_dirs()

    def _record_recent_dir(self, working_dir: str) -> None:
        home = str(Path.home())
        if working_dir.startswith(home):
            working_dir = "~" + working_dir[len(home) :]
        recent = self._load_recent_dirs()
        if working_dir in recent:
            recent.remove(working_dir)
        recent.insert(0, working_dir)
        recent = recent[:10]
        self._recent_dirs_path.parent.mkdir(parents=True, exist_ok=True)
        self._recent_dirs_path.write_text("\n".join(recent))

    def _load_recent_dirs(self) -> list[str]:
        if not self._recent_dirs_path.exists():
            return []
        data = self._recent_dirs_path.read_text().splitlines()
        home = str(Path.home())
        result: list[str] = []
        for line in data:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(home):
                stripped = "~" + stripped[len(home) :]
            result.append(stripped)
        return result

    async def send_debug_prompt(
        self,
        session_id: str,
        description: str,
        tmux_capture: str,
        agent_to_debug: AgentType,
    ) -> None:
        """Wait for Claude to be ready, then send debug prompt.

        Polls capture_output + parse_output every 2s for up to
        60s, waiting for UIState.PROMPT before sending.
        """
        for _ in range(30):
            await asyncio.sleep(2)
            try:
                output = await self.capture_output(session_id)
            except KeyError:
                return
            parsed = self.parse_output(output.content)
            if parsed.state == UIState.PROMPT:
                break
        else:
            logger.warning(
                "debug_prompt_timeout",
                session=session_id,
            )
            return

        message = (
            "first read docs/architecture.md to understand "
            "the application architecture.\n\n"
            f"User using {agent_to_debug.value} "
            f"reported this issue:\n{description}\n\n"
            "just analyze the root cause and do not "
            "change the code just yet. "
            "below is the tmux capture :\n\n"
            f"<tmux-capture>\n{tmux_capture}\n</tmux-capture>"
        )
        await self.send_input(session_id, message)
        await asyncio.sleep(0.3)
        await asyncio.to_thread(
            self._tmux.send_keys,
            session_id,
            "Enter",
            enter=False,
        )
