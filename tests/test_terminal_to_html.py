"""Tests for _terminal_to_html box-drawing conversion."""

from agentdeck.api.sessions import _terminal_to_html

# ── Multi-column table ──────────────────────────────────────


TABLE_INPUT = """\
┌─────┬──────────┬─────────┐
│  #  │   Test   │ Verdict │
├─────┼──────────┼─────────┤
│ 1   │ foo_test │ Keep    │
│ 2   │ bar_test │ Remove  │
└─────┴──────────┴─────────┘"""


def test_table_produces_html_table():
    result = str(_terminal_to_html(TABLE_INPUT))
    assert "<table" in result
    assert "terminal-table" in result


def test_table_has_header_row():
    result = str(_terminal_to_html(TABLE_INPUT))
    assert "<thead>" in result
    assert "<th>#</th>" in result
    assert "<th>Test</th>" in result
    assert "<th>Verdict</th>" in result


def test_table_has_body_rows():
    result = str(_terminal_to_html(TABLE_INPUT))
    assert "<tbody>" in result
    assert "foo_<wbr>test" in result
    assert "bar_<wbr>test" in result
    assert "<td>Keep</td>" in result
    assert "<td>Remove</td>" in result


def test_table_cells_have_wbr_after_underscores():
    """Long snake_case identifiers get <wbr> break hints."""
    inp = (
        "┌───┬──────────────────────┐\n"
        "│ # │ Name                 │\n"
        "├───┼──────────────────────┤\n"
        "│ 1 │ long_snake_case_name │\n"
        "└───┴──────────────────────┘"
    )
    result = str(_terminal_to_html(inp))
    assert "long_<wbr>snake_<wbr>case_<wbr>name" in result


def test_table_strips_box_drawing():
    """No box-drawing characters should remain."""
    result = str(_terminal_to_html(TABLE_INPUT))
    for ch in "┌┬┐├┼┤└┴┘─":
        assert ch not in result


# ── Single-column panel (rounded corners) ───────────────────


PANEL_INPUT = """\
╭────────────────────────╮
│ Plan to implement      │
│ step 1: read code      │
│ step 2: write tests    │
╰────────────────────────╯"""


def test_panel_produces_div():
    result = str(_terminal_to_html(PANEL_INPUT))
    assert '<div class="terminal-panel">' in result


def test_panel_contains_content():
    result = str(_terminal_to_html(PANEL_INPUT))
    assert "Plan to implement" in result
    assert "step 1: read code" in result
    assert "step 2: write tests" in result


def test_panel_strips_box_drawing():
    result = str(_terminal_to_html(PANEL_INPUT))
    for ch in "╭╮╰╯│─":
        assert ch not in result


# ── Panel with square corners ────────────────────────────────


SQUARE_PANEL = """\
┌──────────────────┐
│ Warning message  │
└──────────────────┘"""


def test_square_panel_produces_div():
    """Square-corner panels (no ┬) are panels, not tables."""
    result = str(_terminal_to_html(SQUARE_PANEL))
    assert '<div class="terminal-panel">' in result
    assert "Warning message" in result
    assert "<table" not in result


# ── Table nested inside panel ────────────────────────────────


PANEL_WITH_TABLE = """\
╭──────────────────────────────────────╮
│ Template changes needed              │
│ ┌──────────┬──────────┬──────────┐   │
│ │ What     │ v4       │ v5       │   │
│ ├──────────┼──────────┼──────────┤   │
│ │ Form     │ form-ctl │ fieldset │   │
│ │ Input    │ bordered │ remove   │   │
│ └──────────┴──────────┴──────────┘   │
╰──────────────────────────────────────╯"""


def test_panel_with_table_renders_both():
    result = str(_terminal_to_html(PANEL_WITH_TABLE))
    assert '<div class="terminal-panel">' in result
    assert '<table class="terminal-table">' in result


def test_panel_with_table_has_label():
    result = str(_terminal_to_html(PANEL_WITH_TABLE))
    assert "Template changes needed" in result


def test_panel_with_table_has_cells():
    result = str(_terminal_to_html(PANEL_WITH_TABLE))
    assert "<th>What</th>" in result
    assert "<td>fieldset</td>" in result


def test_panel_with_table_strips_box_drawing():
    result = str(_terminal_to_html(PANEL_WITH_TABLE))
    for ch in "╭╮╰╯┌┬┐├┼┤└┴┘─│":
        assert ch not in result


# ── Mixed content ────────────────────────────────────────────


MIXED = """\
Some plain text above
───────────────────
╭─────────────────╮
│ A panel block   │
╰─────────────────╯
More text below
┌───┬───┐
│ A │ B │
├───┼───┤
│ 1 │ 2 │
└───┴───┘
Final line"""


def test_mixed_preserves_plain_text():
    result = str(_terminal_to_html(MIXED))
    assert "Some plain text above" in result
    assert "More text below" in result
    assert "Final line" in result


def test_mixed_converts_hrule():
    result = str(_terminal_to_html(MIXED))
    assert '<hr class="terminal-hr">' in result


def test_dashed_hrule_variants():
    """All box-drawing dash chars become <hr>."""
    for ch in "─╌╍┄┅┈┉━":
        line = ch * 20
        result = str(_terminal_to_html(line))
        assert '<hr class="terminal-hr">' in result, (
            f"U+{ord(ch):04X} ({ch}) not recognized as hrule"
        )


def test_mixed_converts_panel_and_table():
    result = str(_terminal_to_html(MIXED))
    assert '<div class="terminal-panel">' in result
    assert '<table class="terminal-table">' in result


# ── Plain text passthrough ───────────────────────────────────


# ── Headless panel (no top border) ───────────────────────────


HEADLESS_PANEL = """\
│ Verification          │
│                       │
│ 1. Check SVG icons    │
│ 2. Test popover       │
╰───────────────────────╯"""


def test_headless_panel_produces_div():
    """Panel without top border is still rendered as a panel."""
    result = str(_terminal_to_html(HEADLESS_PANEL))
    assert '<div class="terminal-panel">' in result


def test_headless_panel_contains_content():
    result = str(_terminal_to_html(HEADLESS_PANEL))
    assert "Verification" in result
    assert "Check SVG icons" in result
    assert "Test popover" in result


def test_headless_panel_strips_box_drawing():
    result = str(_terminal_to_html(HEADLESS_PANEL))
    for ch in "╰╯│─":
        assert ch not in result


# ── Plain text passthrough ───────────────────────────────────


def test_plain_text_is_escaped():
    result = str(_terminal_to_html("<script>alert(1)</script>"))
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_plain_text_no_conversion():
    result = str(_terminal_to_html("just normal text\nline two"))
    assert result == "just normal text\nline two"
