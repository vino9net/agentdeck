"""Tests for UIStateDetector with realistic tmux captures."""

import pytest

from agentdeck.sessions.models import UIState
from agentdeck.sessions.ui_state_detector import UIStateDetector

FOOTER = "\nEnter to select · ↑/↓ to navigate · Esc to cancel"


@pytest.fixture()
def parser():
    return UIStateDetector()


# ── Selection state fixtures ────────────────────────────

SELECTION_BASIC = f"""\
  What would you like to do?
  ❯ 1. Yes, proceed
    2. No, cancel
    3. Type something.
{FOOTER}
"""

SELECTION_WITH_DESCRIPTIONS = f"""\
  Which file should I edit?
  ❯ 1. src/main.py
        The main entry point
    2. src/utils.py
        Utility functions
    3. Type something.
{FOOTER}
"""

SELECTION_CURSOR_ON_SECOND = f"""\
  Allow this action?
    1. Allow once
  ❯ 2. Allow always
    3. Deny
{FOOTER}
"""

# Realistic Claude Code capture (no ❯ marker, has hrule between items)
SELECTION_REAL_CAPTURE = """\
  What would you like to learn about tmux?
  1. Basics & getting started
     Introduction to tmux sessions, windows, and panes
  2. Windows, panes & navigation
     Splitting panes, switching windows, and managing layouts
  3. Config & keybindings
     Customizing .tmux.conf, remapping prefix key, and plugins
  4. Scripting & automation
     Automating tmux workflows with scripts and tmuxinator/tmuxp
  5. Type something.
────────────────────────────────────────────────────────────────
  6. Chat about this

Enter to select · ↑/↓ to navigate · Esc to cancel"""

# Permission dialog: question header, no standard footer
SELECTION_PERMISSION_NO_FOOTER = """\
  Allow Claude to execute Bash(git push origin main)?
  ❯ 1. Allow once
    2. Allow always for this session
    3. Deny
"""

# Numbered list scrolled far above bottom (stale)
SELECTION_SCROLLED_AWAY = """\
  Pick a color?
  1. Red
  2. Blue
  3. Green

  ...lots of output below...
  line
  line
  line
  line
  line
  line
  line
"""

# Permission prompt with tmux pane padding (trailing blank lines)
SELECTION_PERMISSION_PADDED = (
    "⏺ Bash(git checkout -- src/app.js)\n"
    "  ⎿  Running…\n"
    "\n"
    "─" * 80 + "\n"
    " Bash command\n"
    "\n"
    "   git checkout -- src/app.js\n"
    "   Revert app.js to original state\n"
    "\n"
    " Do you want to proceed?\n"
    " ❯ 1. Yes\n"
    "   2. Yes, and don't ask again for git checkout"
    " commands\n"
    "      /Users/lee/Projects/agentdeck\n"
    "   3. No\n"
    "\n"
    " Esc to cancel · Tab to amend · ctrl+e to explain\n" + "\n" * 16  # tmux pane padding
)

# Codex number-input selection (no marker, question ends with :)
SELECTION_CODEX_NUMBER_INPUT = """\
• Pick one option:

  1. Build a quick feature in this repo
  2. Debug a specific bug
  3. Review architecture and suggest improvements
  4. Add/expand tests
  5. Explain one module in depth

› Explain this codebase

  ? for shortcuts                                         82% context left
"""

# Numbered list with neither question header nor footer
NUMBERED_LIST_NO_SIGNAL = """\
  Here are the results
  1. First item
  2. Second item
  3. Third item
"""

# ── Working state fixtures ──────────────────────────────

WORKING_SPINNER = """\
✳ Moonwalking… (thought for 3s)
"""

WORKING_SPINNER_COLLOQUIAL = """\
✳ Hustlin'… (thought for 2s)
"""

WORKING_SPINNER_LONG_TEXT = """\
· Renaming OutputLog to AgentOutputLog across codebase… (1m 50s)
"""

WORKING_SPINNER_TOOL_USE = """\
⏺ Reading 1 file… (ctrl+o to expand)
"""

WORKING_SPINNER_COMPACT = """\
✻ compacting conversation…
"""

WORKING_SURVEY = """\
  Some output above
  1: Bad    2: Fine    3: Good    0: Dismiss
"""

# ── Prompt state fixtures ───────────────────────────────

PROMPT_BASIC = """\
  Some output text here
─────────────────────────────
›
─────────────────────────────
"""

PROMPT_EMPTY = ""

PROMPT_PLAIN_TEXT = """\
  Here is the code I found:
  def hello():
      print("world")
"""


class TestSelectionState:
    def test_basic_selection(self, parser):
        result = parser.parse(SELECTION_BASIC)
        assert result.state == UIState.SELECTION
        assert len(result.items) == 3
        assert result.items[0].number == 1
        assert result.items[0].label == "Yes, proceed"
        assert result.items[1].label == "No, cancel"
        assert result.selected_index == 0

    def test_descriptions(self, parser):
        result = parser.parse(SELECTION_WITH_DESCRIPTIONS)
        assert result.items[0].description == "The main entry point"
        assert result.items[1].description == "Utility functions"

    def test_cursor_with_marker(self, parser):
        result = parser.parse(SELECTION_CURSOR_ON_SECOND)
        assert result.state == UIState.SELECTION
        assert result.selected_index == 1
        assert len(result.items) == 3

    def test_real_capture_no_marker(self, parser):
        """Realistic capture without ❯ marker but with footer."""
        result = parser.parse(SELECTION_REAL_CAPTURE)
        assert result.state == UIState.SELECTION
        assert len(result.items) == 6
        assert result.items[0].label == "Basics & getting started"
        assert result.items[4].label == "Type something."
        assert result.items[5].label == "Chat about this"
        assert result.selected_index == 0  # default

    def test_real_capture_freeform(self, parser):
        result = parser.parse(SELECTION_REAL_CAPTURE)
        assert result.items[4].is_freeform is True
        assert result.items[4].label == "Type something."

    def test_real_capture_question(self, parser):
        result = parser.parse(SELECTION_REAL_CAPTURE)
        assert "tmux" in result.question

    def test_permission_dialog_no_footer(self, parser):
        """Permission dialog with question header detected."""
        result = parser.parse(SELECTION_PERMISSION_NO_FOOTER)
        assert result.state == UIState.SELECTION
        assert len(result.items) == 3
        assert result.items[0].label == "Allow once"
        assert "execute" in result.question

    def test_permission_prompt_with_pane_padding(self, parser):
        """Permission prompt with trailing blank lines (tmux padding)."""
        result = parser.parse(SELECTION_PERMISSION_PADDED)
        assert result.state == UIState.SELECTION
        assert len(result.items) == 3
        assert result.items[0].label == "Yes"
        assert result.items[2].label == "No"
        assert result.selected_index == 0

    def test_arrow_navigable_with_marker(self, parser):
        """Selection with ❯ marker → arrow_navigable=True."""
        result = parser.parse(SELECTION_BASIC)
        assert result.state == UIState.SELECTION
        assert result.arrow_navigable is True

    def test_arrow_navigable_no_marker_with_footer(self, parser):
        """Selection without marker but with footer → not navigable."""
        result = parser.parse(SELECTION_REAL_CAPTURE)
        assert result.state == UIState.SELECTION
        assert result.arrow_navigable is False

    def test_codex_number_input_selection(self, parser):
        """Codex number-input selection (no marker, colon question)."""
        result = parser.parse(SELECTION_CODEX_NUMBER_INPUT)
        assert result.state == UIState.SELECTION
        assert result.arrow_navigable is False
        assert len(result.items) == 5
        assert result.items[0].label == "Build a quick feature in this repo"
        assert result.items[4].label == "Explain one module in depth"

    def test_scrolled_away_not_selection(self, parser):
        """Old selection scrolled above bottom 5 → PROMPT."""
        result = parser.parse(SELECTION_SCROLLED_AWAY)
        assert result.state == UIState.PROMPT

    def test_numbered_list_no_signal(self, parser):
        """Numbered list without question or footer → PROMPT."""
        result = parser.parse(NUMBERED_LIST_NO_SIGNAL)
        assert result.state == UIState.PROMPT


class TestWorkingState:
    def test_spinner_unicode_ellipsis(self, parser):
        result = parser.parse(WORKING_SPINNER)
        assert result.state == UIState.WORKING

    def test_spinner_colloquial_apostrophe(self, parser):
        result = parser.parse(WORKING_SPINNER_COLLOQUIAL)
        assert result.state == UIState.WORKING

    def test_spinner_long_text(self, parser):
        result = parser.parse(WORKING_SPINNER_LONG_TEXT)
        assert result.state == UIState.WORKING

    def test_spinner_tool_use(self, parser):
        result = parser.parse(WORKING_SPINNER_TOOL_USE)
        assert result.state == UIState.WORKING

    def test_spinner_compact(self, parser):
        result = parser.parse(WORKING_SPINNER_COMPACT)
        assert result.state == UIState.WORKING

    def test_survey_auto_dismiss(self, parser):
        result = parser.parse(WORKING_SURVEY)
        assert result.state == UIState.WORKING
        assert result.auto_response == "0"


class TestPromptState:
    def test_basic_prompt(self, parser):
        result = parser.parse(PROMPT_BASIC)
        assert result.state == UIState.PROMPT

    def test_empty_is_prompt(self, parser):
        """Empty input falls through to prompt (default)."""
        result = parser.parse(PROMPT_EMPTY)
        assert result.state == UIState.PROMPT

    def test_plain_text_is_prompt(self, parser):
        """Plain text without spinner falls through to prompt."""
        result = parser.parse(PROMPT_PLAIN_TEXT)
        assert result.state == UIState.PROMPT


class TestEdgeCases:
    def test_single_item_not_selection(self, parser):
        """A single numbered item with footer still needs 2+ items."""
        raw = f"  1. Only one option\n{FOOTER}\n"
        result = parser.parse(raw)
        # Falls through to prompt (no spinner, no valid selection)
        assert result.state == UIState.PROMPT

    def test_marker_on_last_item(self, parser):
        raw = f"""\
  Pick one:
    1. Apple
    2. Banana
  ❯ 3. Cherry
{FOOTER}
"""
        result = parser.parse(raw)
        assert result.state == UIState.SELECTION
        assert result.selected_index == 2
        assert result.items[2].label == "Cherry"

    def test_detection_priority_working_over_selection(self, parser):
        """Spinner line takes priority even if footer is present."""
        raw = f"""\
  ✻ Thinking…
  1. Option A
  2. Option B
{FOOTER}
"""
        result = parser.parse(raw)
        assert result.state == UIState.WORKING


class TestBottomUpScanning:
    """Bottom-up scanning finds the current selection near bottom
    and ignores stale selections above."""

    def test_hrule_between_items(self, parser):
        """Items 1-6 with hrule between 4 and 5, all detected."""
        raw = """\
  What would you like to learn about tmux?
  1. Basics & getting started
  2. Windows, panes & navigation
  3. Config & keybindings
  4. Scripting & automation
  5. Type something.
────────────────────────────────────────────────────
  6. Chat about this

Enter to select · ↑/↓ to navigate · Esc to cancel"""
        result = parser.parse(raw)
        assert result.state == UIState.SELECTION
        assert len(result.items) == 6
        assert result.items[0].label == "Basics & getting started"
        assert result.items[5].label == "Chat about this"

    def test_stale_selection_above_current(self, parser):
        """Old selection (1-3) far above, current (1-2) near
        bottom. Bottom-up finds current only."""
        raw = """\
  Allow Claude to execute Bash(rm -rf /tmp/old)?
  ❯ 1. Allow once
    2. Allow always
    3. Deny

  Esc to cancel · Tab to amend · ctrl+e to explain

  ⏺ Updated file src/main.py
  Some working output here
  More working output

  Allow Claude to execute Bash(ls -la)?
  ❯ 1. Yes
    2. No

  Esc to cancel · Tab to amend · ctrl+e to explain
"""
        result = parser.parse(raw)
        assert result.state == UIState.SELECTION
        assert len(result.items) == 2
        assert result.items[0].label == "Yes"
        assert result.items[1].label == "No"

    def test_stale_selection_then_prompt(self, parser):
        """Old selection above, prompt box at bottom → PROMPT."""
        raw = """\
  Allow Claude to execute Bash(rm -rf /tmp/old)?
  ❯ 1. Allow once
    2. Allow always
    3. Deny

  Esc to cancel · Tab to amend · ctrl+e to explain

  ⏺ Updated file src/main.py
  Some working output here
  More working output
─────────────────────────────
›
─────────────────────────────
"""
        result = parser.parse(raw)
        assert result.state == UIState.PROMPT
