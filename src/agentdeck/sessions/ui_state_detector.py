"""Parse Claude Code UI state from raw tmux output."""

import re

from agentdeck.sessions.models import (
    ParsedOutput,
    SelectionItem,
    UIState,
)

# Matches numbered list items, with optional › or ❯ marker.
_ITEM_RE = re.compile(r"^(?P<prefix>\s*[›❯]?\s*)(?P<num>\d+)\.\s+(?P<label>.+)$")

# Horizontal rule made of ─ (box-drawing char)
_HRULE_RE = re.compile(r"^[\s]*[─╌╍┄┅┈┉━]{3,}[\s]*$")

# Footer line that confirms this is a selection prompt
# Matches: "Enter to select · ↑/↓ to navigate · Esc to cancel"
# Also matches: "Enter to confirm · Esc to cancel" (trust prompt)
# Also matches: "Esc to cancel · Tab to amend" (permission prompt)
# Also matches: "Press enter to continue" (Codex selection)
_FOOTER_RE = re.compile(
    r"(Enter to (select|confirm)|Esc to cancel)"
    r".*(Esc to cancel|Tab to amend|↑/↓)"
    r"|Press enter to continue",
    re.IGNORECASE,
)

# Freeform indicator — Claude uses "Type something" for free input
_FREEFORM_HINT = "type something"

# Known spinner characters used by Claude Code status lines.
# Captured empirically — see scripts/capture_spinners.py
_SPINNER_CHARS = "·⏺✢✳✶✻✽"

# Status line: spinner char + space + text containing …
# Examples: "✳ Moonwalking…", "⏺ Reading 1 file…",
#           "+ Renaming Foo across codebase…"
_SPINNER_RE = re.compile(rf"^\s*[{_SPINNER_CHARS}]\s+.*\u2026")

# Codex working line: "• Working (0s • esc to interrupt)"
_CODEX_WORKING_RE = re.compile(r"^\s*•\s+.*\(\d+s\s*•\s*esc to interrupt\)")

# Quality survey: "1: Bad  2: Fine  3: Good  0: Dismiss"
_SURVEY_RE = re.compile(r"\d:\s*Good\s+0:\s*Dismiss", re.IGNORECASE)

# How many lines from the bottom to search for spinner/perf.
_BOTTOM_LINES = 5

# Agent chrome lines found at the bottom of the pane.
# Matched lines are stripped alongside blank lines so
# proximity checks see actual content, not agent chrome.
#   "? for shortcuts"
#   "82% context left"
#   "shift+tab to cycle"
#   "› some placeholder"  (input prompt cursor)
_CHROME_RE = re.compile(
    r"\?\s+for\s+shortcuts"
    r"|\d+%\s+context left"
    r"|shift\+tab to cycle"
    r"|^\s*[›❯]\s+\S",
    re.IGNORECASE,
)


class UIStateDetector:
    """Detect Claude Code UI state from captured pane text."""

    def parse(self, raw: str) -> ParsedOutput:
        """Parse raw tmux output into a structured state.

        Detection priority:
          1. Working — spinner line near bottom
          2. Selection — numbered list + navigation footer
          3. Prompt — default fallback
        """
        lines = raw.split("\n")

        # Strip trailing blank lines and agent status-bar
        # chrome so position checks use actual content bottom.
        while lines and (not lines[-1].strip() or _CHROME_RE.search(lines[-1])):
            lines.pop()

        working = self._try_working(lines)
        if working is not None:
            return working

        selection = self._try_selection(lines)
        if selection is not None:
            return selection

        return ParsedOutput(state=UIState.PROMPT)

    def _try_working(self, lines: list[str]) -> ParsedOutput | None:
        """Detect working state from spinner near bottom.

        Also detects performance evaluation prompt and sets
        auto_response to respond automatically.
        """
        tail = lines[-_BOTTOM_LINES:]

        # Check for quality survey — auto-dismiss
        for line in tail:
            if _SURVEY_RE.search(line):
                return ParsedOutput(
                    state=UIState.WORKING,
                    auto_response="0",
                )

        # Check for spinner line (Claude or Codex)
        for line in tail:
            if _SPINNER_RE.match(line):
                return ParsedOutput(state=UIState.WORKING)
            if _CODEX_WORKING_RE.match(line):
                return ParsedOutput(state=UIState.WORKING)

        return None

    def _try_selection(self, lines: list[str]) -> ParsedOutput | None:  # noqa: C901
        """Try to parse a numbered selection list.

        Scans bottom-up so stale selections above the current
        one are never reached. Requires:
          - 2+ consecutive items numbered 1..N
          - Bottom-most item within 5 lines of content end
          - Either the navigation footer OR a question header
        """
        n = len(lines)
        if n == 0:
            return None

        # --- Phase 1: bottom-up scan for numbered items ---
        # Map: item number → (line index, label, has_marker)
        found: dict[int, tuple[int, str, bool]] = {}
        bottom_item_idx: int | None = None
        i = n - 1

        # Skip footer lines at the very bottom
        while i >= 0:
            line = lines[i]
            if not line.strip() or _FOOTER_RE.search(line):
                i -= 1
                continue
            break

        # Walk upward looking for numbered items
        prev_item_line: int | None = None
        while i >= 0:
            line = lines[i]
            m = _ITEM_RE.match(line)
            if m:
                num = int(m.group("num"))
                label = m.group("label").strip()
                prefix = m.group("prefix")
                marker = "›" in prefix or "❯" in prefix

                if bottom_item_idx is None:
                    # First item from bottom — must be near end
                    if i < n - 5:
                        return None
                    bottom_item_idx = i

                # Gap check: each item must be within 3 lines
                # of the previous (lower) item
                if prev_item_line is not None:
                    gap = prev_item_line - i
                    if gap > 3:
                        break

                found[num] = (i, label, marker)
                prev_item_line = i

                # Stop once we find item 1
                if num == 1:
                    break
            elif _FOOTER_RE.search(line):
                pass  # skip inline footer
            elif not line.strip():
                pass  # skip blank lines
            elif _HRULE_RE.match(line):
                pass  # skip hrules between items
            elif line.startswith("    "):
                pass  # skip description lines (collected later)
            else:
                # Non-item, non-skip line — gap tolerance
                # still applies via prev_item_line check above
                pass

            i -= 1

        # Must have found item 1 and at least 2 items
        if 1 not in found or len(found) < 2:
            return None

        # Build consecutive item list 1..max
        max_num = max(found)
        items: list[SelectionItem] = []
        item_lines: list[int] = []
        selected_index = 0
        has_marker = False

        for num in range(1, max_num + 1):
            if num not in found:
                return None  # gap in numbering
            idx, label, marker = found[num]
            items.append(SelectionItem(number=num, label=label))
            item_lines.append(idx)
            if marker:
                selected_index = len(items) - 1
                has_marker = True

        # --- Phase 2: forward pass for descriptions ---
        for pos, item in enumerate(items):
            start = item_lines[pos] + 1
            end = item_lines[pos + 1] if pos + 1 < len(items) else n
            for j in range(start, end):
                line = lines[j]
                if _ITEM_RE.match(line) or _FOOTER_RE.search(line):
                    break
                if _HRULE_RE.match(line) or not line.strip():
                    continue
                if line.startswith("    "):
                    desc = line.strip()
                    if item.description:
                        item.description += " " + desc
                    else:
                        item.description = desc

        # --- Phase 3: validation gates ---
        has_footer = any(_FOOTER_RE.search(ln) for ln in lines)

        has_question = False
        first_idx = item_lines[0]
        for k in range(first_idx - 1, max(first_idx - 3, -1), -1):
            line = lines[k].strip()
            if not line:
                continue
            if line.endswith(("?", ":")):
                has_question = True
                break

        if not has_footer and not has_question:
            return None

        if not has_marker:
            selected_index = 0

        for item in items:
            if _FREEFORM_HINT in item.label.lower():
                item.is_freeform = True

        # Extract question text above the first item
        question_lines: list[str] = []
        first_item_idx = item_lines[0]
        for k in range(first_item_idx - 1, -1, -1):
            line = lines[k].strip()
            if not line or _HRULE_RE.match(lines[k]):
                break
            question_lines.insert(0, line)

        return ParsedOutput(
            state=UIState.SELECTION,
            items=items,
            selected_index=selected_index,
            arrow_navigable=has_marker,
            question=" ".join(question_lines),
        )
