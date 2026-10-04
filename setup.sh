#!/usr/bin/env bash
# One-command setup on Linux/macOS. Usage, in the project folder:
#   ./setup.sh                                    # full live setup (GPU or CPU PyTorch picked automatically)
#   ./setup.sh --keys sigil-proving-keys.zip      # also install the shipped proving keys
#   ./setup.sh --minimal                          # demo UI with saved results only (installs nothing)
set -euo pipefail
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python || true)
[ -n "$PY" ] || { echo "Python 3.10+ is required" >&2; exit 1; }
exec "$PY" scripts/setup_env.py "$@"
