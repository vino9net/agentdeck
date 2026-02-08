"""Claude Code agent adapter."""

from pathlib import Path

from agentdeck.agents.base import BaseAgent, SlashCommand

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "start_agent.sh"

# (keys, enter) — enter=False sends as special key
SHORTCUTS: dict[str, tuple[str, bool]] = {
    "stop": ("Escape", False),
    "cancel": ("C-c", False),
    "up": ("Up", False),
    "down": ("Down", False),
    "left": ("Left", False),
    "right": ("Right", False),
    "enter": ("Enter", False),
    "tab": ("BTab", False),
}

# (text, send_enter, need_confirmation, show_nav)
SLASH_COMMANDS: list[SlashCommand] = [
    ("/clear", True, True, False),
    ("/config", True, False, True),
    ("/context", True, False, False),
    ("/compact", True, True, False),
    ("/model", True, False, True),
]


class ClaudeCodeAgent(BaseAgent):
    """Adapter for Claude Code CLI."""

    slash_commands = SLASH_COMMANDS

    def launch_command(self, working_dir: str) -> str:
        """Launch claude in the working directory."""
        return f"{_SCRIPT} {working_dir} claude"

    def expand_shortcut(self, text: str) -> tuple[str, bool] | None:
        return SHORTCUTS.get(text.strip().lower())
