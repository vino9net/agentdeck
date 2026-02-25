import json
from pathlib import Path

from pydantic import AliasChoices, Field, computed_field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    # API
    app_name: str = "agentdeck"
    app_version: str = "0.9.8"

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
    state_dir: str = Field(
        default=str(Path.home() / ".agentdeck"),
        validation_alias=AliasChoices("state_dir", "AGENTDECK_STATE"),
        description="Directory for state files (config.json, output.db, etc.)",
    )
    rehydrate_dir_whitelist: list[str] = []

    # Push notifications
    agentdeck_url: str = "http://127.0.0.1"

    # UI behaviour
    confirm_image_upload: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def db_path(self) -> Path:
        """SQLite database path for output log."""
        return Path(self.state_dir) / "output.db"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def push_subs_path(self) -> Path:
        """JSON file for push subscriptions."""
        return Path(self.state_dir) / "push_subscriptions.json"

    model_config = {
        "env_file": ".env",
        "extra": "ignore",
    }


_override: Settings | None = None


def get_settings() -> Settings:
    """Return the active settings instance."""
    if _override:
        return _override
    settings = Settings()
    return _load_config_file(settings)


def _load_config_file(settings: Settings) -> Settings:
    """Load and merge config.json if it exists."""
    config_path = Path(settings.state_dir) / "config.json"
    if not config_path.exists():
        return settings

    try:
        data = json.loads(config_path.read_text())
        if not isinstance(data, dict):
            return settings

        # Expand ~ in path fields
        for key in ("default_working_dir", "state_dir"):
            if key in data and isinstance(data[key], str):
                data[key] = str(Path(data[key]).expanduser())

        # Expand ~ in whitelist paths
        if "rehydrate_dir_whitelist" in data:
            whitelist = data["rehydrate_dir_whitelist"]
            if isinstance(whitelist, list):
                data["rehydrate_dir_whitelist"] = [
                    str(Path(v).expanduser()) if isinstance(v, str) else v
                    for v in whitelist
                ]

        return settings.model_copy(update=data)
    except Exception:
        return settings


def override_settings(s: Settings | None) -> None:
    """Swap in a custom Settings (use None to reset)."""
    global _override  # noqa: PLW0603
    _override = s
