"""Codex agent adapter."""

from pathlib import Path

from agentdeck.agents.base import BaseAgent, SlashCommand

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "start_agent.sh"

# Same terminal shortcuts as Claude — standard TUI keys
SHORTCUTS: dict[str, tuple[str, bool]] = {
    "stop": ("Escape", False),
    "cancel": ("C-c", False),
    "up": ("Up", False),
    "down": ("Down", False),
    "enter": ("Enter", False),
}

SLASH_COMMANDS: list[SlashCommand] = [
    ("/model", True, False),
]


class CodexAgent(BaseAgent):
    """Adapter for OpenAI Codex CLI."""

    slash_commands = SLASH_COMMANDS

    def launch_command(self, working_dir: str) -> str:
        """Launch codex in the working directory."""
        return f"{_SCRIPT} {working_dir} codex"

    def expand_shortcut(self, text: str) -> tuple[str, bool] | None:
        return SHORTCUTS.get(text.strip().lower())
