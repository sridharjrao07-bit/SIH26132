#!/usr/bin/env bash
# Start the mock API.  Usage:  ./run.sh [--port 8000] [--delay 0.4]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but was not found on PATH." >&2
  echo "Install Python 3, or run the mock on any machine that has it." >&2
  exit 1
fi

exec python3 "$HERE/mock/mock_api.py" "$@"
