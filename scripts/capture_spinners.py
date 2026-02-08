#!/usr/bin/env python3
"""Capture spinner characters from a live agent session.

Launches a tmux session, sends a prompt, then rapidly captures
output to collect all spinner characters used in status lines.

Usage:
    uv run scripts/capture_spinners.py [--prompt TEXT] [--rounds N]

The script looks for lines containing the Unicode ellipsis (…)
near the bottom of the pane and extracts the leading character
(the spinner). Results are printed as a sorted set.
"""

import argparse
import time
import unicodedata

from libtmux import Server

SESSION_NAME = "spinner-capture"
PANE_WIDTH = 200
PANE_HEIGHT = 50
# How many lines from bottom to scan
BOTTOM_LINES = 8
# Capture interval in seconds
CAPTURE_INTERVAL = 0.05
# Seconds to capture per round
CAPTURE_DURATION = 30
# Wait for agent to be ready before sending prompt
STARTUP_WAIT = 10

ELLIPSIS = "\u2026"  # …


def create_session(server: Server, working_dir: str) -> None:
    """Create a tmux session running claude."""
    # Kill stale session if it exists
    for s in server.sessions:
        if s.name == SESSION_NAME:
            s.kill()
            break

    cmd = f"cd {working_dir} && claude"
    session = server.new_session(
        session_name=SESSION_NAME,
        window_command=cmd,
        x=PANE_WIDTH,
        y=PANE_HEIGHT,
    )
    session.set_option("remain-on-exit", "on")


def capture_pane(server: Server) -> list[str]:
    """Capture visible pane content as lines."""
    session = server.sessions.get(session_name=SESSION_NAME)
    assert session is not None
    pane = session.active_pane
    assert pane is not None
    lines: list[str] = pane.capture_pane()
    return lines


def send_keys(
    server: Server,
    text: str,
    *,
    enter: bool = True,
    literal: bool = False,
) -> None:
    session = server.sessions.get(session_name=SESSION_NAME)
    assert session is not None
    pane = session.active_pane
    assert pane is not None
    pane.send_keys(text, enter=enter, literal=literal)


def extract_spinners(lines: list[str]) -> set[str]:
    """Find spinner chars from lines containing …"""
    spinners: set[str] = set()
    # Only check bottom N lines
    tail = lines[-BOTTOM_LINES:]
    for line in tail:
        if ELLIPSIS not in line:
            continue
        stripped = line.lstrip()
        if not stripped:
            continue
        # The spinner is the first character
        ch = stripped[0]
        # Skip if it's a regular letter/digit (probably not a
        # spinner)
        if ch.isascii() and ch.isalnum():
            continue
        spinners.add(ch)
    return spinners


def char_info(ch: str) -> str:
    """Format character with its Unicode name and codepoint."""
    try:
        name = unicodedata.name(ch)
    except ValueError:
        name = "UNKNOWN"
    return f"  {ch}  U+{ord(ch):04X}  {name}"


def run_capture_round(
    server: Server,
    round_num: int,
    prompt: str,
    duration: int = CAPTURE_DURATION,
) -> set[str]:
    """Send a prompt and capture spinners for duration."""
    print(f"\n--- Round {round_num} ---")
    print(f"Sending: {prompt[:80]}...")
    send_keys(server, prompt, enter=True, literal=True)
    # Claude Code needs Enter pressed after literal text
    time.sleep(0.3)
    send_keys(server, "Enter", enter=False)

    all_spinners: set[str] = set()
    ellipsis_lines: set[str] = set()
    captures = 0
    start = time.monotonic()
    dumped_first = False

    while time.monotonic() - start < duration:
        lines = capture_pane(server)

        # Dump first non-empty capture for debugging
        if not dumped_first and any(ln.strip() for ln in lines):
            tail = [ln for ln in lines[-10:] if ln.strip()]
            print(f"  First capture ({len(lines)} lines), tail:")
            for ln in tail[-5:]:
                print(f"    | {ln}")
            dumped_first = True

        # Collect all lines with …
        tail = lines[-BOTTOM_LINES:]
        for line in tail:
            if ELLIPSIS in line:
                ellipsis_lines.add(line.strip())

        found = extract_spinners(lines)
        if found:
            new = found - all_spinners
            if new:
                for ch in new:
                    print(f"  NEW: {char_info(ch)}")
                all_spinners |= found
        captures += 1
        time.sleep(CAPTURE_INTERVAL)

    print(f"  Captures: {captures}, spinners found: {len(all_spinners)}")
    if ellipsis_lines:
        print("  Lines with …:")
        for ln in sorted(ellipsis_lines):
            print(f"    | {ln}")
    return all_spinners


def wait_for_prompt(server: Server, timeout: int = 60) -> bool:
    """Wait until agent shows a prompt (no … in bottom lines)."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        lines = capture_pane(server)
        tail = lines[-BOTTOM_LINES:]
        has_ellipsis = any(ELLIPSIS in line for line in tail)
        if not has_ellipsis:
            # Quick check: non-empty content means it's loaded
            content = "\n".join(lines).strip()
            if content:
                return True
        time.sleep(1)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture spinner characters from agent")
    parser.add_argument(
        "--working-dir",
        default=".",
        help="Working directory for agent (default: .)",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=2,
        help="Number of capture rounds (default: 2)",
    )
    parser.add_argument(
        "--prompt",
        action="append",
        help="Prompt(s) to send. Can specify multiple. Defaults to two built-in prompts.",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=CAPTURE_DURATION,
        help=f"Seconds per round (default: {CAPTURE_DURATION})",
    )
    args = parser.parse_args()

    capture_duration = args.duration

    prompts = args.prompt or [
        "list all files in this directory",
        "explain the project structure briefly",
    ]

    server = Server()

    print(f"Creating session: {SESSION_NAME}")
    create_session(server, args.working_dir)

    print(f"Waiting {STARTUP_WAIT}s for agent startup...")
    time.sleep(STARTUP_WAIT)

    if not wait_for_prompt(server):
        print("WARNING: agent may not be ready, proceeding anyway")

    all_spinners: set[str] = set()
    rounds = min(args.rounds, len(prompts))

    for i in range(rounds):
        spinners = run_capture_round(server, i + 1, prompts[i], capture_duration)
        all_spinners |= spinners

        if i < rounds - 1:
            print("\nWaiting for agent to finish...")
            wait_for_prompt(server, timeout=120)

    print("\n" + "=" * 50)
    print(f"TOTAL UNIQUE SPINNER CHARACTERS: {len(all_spinners)}")
    print("=" * 50)
    for ch in sorted(all_spinners):
        print(char_info(ch))

    # Print as a regex character class
    if all_spinners:
        escaped = "".join(f"\\u{ord(c):04X}" for c in sorted(all_spinners))
        print(f"\nRegex class: [{escaped}]")

    # Cleanup
    print(f"\nKilling session: {SESSION_NAME}")
    for s in server.sessions:
        if s.name == SESSION_NAME:
            s.kill()
            break


if __name__ == "__main__":
    main()
