#!/usr/bin/env bash
export PYTHONPATH="/home/deep/antcoder:$PYTHONPATH"
exec python3 -m antcoder.cli "$@"
