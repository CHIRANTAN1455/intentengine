#!/usr/bin/env bash
# Run hirequity locally with Python 3.10+ and python-jobspy installed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  CREATOR=""
  for c in /opt/homebrew/bin/python3.13 python3.13 python3.12 python3.11 python3.10; do
    if [[ -x "$c" ]] || command -v "$c" >/dev/null 2>&1; then
      CREATOR="$c"
      break
    fi
  done
  if [[ -z "$CREATOR" ]]; then
    echo "Need Python 3.10+. Install via Homebrew: brew install python@3.13"
    exit 1
  fi
  echo "Creating .venv with $CREATOR ..."
  "$CREATOR" -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -q -r requirements.txt
fi

PY="$ROOT/.venv/bin/python"
echo "Using: $PY ($("$PY" --version))"
if ! "$PY" -c "from jobspy import scrape_jobs" 2>/dev/null; then
  echo "Installing python-jobspy ..."
  "$ROOT/.venv/bin/pip" install -q -r requirements.txt
fi
exec "$PY" -m streamlit run main.py "$@"
