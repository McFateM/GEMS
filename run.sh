#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

mode=desktop
install=0
args=()
for arg in "$@"; do
  case "$arg" in
    --web) mode=web; args+=("$arg") ;;
    --headless) mode=core; args+=("$arg") ;;
    --install) install=1 ;;
    *) args+=("$arg") ;;
  esac
done

if [[ ! -d .venv ]]; then
  "${GEMS_PYTHON:-python3}" -m venv .venv
  install=1
fi
if [[ "$install" == 1 ]]; then
  requirement="."
  if [[ "$mode" != core ]]; then
    requirement=".[${mode}]"
  fi
  .venv/bin/python -m pip install -e "$requirement"
fi
exec .venv/bin/python -m gems "${args[@]}"