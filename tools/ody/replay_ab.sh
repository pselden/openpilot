#!/usr/bin/env bash
# Compare Honda process replay with our stable release, without replacing an existing checkout or ref file.
# usage: replay_ab.sh [base ref] [base dir]   defaults: sp-ody ~/odypilot-replay-base
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
HERE=$ODY_ROOT
APP_VENV=${ODY_VENV:-${VIRTUAL_ENV:-$HERE/.venv}}
BASE_DIR=${2:-$HOME/odypilot-replay-base}
ody_checkout https://github.com/pselden/openpilot.git "${1:-sp-ody}" "$BASE_DIR"
cd "$BASE_DIR"
git submodule sync --recursive
git submodule update --init --recursive --jobs "$(ody_jobs)"
git lfs pull
uv sync --frozen --all-extras
ody_activate "$BASE_DIR" "$BASE_DIR/.venv"
BASE=$(git rev-parse HEAD)
if ! scons -j"$(ody_jobs)" > "$BASE_DIR/scons.log" 2>&1; then
  tail -40 "$BASE_DIR/scons.log"
  exit 1
fi
cd openpilot/selfdrive/test/process_replay
# Baseline failures require review too; do not silently accept invalid reference generation.
python test_processes.py -j "$(ody_jobs)" --whitelist-cars HONDA HONDA2 > "$BASE_DIR/replay.log" 2>&1 || {
  tail -40 "$BASE_DIR/replay.log"; exit 1;
}
PR="$HERE/openpilot/selfdrive/test/process_replay"
mkdir -p "$PR/fakedata"
cp fakedata/*_"$BASE".zst "$PR/fakedata/"
REF="$PR/ref_commit"
BACKUP=$(mktemp)
HAD_REF=0
if [ -f "$REF" ]; then cp "$REF" "$BACKUP"; HAD_REF=1; fi
restore_ref() {
  if [ "$HAD_REF" = 1 ]; then cp "$BACKUP" "$REF"; else rm -f "$REF"; fi
  rm -f "$BACKUP"
}
trap restore_ref EXIT
printf '%s\n' "$BASE" > "$REF"
deactivate
ody_activate "$HERE" "$APP_VENV"
cd "$PR"
python test_processes.py -j "$(ody_jobs)" --whitelist-cars HONDA HONDA2
