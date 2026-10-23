#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
danus_root="${DANUS_ROOT:-/opt/danus}"
if [[ -r "$danus_root/scripts/env.sh" ]]; then
  source "$danus_root/scripts/env.sh"
  python_bin="$danus_root/runtime/venv/bin/python"
else
  python_bin="${PYTHON_BIN:-python3}"
fi
cd -- "$repo_root"
exec "$python_bin" -m danus_rsi "$@"
