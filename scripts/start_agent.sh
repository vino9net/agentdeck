#!/usr/bin/env bash
# -----------------------------------------------------------
# start_agent.sh — bootstrap script for coding agent sessions
# -----------------------------------------------------------
# Called by ClaudeCodeAgent.launch_command() every time a new
# session is created via the agentdeck UI. The command that
# runs inside the tmux pane is:
#
#   /path/to/start_agent.sh <working_dir> <agent>
#
# WARNING: Renaming, moving, or changing the interface of this
# script will break the ability to launch new sessions.
# If you need to modify it, update the corresponding
# launch_command() in src/agentdeck/agents/claude_code.py.
# -----------------------------------------------------------
#
# What it does:
#   1. cd into the project's working directory
#   2. Activate .venv/bin/activate if a .venv dir exists,
#      so the agent can run python/pytest/etc. directly
#      without prefixing commands with `uv run`
#   3. exec the agent (replaces this shell process)
#
# Usage: start_agent.sh <working_dir> [agent]
#   working_dir  — project directory to cd into
#   agent        — agent command to run (default: claude)

set -euo pipefail

working_dir="${1:?Usage: start_agent.sh <working_dir> [agent]}"
agent="${2:-claude}"

cd "$working_dir"

if [ -d .venv ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

exec "$agent"
