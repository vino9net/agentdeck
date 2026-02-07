"""Thin synchronous wrapper around libtmux.

All methods are synchronous. The SessionManager wraps
them in asyncio.to_thread() to avoid blocking the event
loop.
"""

import structlog
from libtmux import Server
from libtmux._internal.query_list import ObjectDoesNotExist

logger = structlog.get_logger()


class TmuxBackend:
    """Manages tmux sessions via libtmux."""

    def __init__(
        self,
        pane_width: int = 200,
        pane_height: int = 50,
        scrollback_lines: int = 2_000,
    ) -> None:
        self._pane_width = pane_width
        self._pane_height = pane_height
        self._scrollback_lines = scrollback_lines
        self._server: Server | None = None

    @property
    def server(self) -> Server:
        """Lazy-init the libtmux Server."""
        if self._server is None:
            self._server = Server()
        return self._server

    def _find_session(self, session_name: str):
        """Look up a session by name, returning None if missing."""
        try:
            return self.server.sessions.get(
                session_name=session_name,
            )
        except ObjectDoesNotExist:
            return None

    def create_session(
        self,
        session_name: str,
        window_command: str,
    ) -> str:
        """Create a new tmux session.

        Args:
            session_name: Unique name for the session.
            window_command: Shell command to run in the
                session window.

        Returns:
            The session name.
        """
        session = self.server.new_session(
            session_name=session_name,
            window_command=window_command,
            x=self._pane_width,
            y=self._pane_height,
        )
        session.cmd(
            "set-option",
            "history-limit",
            str(self._scrollback_lines),
        )
        session.set_option("remain-on-exit", "on")
        logger.info(
            "tmux_session_created",
            session=session_name,
            command=window_command,
        )
        return session.name  # type: ignore[return-value]

    def send_keys(
        self,
        session_name: str,
        keys: str,
        *,
        enter: bool = True,
        literal: bool = False,
    ) -> None:
        """Send keys to the active pane of a session.

        Args:
            session_name: Target session name.
            keys: Text or special key name to send.
            enter: Whether to press Enter after.
            literal: Send keys literally (no tmux
                key-name interpretation).
        """
        session = self._find_session(session_name)
        if session is None:
            msg = f"Session not found: {session_name}"
            raise ValueError(msg)
        pane = session.active_pane
        if pane is None:
            msg = f"No active pane: {session_name}"
            raise ValueError(msg)
        pane.send_keys(keys, enter=enter, literal=literal)

    def capture_scrollback(
        self,
        session_name: str,
        tail: int | None = None,
    ) -> list[str]:
        """Capture scrollback of the active pane.

        Args:
            session_name: Target session name.
            tail: If set, capture only the last N lines
                of scrollback. None captures everything.

        Returns:
            Scrollback lines.
        """
        session = self._find_session(session_name)
        if session is None:
            msg = f"Session not found: {session_name}"
            raise ValueError(msg)
        pane = session.active_pane
        if pane is None:
            msg = f"No active pane: {session_name}"
            raise ValueError(msg)
        start = f"-{tail}" if tail is not None else "-"
        lines: list[str] = pane.capture_pane(  # type: ignore[assignment]
            start=start,
        )
        return lines

    def capture_pane(self, session_name: str) -> str:
        """Capture visible content of the active pane.

        Args:
            session_name: Target session name.

        Returns:
            The pane text content.
        """
        session = self._find_session(session_name)
        if session is None:
            msg = f"Session not found: {session_name}"
            raise ValueError(msg)
        pane = session.active_pane
        if pane is None:
            msg = f"No active pane: {session_name}"
            raise ValueError(msg)
        lines: list[str] = pane.capture_pane()  # type: ignore[assignment]
        return "\n".join(lines)

    def kill_session(self, session_name: str) -> None:
        """Kill a tmux session.

        Args:
            session_name: Session to kill.
        """
        session = self._find_session(session_name)
        if session is None:
            logger.warning(
                "tmux_session_not_found",
                session=session_name,
            )
            return
        session.kill()
        logger.info(
            "tmux_session_killed",
            session=session_name,
        )

    def get_history_size(self, session_name: str) -> int:
        """Return the number of scrollback lines above the pane."""
        session = self._find_session(session_name)
        if session is None:
            return 0
        pane = session.active_pane
        if pane is None:
            return 0
        return int(pane.history_size)  # type: ignore[arg-type]

    def is_process_dead(self, session_name: str) -> bool:
        """Check if the pane's process has exited.

        Requires remain-on-exit to be set on the session,
        otherwise the pane disappears on process death.
        """
        session = self._find_session(session_name)
        if session is None:
            return False
        pane = session.active_pane
        if pane is None:
            return False
        return pane.pane_dead_status is not None

    def is_alive(self, session_name: str) -> bool:
        """Check if a session exists and is running."""
        return self._find_session(session_name) is not None

    def list_sessions(self) -> list[str]:
        """List all tmux session names."""
        return [s.name for s in self.server.sessions if s.name is not None]

    def get_session_path(self, session_name: str) -> str | None:
        """Get the current path of the active pane."""
        session = self._find_session(session_name)
        if session is None:
            return None
        pane = session.active_pane
        if pane is None:
            return None
        current_path = getattr(pane, "current_path", None)
        if current_path:
            return current_path
        try:
            result = pane.cmd(  # type: ignore[attr-defined]
                "display-message",
                "-p",
                "-t",
                pane.pane_id,  # type: ignore[attr-defined]
                "#{pane_current_path}",
            )
        except Exception:
            return None
        if getattr(result, "stdout", None):
            return result.stdout[0]
        return None
