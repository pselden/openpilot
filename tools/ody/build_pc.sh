#!/usr/bin/env bash
# Build pselden/openpilot on Apple Silicon macOS or Linux. JOBS caps parallelism (default: up to 4).
# usage: build_pc.sh [branch] [dir]   defaults: sp-ody-dev ~/odypilot-dev
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
BRANCH=${1:-sp-ody-dev}
DIR=${2:-$HOME/odypilot-dev}
command -v git-lfs >/dev/null || { echo 'Install git-lfs first (macOS: brew install git-lfs).' >&2; exit 1; }
ody_checkout https://github.com/pselden/openpilot.git "$BRANCH" "$DIR"
cd "$DIR"
git submodule sync --recursive
git submodule update --init --recursive --jobs "$(ody_jobs)"
git lfs pull
if [ ! -d "$DIR/.venv" ] && [ -z "${ODY_VENV:-}" ]; then
  tools/setup_dependencies.sh
fi
ody_activate "$DIR"
echo "HEAD $(git rev-parse HEAD) | opendbc $(git -C opendbc_repo rev-parse HEAD)"
if ! scons -j"$(ody_jobs)" > "$DIR/scons.log" 2>&1; then
  tail -40 "$DIR/scons.log"
  exit 1
fi
python tools/ody/check_params.py
