"""Claude Code agent adapter."""

from agentdeck.agents.base import BaseAgent, SlashCommand

# (keys, enter) — enter=False sends as special key
SHORTCUTS: dict[str, tuple[str, bool]] = {
    "stop": ("Escape", False),
    "cancel": ("C-c", False),
    "up": ("Up", False),
    "down": ("Down", False),
    "enter": ("Enter", False),
    "tab": ("BTab", False),
}

# (text, send_enter, need_confirmation)
SLASH_COMMANDS: list[SlashCommand] = [
    ("/context", True, False),
    ("/clear", True, True),
    ("/compact", True, True),
    ("/pytest", True, False),
]


class ClaudeCodeAgent(BaseAgent):
    """Adapter for Claude Code CLI."""

    slash_commands = SLASH_COMMANDS

    def launch_command(self, working_dir: str) -> str:
        """Launch claude in the working directory."""
        return f"cd {working_dir} && claude"

    def expand_shortcut(self, text: str) -> tuple[str, bool] | None:
        return SHORTCUTS.get(text.strip().lower())
