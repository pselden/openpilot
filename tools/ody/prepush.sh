#!/usr/bin/env bash
# Host validation: --quick runs the portable focused checks. Default also builds/runs models and full app tests.
# --full adds the complete opendbc suite and stable-vs-dev process replay.
# usage: prepush.sh [--quick | --full] [--target REMOTE/BRANCH] [--rlogs DIR]
# Exit 1 = failed check; exit 2 = required drive replay missing. A quick pass is not a release validation.
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
cd "$ODY_ROOT"
ROOT=$PWD
FULL=0; QUICK=0; TARGET=pselden/sp-ody; RLOGS=${RLOGS:-$HOME/Documents/openpilot/rlogs}
while [ $# -gt 0 ]; do
  case "$1" in
    --quick) QUICK=1 ;;
    --full) FULL=1 ;;
    --target|--rlogs)
      [ $# -ge 2 ] || { echo "$1 needs a value" >&2; exit 1; }
      if [ "$1" = --target ]; then TARGET=$2; else RLOGS=$2; fi
      shift ;;
    *) echo "unknown option $1" >&2; exit 1 ;;
  esac
  shift
done
[ "$QUICK$FULL" != 11 ] || { echo '--quick and --full are exclusive' >&2; exit 1; }
ody_activate "$ROOT" || exit 1
JOBS=$(ody_jobs)
CHECKS="$ROOT/tools/ody/checks"
LOG=$(mktemp -d)
FAILS=(); WARNS=(); PENDING=()
step() {
  local name=$1; shift
  if "$@" > "$LOG/$name.log" 2>&1; then printf '  PASS  %s\n' "$name"
  else
    printf '  FAIL  %s (log: %s/%s.log)\n' "$name" "$LOG" "$name"
    tail -15 "$LOG/$name.log"
    FAILS+=("$name")
  fi
}
warn() { printf '  WARN  %s\n' "$*"; WARNS+=("$*"); }
echo "OdyPilot $(git log --oneline -1) | $(uname -s) | logs $LOG"
if [ "$QUICK" = 0 ]; then
  step build scons -j"$JOBS"
  step models python "$CHECKS/model_e2e.py"
  step model_store python "$CHECKS/model_store.py"
  step lfs_host python -I "$CHECKS/lfs_host.py" "$ROOT"
fi
step imports python -I "$CHECKS/importscan.py" "$ROOT"
step params python -I "$CHECKS/paramscan.py" "$ROOT"
step services python "$CHECKS/svcscan.py" "$ROOT"
step lint ruff check openpilot/selfdrive openpilot/sunnypilot openpilot/system openpilot/common tools/ody
if [ "$QUICK" = 1 ]; then
  step app_tests python -m pytest -q \
    openpilot/common/tests/test_forks.py openpilot/common/tests/test_settings_profile.py \
    openpilot/selfdrive/controls/tests/test_accel_boost.py openpilot/selfdrive/controls/tests/test_cruise_accel.py \
    openpilot/selfdrive/controls/tests/test_launch_boost.py openpilot/selfdrive/controls/tests/test_turn_intent.py \
    openpilot/selfdrive/locationd/test/test_torqued_odyssey.py openpilot/selfdrive/selfdrived/tests \
    openpilot/selfdrive/ui/tests/test_experimental_mode.py openpilot/selfdrive/ui/tests/test_settings_groups.py \
    openpilot/selfdrive/ui/tests/test_status_pills.py openpilot/selfdrive/ui/tests/test_fork_switcher.py \
    openpilot/system/updated/tests/test_update_remote.py openpilot/sunnypilot/modeld_v2/tests/test_blendful.py \
    openpilot/sunnypilot/selfdrive/controls/lib/tests/test_accel_boost.py tools/ody/tests
else
  step app_tests bash -c 'cd openpilot && python -m pytest -q -n "$1" --timeout=300 common selfdrive system sunnypilot \
    --ignore=selfdrive/test/process_replay --ignore=selfdrive/ui/tests/diff \
    -k "not onroad and not power_draw and not test_models_segs"' _ "$JOBS"
  step settings_ui python "$CHECKS/settings_render.py" "$LOG/settings"
fi
step honda_car python -m pytest -q opendbc_repo/opendbc/car/honda/tests
step honda_safety python -m pytest -q opendbc_repo/opendbc/safety/tests/test_honda.py
if [ "$QUICK" = 0 ]; then
  step honda_parallel python -m pytest -q -n "$JOBS" opendbc_repo/opendbc/car/honda/tests
fi
SEG=$(python - "$RLOGS" <<'PY'
from pathlib import Path
import sys
files = list(Path(sys.argv[1]).glob('*/rlog.zst'))
print(max(files, key=lambda p: p.stat().st_mtime) if files else '')
PY
)
if [ -n "$SEG" ]; then
  step replay python tools/ody/replay_segments.py "$SEG"
  step factory_mode python "$CHECKS/factory_mode.py" "$SEG"
  step turn_lane_change python "$CHECKS/turn_lane_change.py" "$RLOGS"
  step lead_depart_chime python "$CHECKS/lead_depart_chime.py" "$RLOGS"
elif [ "$QUICK" = 0 ]; then
  echo "  PENDING drive replay: no rlog.zst under $RLOGS (use --rlogs DIR)"
  PENDING+=(replay)
fi
if [ "$QUICK" = 1 ]; then
  echo '  PENDING stable-release migration audit (run the default/full validation)'
elif git rev-parse -q --verify "$TARGET" >/dev/null; then
  step release_audit python -I "$CHECKS/release_audit.py" "$ROOT" "$TARGET"
else
  warn "comparison ref $TARGET not available; use --target with a local ref"
fi
if [ "$FULL" = 1 ]; then
  step opendbc_suite tools/ody/opendbc_test.sh
  step replay_ab tools/ody/replay_ab.sh
fi
if [ ${#FAILS[@]} -gt 0 ]; then echo "VALIDATION FAILED: ${FAILS[*]}"; exit 1; fi
if [ ${#PENDING[@]} -gt 0 ]; then echo "VALIDATION INCOMPLETE: ${PENDING[*]}"; exit 2; fi
if [ "$QUICK" = 1 ]; then
  echo 'FOCUSED CHECKS PASSED. Full build, inference, UI render, complete suites, replay, migration audit, and device validation remain separate gates.'
else
  echo 'REQUESTED HOST CHECKS PASSED. Device inference/timing and vehicle validation remain pending.'
fi
