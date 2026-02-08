#!/usr/bin/env python3
"""Capture tmux pane output for agent UI state analysis.

General-purpose debug tool — works with any tmux session.
Captures the visible pane content N times at a specified
interval and writes each capture to a file with timestamps.

Usage:
    uv run scripts/capture_pane.py [--ansi] <session> <n> <delay-ms> <output>

Arguments:
    --ansi    — include ANSI escape sequences (color codes)
    session   — tmux session name
    n         — number of captures
    delay-ms  — milliseconds between captures
    output    — output file path
"""

from __future__ import annotations

import sys
import time

import libtmux


def _get_pane(session_name: str) -> libtmux.Pane:
    """Find the active pane for a tmux session."""
    server = libtmux.Server()
    session = server.sessions.get(session_name=session_name)
    if session is None:
        msg = f"Session not found: {session_name}"
        raise SystemExit(msg)
    window = session.active_window
    if window is None:
        raise SystemExit("No active window")
    pane = window.active_pane
    if pane is None:
        raise SystemExit("No active pane")
    return pane


def capture(
    session_name: str,
    n: int,
    delay_ms: int,
    output_path: str,
    *,
    ansi: bool = False,
) -> None:
    pane = _get_pane(session_name)
    delay_s = delay_ms / 1000.0

    with open(output_path, "w") as f:
        for i in range(n):
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            content = pane.capture_pane(
                escape_sequences=ansi,
            )
            text = "\n".join(content) if isinstance(content, list) else str(content)

            f.write(f"--- capture {i + 1}/{n} at {ts} ---\n")
            f.write(text)
            f.write("\n\n")
            f.flush()

            if i < n - 1:
                time.sleep(delay_s)

    print(f"Wrote {n} captures to {output_path}")


def main() -> None:
    args = sys.argv[1:]
    ansi = False
    if args and args[0] == "--ansi":
        ansi = True
        args = args[1:]

    if len(args) != 4:
        print(
            "Usage: capture_pane.py [--ansi] <session> <n> <delay-ms> <output>",
            file=sys.stderr,
        )
        sys.exit(1)

    session_name = args[0]
    n = int(args[1])
    delay_ms = int(args[2])
    output_path = args[3]

    capture(
        session_name,
        n,
        delay_ms,
        output_path,
        ansi=ansi,
    )


if __name__ == "__main__":
    main()
