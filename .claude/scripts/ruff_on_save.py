#!/usr/bin/env python3
"""PostToolUse hook: auto-format Python files after edit/write.

Runs `ruff format` on any .py file that was edited or created by Claude,
preventing style drift and reducing pre-commit formatting overhead.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

LOG_FILE = os.path.expanduser("~/tmp/pyhooks.log")


def log(payload: dict, decision: str) -> None:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    entry = {
        "timestamp": timestamp,
        "hook": "ruff_on_save",
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
    file_path = tool_input.get("file_path", "")

    if not file_path.endswith(".py"):
        log(payload, "skip")
        return

    ruff = shutil.which("ruff")
    if ruff:
        cmd = [ruff, "format", file_path]
    else:
        cmd = ["uv", "run", "ruff", "format", file_path]

    result = subprocess.run(cmd, capture_output=True, timeout=10)
    decision = "formatted" if result.returncode == 0 else "error"
    log(payload, decision)


if __name__ == "__main__":
    main()
