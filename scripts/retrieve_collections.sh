#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'Usage: %s TITLES_FILE OUTPUT_DIRECTORY [ENV_FILE]\n' "$0"
  printf 'Retrieve each collection title (one per line); stop at the first failure.\n'
}

if [[ "${1:-}" == --help ]]; then
  usage
  exit 0
fi
if [[ $# -lt 2 || $# -gt 3 ]]; then
  usage >&2
  exit 2
fi

titles_file=$1
output=$2
env_file=${3:-${GEMS_ENV_FILE:-}}
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python="$repo/.venv/bin/python"

if [[ ! -f "$titles_file" || ! -r "$titles_file" ]]; then
  printf 'Cannot read collection-title file: %s\n' "$titles_file" >&2
  exit 2
fi
if [[ ! -d "$output" || ! -w "$output" ]]; then
  printf 'Output must be an existing writable directory: %s\n' "$output" >&2
  exit 2
fi
if [[ ! -x "$python" ]]; then
  printf 'GEMS virtual environment is missing: %s\n' "$python" >&2
  printf 'Install the headless runtime before running this script.\n' >&2
  exit 2
fi
args=(-m gems --headless --retrieve)
if [[ -n "$env_file" ]]; then
  if [[ ! -f "$env_file" || ! -r "$env_file" ]]; then
    printf 'Cannot read environment file: %s\n' "$env_file" >&2
    exit 2
  fi
  if [[ "$env_file" != /* ]]; then
    env_file="$PWD/$env_file"
  fi
  args+=(--env-file "$env_file")
fi
output=$(cd "$output" && pwd)
exec 3< "$titles_file"
cd "$repo"

completed=0
line=0
while IFS= read -r title <&3 || [[ -n "$title" ]]; do
  line=$((line + 1))
  title="${title#"${title%%[![:space:]]*}"}"
  title="${title%"${title##*[![:space:]]}"}"
  if [[ -z "$title" ]]; then
    continue
  fi
  printf '\nRetrieving collection (line %s): %s\n' "$line" "$title"
  if "$python" "${args[@]}" \
      --collection-title="$title" --output "$output" </dev/null; then
    completed=$((completed + 1))
  else
    status=$?
    printf 'Stopped at line %s: %s (exit %s). Completed %s collection(s).\n' \
      "$line" "$title" "$status" "$completed" >&2
    exit "$status"
  fi
done
exec 3<&-

if [[ "$completed" == 0 ]]; then
  printf 'No collection titles found in: %s\n' "$titles_file" >&2
  exit 2
fi
printf '\nCompleted button 1 for %s collection(s). No button 2 exports were started.\n' "$completed"
