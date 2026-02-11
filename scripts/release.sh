#!/usr/bin/env bash
set -euo pipefail

# prepare the directory for release

cd "$(dirname "$0")/.."

cp -r ../my_code_server/* .
rm t
rm scripts/*.py
uv sync
git add -A
