from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    # API
    app_name: str = "agentdeck"
    app_version: str = "0.8.0"

    # tmux
    tmux_pane_width: int = 160
    tmux_pane_height: int = 35
    tmux_scrollback_lines: int = 2_000
    poll_interval_ms: int = 800

    # Background capture
    capture_interval_s: int = 2
    session_refresh_ms: int = 3000
    capture_tail_lines: int = 300

    # Paths
    default_working_dir: str = str(Path.home())
    state_dir: str = "state"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def db_path(self) -> Path:
        """SQLite database path for output log."""
        return Path(self.state_dir) / "output.db"

    model_config = {
        "env_file": ".env",
        "extra": "ignore",
    }


_override: Settings | None = None


def get_settings() -> Settings:
    """Return the active settings instance."""
    return _override or Settings()


def override_settings(s: Settings | None) -> None:
    """Swap in a custom Settings (use None to reset)."""
    global _override  # noqa: PLW0603
    _override = s
