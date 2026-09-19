#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-}:src"
echo "== compile =="
python3 -m compileall -q src tests
echo "== tests =="
python3 -m unittest discover -s tests -v
