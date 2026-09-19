#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-}:src"
PORT="${WORKBENCH_PORT:-8765}"
python3 -m workbench serve --port "$PORT"
