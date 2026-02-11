# agentdeck

Your coding agents don't stop working just because you left your desk.
This is a lightweight server that lets you monitor and interact with
AI coding agents (Claude Code, Codex, etc.) running on your dev machine —
from your phone, tablet, or that questionable airport WiFi.

Because sometimes you need to approve a file edit while waiting for
your coffee.

## Quick start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/)
and at least one coding agent:
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview)
- [Codex](https://github.com/openai/codex)

```bash
# 1. install tmux
# macOS
brew install tmux
# (Debian/Ubuntu)
sudo apt install -y tmux

# 2. install agentdeck and start server
uv sync
uv run uvicorn agentdeck.main:app --host 0.0.0.0 --port 8000
```

Point your browser or your mobile phone to `http://<local_ip>:8000`, tap **New Session**, pick a working
directory, and start talking to your agent.

<p>
  <img src="docs/Screenshot_prompt.png" width="280" alt="Prompt view">&nbsp;&nbsp;
  <img src="docs/Screenshot_choice.png" width="280" alt="Selection view">
</p>

## How it works
 

The server wraps each agent in a tmux session, polls the terminal for
output, detects UI states (prompts, selection menus, spinners), and
renders a mobile-friendly interface with tap-friendly controls.

## Features

- **Mobile-first UI** — fat-finger-friendly buttons, works with
  software keyboards, no modifier keys needed
- **Multiple sessions** — run several agents in parallel, switch
  between them
- **Live output** — terminal content streams to your browser via
  HTMX polling
- **Smart controls** — detects numbered selection menus and renders
  them as tappable buttons
- **Readable tables** — box-drawing tables from terminal output are
  converted to HTML tables that reflow on small screens
- **Persistent history** — scrollback is saved to SQLite so you can
  review what happened while you were away

## Security (or lack thereof)

This app has **zero built-in authentication**. By design. It's meant
to run on `localhost` or behind a reverse proxy that handles auth.

The recommended setup is a
[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
with Zero Trust access policies. You get HTTPS, authentication, and
DDoS protection without adding a single line of auth code. Your
server never exposes a port to the internet.

```mermaid
flowchart LR
    Phone["Your Phone<br/>(Browser)"]
    CF["Cloudflare Tunnel<br/>Zero Trust<br/>(auth + HTTPS)"]
    AD["agentdeck :8000"]
    TM["tmux sessions<br/>agent-claude<br/>agent-codex"]

    Phone -- HTTPS --> CF -- HTTP --> AD --> TM
```

## Tech stack

FastAPI, HTMX, Alpine.js, DaisyUI, tmux, SQLite. No Node.js build
step. Just Python and tmux.

## Development

```bash
uv sync                    # install dependencies
uv run pytest -v           # run tests
uv run ruff check . --fix  # lint
uv run ty check            # type check
```

### CSS build

The frontend uses Tailwind CSS + DaisyUI. Styles are compiled with
[`tailwindcss-extra`](https://github.com/nickolaj-jepsen/tailwindcss-extra),
a drop-in `tailwindcss` CLI that bundles first-party plugins like
DaisyUI.

See [GitHub](https://github.com/nickolaj-jepsen/tailwindcss-extra) for how to install

```bash
# for macOS
brew install nickolaj-jepsen/tap/tailwindcss-extra

# rebuild CSS whenever you change templates or input.css
scripts/build-css.sh
```

You do **not** need to run this for backend-only changes — the
compiled `tailwind.css` is checked into the repo.

## Contributing

Contributions are welcome! 

- [`CLAUDE.md`](CLAUDE.md) — coding conventions and quality gates
- [`docs/architecture.md`](docs/architecture.md) — system design,
  component overview, and data flow

Licensed under Apache 2.0.
