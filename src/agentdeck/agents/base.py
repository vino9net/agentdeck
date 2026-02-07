"""Base class for coding agent adapters."""

from abc import ABC, abstractmethod

# (text_to_send, send_enter, need_confirmation)
SlashCommand = tuple[str, bool, bool]


class BaseAgent(ABC):
    """Abstract base for coding agent adapters.

    Each adapter knows how to launch a specific agent
    and what shortcuts/keybindings it responds to.
    """

    slash_commands: list[SlashCommand] = []

    @abstractmethod
    def launch_command(self, working_dir: str) -> str:
        """Shell command to start the agent."""

    @abstractmethod
    def expand_shortcut(self, text: str) -> tuple[str, bool] | None:
        """Expand a shortcut name to (keys, enter).

        Returns None if text is not a known shortcut.
        """
