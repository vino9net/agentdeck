# agentdeck

Server for remote access to coding agents on local machine

## Primary Use Case

The primary way users interact with this app is **from a mobile phone or tablet**.
Every UI decision must account for this:

- **Mobile-first layout** — design for small screens first, scale up for desktop
- **Touch keyboards** — users type on software keyboards with limited modifier keys (no easy Ctrl/Alt), autocorrect, and small key targets. Minimize the need for special characters, provide tap-based shortcuts, and never require key combos that aren't available on mobile
- **Fat-finger friendly** — generous tap targets (min 44×44 px), adequate spacing between interactive elements
- **Viewport-aware** — the software keyboard consumes ~half the screen; critical content and input areas must remain visible when the keyboard is open

## Development

- Package manager: `uv` (never use pip, setup.py, or requirements.txt)
- Python: 3.13+
- Layout: `src/agentdeck/`

## Code Style

- **Line length: 88 characters max.** Write concise lines from the start. Do not exceed 88 chars and rely on the formatter.
- Modern type annotations: `str | None`, `list[int]`, not `Optional[str]`, `List[int]`
- Google-style docstrings
- Imports: stdlib first, third-party second, local last — alphabetically sorted

## Auto-formatting

A PostToolUse hook automatically runs `ruff format` on any `.py` file after edits.
You do not need to manually format files during development.

## UI Design

- See **Primary Use Case** above — mobile-first is the top priority
- Readable text sizes, high-contrast controls, and layouts that reflow cleanly on small screens

## Playwright (browser testing)

- Primary test device: **Pixel 9** — viewport **443×908** CSS pixels
- Always resize to mobile viewport before testing UI:
  `browser_resize(width=443, height=908)`
- The viewport size is also shown in the Sessions dropdown (bottom-right)

## Testing

- Write tests that verify **behavior**, not implementation details
- Don't test getters, setters, constants, or trivial wiring
- Each test should assert something that could actually break
- Use realistic fixtures (e.g. actual tmux captures, not synthetic data)
- If a test would still pass after deleting the code under test, it's useless

## Quality Gates (before commit)

Run these in order — only commit if ALL pass:

```
1. ruff format .
2. ruff check . --fix
3. ruff check .
4. ty check
5. pytest -v --timeout=180
```
