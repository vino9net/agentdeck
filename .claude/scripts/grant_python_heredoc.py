#!/usr/bin/env python3
"""PermissionRequest hook: auto-grant permission for python heredoc execution.

Claude Code invokes this script when a permission dialog appears for Bash
tool calls. It receives a JSON object on stdin describing the tool call and
can print a JSON decision to stdout:

    {"hookSpecificOutput": {"hookEventName": "PermissionRequest",
     "decision": {"behavior": "allow"}}}   — skip the permission prompt
    {"hookSpecificOutput": {"hookEventName": "PermissionRequest",
     "decision": {"behavior": "deny", "message": "..."}}}  — block the call
    (no output / exit 0)  — fall through to normal permission flow

This hook matches Bash commands that use python/python3 with a heredoc
(<<<), which Claude commonly uses to run inline Python snippets.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

HEREDOC_PATTERN = re.compile(r"^(uv run )?(python3?)\s+<<<")
LOG_FILE = os.path.expanduser("~/tmp/pyhooks.log")


def log(payload: dict, decision: str) -> None:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    entry = {
        "timestamp": timestamp,
        "hook": "grant_python_heredoc",
        "request": payload,
        "decision": decision,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    tool_input = payload.get("tool_input", {})
    command = tool_input.get("command", "")

    if HEREDOC_PATTERN.match(command.strip()):
        decision = "allow"
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PermissionRequest",
                    "decision": {"behavior": "allow"},
                }
            },
            sys.stdout,
        )
    else:
        decision = "passthrough"

    log(payload, decision)


if __name__ == "__main__":
    main()
