# Soft Keyboard / Keypad for Mobile

## Problem

Coding agents (and TUI apps in general) rely on real-time keystroke
capture for certain interactions:

- `/` triggers slash command mode; subsequent keys narrow choices
- `Tab` completes or cycles options
- `Up/Down` navigate selections, command history
- `Left/Right` toggle sub-options (model, thinking effort)
- `Escape` cancels, `Ctrl+C` interrupts
- `Enter` confirms

Mobile software keyboards lack arrow keys, Tab, and Escape.
There is no web API to customize the system keyboard layout.

## Web platform limitations

- **`inputmode`** attribute: hints `text`, `numeric`, `tel`, etc.
  None provide arrow keys, Tab, or Escape.
- **`VirtualKeyboard` API**: controls keyboard geometry
  (overlaysContent mode), not key layout.
- **Conclusion**: we must build our own button bar.

## Proposed approach: context-sensitive button bar

A thin button bar that adapts to the current UI state
(driven by the same `parsed.state` that controls the frontend).

### Prompt state (typing text)

System keyboard stays open. Single row above it:

```
[ / ]  [ Up ]  [ Down ]  [ Tab ]  [ Esc ]
```

- `/` sends a literal `/` keystroke (triggers slash mode in agent)
- `Up/Down` for command history recall
- Could also show a local slash-command picker on `/` tap

### Selection state (choosing from list)

System keyboard dismissed. Show a nav pad:

```
        [ Up ]
[ Left ]       [ Right ]    [ Enter ]
        [ Down ]

[ 1 ] [ 2 ] [ 3 ] [ 4 ] [ 5 ]   <- number row
            [ Esc ]
```

- Arrows for navigable selections (`arrow_navigable=True`)
- Number row for direct pick (`arrow_navigable=False`)
- Left/Right for toggling sub-options

### Working state (agent is busy)

Minimal bar:

```
[ Esc ]  [ Ctrl+C ]
```

## Implementation pieces

1. **`POST /api/v1/sessions/{id}/key`** endpoint: sends a single
   key to tmux via `send_keys` with no Enter appended. Lightweight,
   no text buffering.

2. **State-aware button bar component**: Alpine.js component that
   switches layout based on `uiState`. Buttons fire `/key` on tap.

3. **`visualViewport` positioning**: detect system keyboard height
   and position the bar just above it (or above bottom edge when
   keyboard is hidden).

4. **Touch targets**: minimum 44x44px per CLAUDE.md mobile-first
   requirements. Adequate spacing to avoid mis-taps.

## Alternative: gesture layer

Transparent overlay where swipe directions map to arrow keys.
Natural on touch but poor discoverability, conflicts with scrolling.
Could complement the button bar, not replace it.
