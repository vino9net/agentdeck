"""Pydantic models for session management."""

from enum import StrEnum

from pydantic import BaseModel, Field


class AgentType(StrEnum):
    """Supported coding agent types."""

    CLAUDE = "claude"


class SessionCreate(BaseModel):
    """Request to create a new agent session."""

    working_dir: str = Field(description="Working directory (must exist)")
    title: str | None = Field(default=None, description="Optional session title")
    agent_type: AgentType = AgentType.CLAUDE


class SessionInfo(BaseModel):
    """Information about an active or dead session."""

    session_id: str
    agent_type: AgentType
    working_dir: str
    is_alive: bool = True
    ended_at: float | None = None


class DebugRequest(BaseModel):
    """Request to debug a session."""

    description: str = Field(description="Problem description")


class SendInput(BaseModel):
    """Input to send to a session."""

    text: str = Field(description="Text or shortcut name")


class SessionOutput(BaseModel):
    """Captured terminal output from a session."""

    session_id: str
    content: str
    changed: bool = True


class UIState(StrEnum):
    """Detected Claude Code UI state."""

    WORKING = "working"
    SELECTION = "selection"
    PROMPT = "prompt"


class SelectionItem(BaseModel):
    """A numbered option in a Claude Code selection list."""

    number: int = Field(description="1-based item number")
    label: str = Field(description="Option label text")
    description: str = Field(
        default="",
        description="Indented description below the label",
    )
    is_freeform: bool = Field(
        default=False,
        description="Whether this is a freeform text input option",
    )


class ParsedOutput(BaseModel):
    """Parsed state from raw tmux output."""

    state: UIState = UIState.WORKING
    items: list[SelectionItem] = Field(default_factory=list)
    selected_index: int = Field(
        default=0,
        description="0-based index of the currently selected item",
    )
    question: str = Field(
        default="",
        description="Question text above the selection list",
    )
    auto_response: str | None = Field(
        default=None,
        description="Text to auto-send (e.g. perf eval)",
    )


class SendSelection(BaseModel):
    """Request to select an option in a Claude Code prompt."""

    item_number: int = Field(
        description="1-based item number to select",
    )
    freeform_text: str | None = Field(
        default=None,
        description="Text to type for freeform options",
    )
