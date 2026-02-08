#!/bin/bash
set -euo pipefail
tailwindcss-extra \
    -i src/agentdeck/static/css/input.css \
    -o src/agentdeck/static/css/tailwind.css \
    --minify
