#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'Usage: bash %s [--dry-run | --move]\n' "$0"
  printf 'Run on your Mac with DGIngest mounted. Default: preview only.\n'
  printf 'Move only files inside objects/.complete/ beneath migrated.\n'
  printf 'Do not write to those directories during a move.\n'
}

mode=${1:---dry-run}
if [[ "$mode" == --help && $# == 1 ]]; then
  usage
  exit 0
fi
if [[ $# -gt 1 || ( "$mode" != --dry-run && "$mode" != --move ) ]]; then
  usage >&2
  exit 2
fi

mount_point=/Volumes/DGIngest
source=sysadmin@dg-landing:/data/gems/data/migrated/
destination="$mount_point/_GEMS_Migration/Migrated"

for tool in rsync ssh mount; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$tool" >&2
    exit 2
  fi
done
if [[ -L "$mount_point" ]] || ! mount | grep -F " on $mount_point (smbfs," >/dev/null; then
  printf 'Mount the DGIngest SMB share at %s before running this script.\n' "$mount_point" >&2
  exit 2
fi
if [[ ! -w "$mount_point" ]]; then
  printf 'Network volume is not writable: %s\n' "$mount_point" >&2
  exit 2
fi

mkdir -p "$destination"
destination=$(cd "$destination" && pwd -P)
case "$destination/" in
  "$mount_point/"*) ;;
  *)
    printf 'Destination resolves outside the network volume: %s\n' "$destination" >&2
    exit 2
    ;;
esac

args=(-rlt --checksum --progress --stats --itemize-changes
  --prune-empty-dirs '--include=*/' '--include=**/objects/.complete/**' '--exclude=*'
  --partial-dir=.gems-rsync-partial
  --backup "--backup-dir=$destination/.replaced/$(date -u +%Y%m%dT%H%M%SZ)-$$"
  -e 'ssh -o BatchMode=yes')
if [[ "$mode" == --move ]]; then
  args+=(--remove-source-files)
  printf 'MOVING only objects/.complete/ contents from %s to %s/\n' "$source" "$destination"
else
  args+=(--dry-run)
  printf 'PREVIEW ONLY (objects/.complete/ contents): %s -> %s/\n' "$source" "$destination"
fi

if rsync "${args[@]}" "$source" "$destination/"; then
  if [[ "$mode" == --move ]]; then
    printf '\nMove completed. Successfully transferred files were removed from dg-landing.\n'
    printf 'Empty source directories were retained. Destination-only files were not deleted.\n'
  else
    printf '\nPreview completed. No source files were removed. Use --move to transfer and remove them.\n'
  fi
else
  status=$?
  printf '\nTransfer failed (exit %s). Some files may already have moved; rerun the same command to resume.\n' \
    "$status" >&2
  exit "$status"
fi
