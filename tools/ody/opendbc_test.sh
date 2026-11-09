#!/usr/bin/env bash
# No arguments: test the exact app-pinned opendbc checkout. Full suite includes MISRA/tool dependencies.
# --focused: Honda controller/HUD/safety tests using the built app environment (macOS or Linux).
# [branch] [dir]: full suite in a separate pselden/opendbc checkout, default dir ~/odypilot-opendbc.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
if [ "${1:-}" = --focused ]; then
  cd "$ODY_ROOT"
  ody_activate "$ODY_ROOT"
  exec python -m pytest -q opendbc_repo/opendbc/car/honda/tests opendbc_repo/opendbc/safety/tests/test_honda.py
fi
if [ $# -gt 0 ]; then
  DIR=${2:-$HOME/odypilot-opendbc}
  ody_checkout https://github.com/pselden/opendbc.git "$1" "$DIR"
else
  DIR="$ODY_ROOT/opendbc_repo"
  expected=$(git -C "$ODY_ROOT" rev-parse HEAD:opendbc_repo)
  actual=$(git -C "$DIR" rev-parse HEAD)
  [ "$actual" = "$expected" ] || { echo "opendbc HEAD differs from the app pin." >&2; exit 1; }
fi
cd "$DIR"
source ./setup.sh
# setup.sh/test.sh source each other; install the shim where either environment activation can find it.
python - "$ODY_ROOT/tools/ody/opendbc_shim" <<'PY'
from pathlib import Path
import sys
import sysconfig
Path(sysconfig.get_path('purelib'), 'op_shim.pth').write_text(sys.argv[1] + '\n')
PY
git log --oneline -1
if ./test.sh > "$DIR/test.log" 2>&1; then
  tail -12 "$DIR/test.log"
else
  tail -40 "$DIR/test.log"
  exit 1
fi
