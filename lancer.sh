#!/usr/bin/env bash
# Lanceur double-clic InsertYourCoin (PAPER-ONLY) -- macOS / Linux.
cd "$(dirname "$0")" || exit 1
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi
exec "$PY" lancer.py "$@"
