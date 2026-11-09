#!/usr/bin/env bash
# Shared host helpers. Source this file; it does not change a checkout by itself.
ODY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"

ody_jobs() {
  python3 -c 'import os; print(os.environ.get("JOBS", min(os.cpu_count() or 1, 4)))'
}

ody_activate() {
  local root=$1 venv=${2:-${ODY_VENV:-${VIRTUAL_ENV:-$1/.venv}}}
  if [ ! -f "$venv/bin/activate" ]; then
    echo "No environment at $venv; run tools/setup_dependencies.sh or set ODY_VENV." >&2
    return 1
  fi
  source "$venv/bin/activate"
  export PYTHONPATH="$root/opendbc_repo:$root/msgq_repo:$root/tinygrad_repo:$root/rednose_repo:$root/teleoprtc_repo:$root${PYTHONPATH:+:$PYTHONPATH}"
  export SCALE=${SCALE:-1}
}

ody_checkout() {
  local url=$1 ref=$2 dir=$3 current_url status
  if [ -e "$dir" ]; then
    if [ ! -d "$dir/.git" ]; then
      echo "Refusing non-checkout directory: $dir" >&2
      return 1
    fi
    current_url=$(git -C "$dir" remote get-url origin) || return 1
    if [ "${current_url%.git}" != "${url%.git}" ]; then
      echo "Refusing unexpected origin $current_url in $dir (expected $url)." >&2
      return 1
    fi
    status=$(git -C "$dir" status --porcelain) || return 1
    if [ -n "$status" ]; then
      echo "Refusing to switch dirty checkout: $dir" >&2
      return 1
    fi
  else
    git clone --filter=blob:none --no-checkout "$url" "$dir" || return 1
  fi
  git -C "$dir" fetch origin "$ref" || return 1
  if [[ "$ref" =~ ^[0-9a-f]{7,40}$ ]]; then
    git -C "$dir" checkout --detach FETCH_HEAD
  elif git -C "$dir" show-ref --verify --quiet "refs/heads/$ref"; then
    git -C "$dir" checkout "$ref" || return 1
    git -C "$dir" merge --ff-only FETCH_HEAD
  else
    git -C "$dir" checkout -b "$ref" FETCH_HEAD
  fi
}
