#!/bin/sh
# Thin entry point: no curl|sh, no implicit root, no environment-file evaluation.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$ROOT/scripts/install.py" "$@"
