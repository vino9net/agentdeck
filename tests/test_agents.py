"""Tests for agent adapters."""

from agentdeck.agents.claude_code import ClaudeCodeAgent


def test_shortcut_expands_to_correct_key():
    """Known shortcut names map to the right tmux keys."""
    agent = ClaudeCodeAgent()
    assert agent.expand_shortcut("stop") == ("Escape", False)
    assert agent.expand_shortcut("cancel") == ("C-c", False)


def test_shortcut_is_case_insensitive():
    agent = ClaudeCodeAgent()
    assert agent.expand_shortcut("STOP") == ("Escape", False)
    assert agent.expand_shortcut("  Cancel  ") == ("C-c", False)


def test_unknown_shortcut_returns_none():
    """Non-shortcut text passes through as None."""
    agent = ClaudeCodeAgent()
    assert agent.expand_shortcut("explain this code") is None
    assert agent.expand_shortcut("deploy") is None
