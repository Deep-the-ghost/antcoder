#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
python3 -m antcoder.cli "$@"
