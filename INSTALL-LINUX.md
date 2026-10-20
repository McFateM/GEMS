# Installing and testing GEMS on dg-landing

This runbook covers the `linux` branch: a private, single-operator Flet web
service with durable jobs and local configuration/data under `/data`. Desktop mode
remains available. Use the [README](README.md#linuxweb-service-and-local-storage)
for application behavior and the
[dg-landing quick start](../dg-landing/README.md) for VPN/SSH access.

**Status, 2026-10-19:** implementation has been tested locally on macOS, including
87 unit tests and browser/restart tests. It has not been installed or certified
on dg-landing or its intended storage. The `linux` changes are currently
**uncommitted and unpushed**; an ordinary clone cannot obtain them yet.
The commands below are instructions, not actions already performed.

**Storage plan, 2026-10-20:** dg-landing is web-facing and cannot access the
campus SMB `//storage` server. A **500 GB local `/data` store has been requested**
for GEMS and DART operations; provisioning is not yet confirmed. Do not mount
`//storage` on dg-landing. The paths below propose separate GEMS roots under
`/data/gems`; confirm them with the administrator once `/data` is available.
DART's directory layout and migration remain a separate follow-up.
You can begin small, approved pilot tests before `/data` is provisioned; use
[temporary pilot storage](#temporary-pilot-storage-before-data-is-ready) below.

## 1. Publish the branch from the Mac

Review the work before publishing. Do not add credentials, collection data,
logs, or virtual environments.

```bash
cd ~/GitHub/GEMS
git branch --show-current       # must be linux
git status --short
git diff --check
git diff
```

When satisfied, explicitly stage the implementation and documentation:

```bash
git add .env.example README.md INSTALL-LINUX.md run.sh \
  pyproject.toml python_requirements.txt \
  gems/__main__.py gems/app.py gems/pipeline.py \
  gems/storage.py gems/service.py gems/web.py \
  scripts/gems-web.service tests/test_service.py
git diff --cached --stat
git diff --cached
git commit -m "Add private Linux web service and local storage" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push -u origin linux
git rev-parse HEAD
```

Keep that revision for comparison with the server. This does not merge to
`main`. Subsequent development should use additional commits on `linux`.

## 2. Confirm the Linux host and storage plan

On the Mac, connect with `ssh dg-landing`, or open dg-landing through VS Code
Remote - SSH. The following commands now run **on Linux**:

```bash
cat /etc/os-release
uname -m
python3 --version
id
df -h
findmnt
ss -ltn
```

Require Python 3.11+ with its matching `venv` support, Git, CA certificates, and
rsync for the transfer examples. Ask the administrator to install missing OS
packages using the distribution's package manager. Do not replace system Python
or install a desktop environment.

Before using real collections, agree on:

- Provisioning of the requested 500 GB local `/data` store, its backing
  filesystem, backup/restore policy, restricted-data approval, and encryption
  at rest. This capacity is for GEMS and DART together, not 500 GB per
  application; agree on space allocation, retention, and free-space monitoring.
  Local storage is not a backup. Transfers from workstations use SSH, not a
  campus SMB mount on dg-landing.
- Which Linux account runs development tests and which dedicated account will
  eventually run the managed service. Neither application should run as root.
- Local ownership, permissions, and any filesystem ACLs that allow the approved
  operator/service to read and write, without granting general campus access.
- Outbound HTTPS access to Alma and the actual original-object download hosts.
- Filesystem support for advisory locking, atomic rename, and file/directory `fsync`.
  Failure of these operations is a deployment blocker, not a reason to suppress
  exceptions. One application process is supported; this is not a distributed
  multi-host worker system.

For the remaining Linux examples, replace these sample values with approved
paths, in each new shell:

```bash
export GEMS_CONFIG_DIR=/data/gems/config
export GEMS_DATA_DIR=/data/gems/data
export GEMS_ENV_FILE=/data/gems/config/gems.env
```

For the intended deployment, have the administrator provision `/data` and the
two restricted GEMS directories before continuing. For early testing instead,
use the temporary-storage option below. Verify the backing filesystem, not just
directory existence:

```bash
findmnt -T "$GEMS_CONFIG_DIR"
findmnt -T "$GEMS_DATA_DIR"
df -h "$GEMS_CONFIG_DIR" "$GEMS_DATA_DIR"
test -d "$GEMS_CONFIG_DIR" && test -w "$GEMS_CONFIG_DIR"
test -d "$GEMS_DATA_DIR" && test -w "$GEMS_DATA_DIR"
```

**Stop unless these resolve to the administrator-approved local `/data` store
with the expected capacity.** If `/data` is a separate mount, do not initialize
markers on its empty, unmounted mountpoint or an unintended root filesystem.
GEMS does not provision storage or create mounts.

### Temporary pilot storage before /data is ready

GEMS does not require a separate volume or the literal path `/data`. It requires
explicit, existing, writable configuration and data roots with initialized
storage markers. For small pilot tests, deliberately configure temporary
storage outside the checkout, preferably under your normal account's home:

```bash
umask 077
export GEMS_CONFIG_DIR="$HOME/gems-pilot/config"
export GEMS_DATA_DIR="$HOME/gems-pilot/data"
export GEMS_ENV_FILE="$GEMS_CONFIG_DIR/gems.env"

mkdir -p "$GEMS_CONFIG_DIR" "$GEMS_DATA_DIR/pilot"
df -h "$GEMS_DATA_DIR"
printf 'Configuration: %s\nData: %s\n' "$GEMS_CONFIG_DIR" "$GEMS_DATA_DIR"
```

Check available space and any account quota with the administrator. The
requested 500 GB is not available yet; keep test inputs/downloads small and
monitor usage. Use only data approved for this filesystem's access controls,
encryption, and backup arrangements.

**Do not create a temporary `/data` directory on the root filesystem.** Mounting
the future volume over it would hide, not migrate, existing contents; those
files would continue consuming space on the root disk. Another approved,
explicit temporary path is fine.

Continue with steps 3 and 4 using the temporary variables above. In the
environment file, use the full absolute paths printed by `printf`, not the
`/data` example values or literal `$HOME`. Re-export the temporary variables in
each new shell. Use these roots for storage checks and initialization; this is
an intentional pilot configuration, not an automatic fallback after a storage
failure.

In step 5, copy only the small inputs needed for the pilot, and replace all
hard-coded remote `/data/gems/...` destinations with your actual absolute
temporary paths. Do not migrate whole collections into limited home storage.
Steps 6 and 7 use the configured roots for offline and browser testing. Run the
service in the foreground through the SSH tunnel; the managed-service
template's `ProtectHome=true` prevents use of these home-directory roots.

These tests can validate installation, exports, and browser behavior, but do
not certify the eventual `/data` filesystem. Follow
[Moving the pilot to the new /data store](#moving-the-pilot-to-the-new-data-store)
when it becomes available, then repeat storage-specific acceptance tests.

## 3. Install a fresh Linux checkout and environment

Use a private development checkout first. Do not copy the Mac `.venv`.

```bash
mkdir -p ~/GitHub
cd ~/GitHub
git clone --branch linux https://github.com/McFateM/GEMS.git
cd GEMS
git rev-parse HEAD              # compare with the published Mac revision
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[web]'
.venv/bin/python -m pip check
.venv/bin/python -m gems --help
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

For an existing server checkout, inspect `git status` first. With no local work
to preserve, use `git fetch origin`, `git switch linux`, and
`git pull --ff-only`. Do not reset/discard server changes to force an update.

Web installation includes Flet, so the UI unit tests can import it without
installing the desktop runtime. For a CLI-only environment use `pip install -e .`;
that environment does not support running the Flet-dependent tests.

The unit tests do not require your pilot environment file or storage markers;
those are created in step 4. If an older checkout's entry-point tests fail
because they inherit `GEMS_CONFIG_DIR`, `GEMS_DATA_DIR`, or `GEMS_ENV_FILE`,
update to the test-isolation fix. Until then, run the suite with those variables
removed only for the test process:

```bash
env -u GEMS_CONFIG_DIR -u GEMS_DATA_DIR -u GEMS_ENV_FILE \
  .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

This leaves the pilot variables in your shell unchanged. Do not bypass
application storage checks or create markers merely to satisfy unit tests.

## 4. Configure secrets and initialize storage

On Linux, create the private environment file with an editor, not a command
containing the real API key:

```bash
umask 077
touch "$GEMS_ENV_FILE"
chmod 600 "$GEMS_ENV_FILE"
nano "$GEMS_ENV_FILE"
```

Use nano for manual file edits in this runbook. Save with Ctrl+O, press Enter
to confirm the filename, then exit with Ctrl+X. If nano is not installed, ask
the administrator to install it. To make it the default editor for tools that
honor these variables, add the following to your shell startup file using nano
(for example, `nano ~/.bashrc` for interactive Bash sessions):

```bash
export EDITOR=nano
export VISUAL=nano
```

Open a new shell afterward, or run those two exports in the current shell.

Example contents, replacing paths and key. For temporary pilot storage,
substitute the full absolute roots selected in step 2:

```dotenv
GEMS_CONFIG_DIR=/data/gems/config
GEMS_DATA_DIR=/data/gems/data
ALMA_API_REGION=America
ALMA_API_KEY=replace-with-authorized-key
```

Verify effective local permissions and any filesystem ACLs with the
administrator. Environment files are plaintext unless the underlying storage is
encrypted. If institutional policy requires a secret manager, inject
`ALMA_API_KEY` into the process environment instead of saving it in this file.
GEMS does not decrypt secret files; do not save a decryption key alongside them.
Process variables override file values, so remove stale overrides when testing
a changed configuration.

From the Linux GEMS checkout, initialize only the verified `/data` roots (or
the explicitly selected temporary pilot roots):

```bash
.venv/bin/python -m gems --init-storage --env-file "$GEMS_ENV_FILE"
```

This writes `.gems-storage` markers, not application data migrations.
Normal web startup requires these markers and writable storage. No web-mode
automatic fallback to the home directory, checkout, or another storage location
is permitted. An explicitly configured home-directory pilot root is supported.

## 5. Copy legacy data; do not delete the originals

First stop all GEMS/DART/CLI/maintenance writers touching the source or
destination. Take a backup/snapshot and record the migration date, source paths,
and destination paths in your institution's operational records.

Inventory these distinct sources on the **Mac**:

| Source | What to preserve |
| --- | --- |
| `~/.GEMS-data/` | Desktop settings, startup logs, and emergency `unsaved-manifests/` |
| `~/GitHub/GEMS/GEMS-data/` | Historical run folders stored in this checkout |
| The desktop Destination folder | Other run groups, often already on a share |
| Custom field maps | JSON rules and their explanatory documentation |
| Legacy `DG-Exports` | MODS and any related source material required for fallback |
| Prepared manifests/originals | Files referenced by local paths in manifests |
| Metadata-refresh inputs | Baselines, reviewed reports, backups, and published core CSVs, if used |

Preserve **whole collection/set/MMS group directories**, with their original
timestamped children. Keep manifests (including persisted IDs), CSVs, normalized
JSON, objects, logs, and review/baseline files together. Copying only `objects/`
or the newest CSV loses workflow state. Do not flatten run directories or
rename them during the initial transfer.

On Linux, create staging locations inside the approved roots:

```bash
mkdir -p "$GEMS_CONFIG_DIR/maps" "$GEMS_CONFIG_DIR/legacy-desktop"
mkdir -p "$GEMS_DATA_DIR/migrated/checkout-runs"
mkdir -p "$GEMS_DATA_DIR/migrated/home-state"
mkdir -p "$GEMS_DATA_DIR/legacy-mods" "$GEMS_DATA_DIR/pilot"
```

From the **Mac**, these examples copy over SSH to dg-landing's local `/data` store.
Replace remote paths with the actual approved values. A trailing slash copies
the source directory's contents. Run a dry-run first, then remove only `n` from
`-anv` to perform the copy:

```bash
rsync -anv ~/GitHub/GEMS/GEMS-data/ \
  dg-landing:/data/gems/data/migrated/checkout-runs/
rsync -anv ~/.GEMS-data/ \
  dg-landing:/data/gems/data/migrated/home-state/
rsync -anv ~/GitHub/GEMS/maps/ \
  dg-landing:/data/gems/config/maps/
```

Repeat for each additional destination/MODS/originals source. Do not use
`--delete`. If archive mode reports ownership/mode errors, agree on an
appropriate rsync option set with the administrator rather than ignoring
errors. If source material resides on `//storage`, transfer it from an approved
workstation that can access that share; dg-landing must not mount or access it.

After copying, verify file content with a checksum dry-run, for example:

```bash
rsync -rnci ~/GitHub/GEMS/GEMS-data/ \
  dg-landing:/data/gems/data/migrated/checkout-runs/
```

No reported file changes indicates matching source file contents; rsync exit
status must also be zero. This does not prove a backup is restorable or find
extra destination files. Check inventory/counts/capacity and test restore
separately. Keep the original copies until acceptance and backup review.

### Translate paths without changing archival evidence

- Web and desktop settings are separate. Do **not** rename old `settings.json`
  to `web-settings.json`: they use different field names. Enter browser paths
  afresh; preferences are saved when submitting a job.
- Keep archived Mac settings for reference. For continued desktop use, copy a
  reviewed settings file into `GEMS_CONFIG_DIR/settings.json` and update paths
  for that desktop's storage. Keep Mac desktop settings separate from Linux
  settings: `/data` is local to dg-landing, not a shared Mac mount.
- In a **pilot copy**, inspect prepared manifests for local `path`, `local_path`,
  `file`, `source`, and `file://` references. Translate only actual filesystem
  values to Linux `/data` paths, preserving metadata, IDs, and URLs. Do not apply
  a global text replacement to archival JSON. Relative file references also
  need review; do not assume they resolve relative to the manifest.
- Signed Alma links can expire. The mapping pipeline refreshes supported Alma
  representation links when credentials and representation identifiers exist;
  arbitrary old URLs cannot necessarily be refreshed.
- Keep sibling runs together when checking stable object-ID allocation. For
  initial mapping tests, copy the relevant **group tree** into
  `GEMS_DATA_DIR/pilot/` and work there, not against the only migrated baseline.

The web service trusts approved operators and prepared manifests, including
embedded local-file references and download URLs. It is not an untrusted-upload
sandbox. Outputs are written beside the chosen manifest.

## 6. Prove an offline export on the local /data store

On Linux, from the checkout, run this with the storage variables from step 2:

```bash
.venv/bin/python - <<'PY'
import csv
import json
import os
from pathlib import Path
from tempfile import mkdtemp
from gems.pipeline import process_export

root = Path(mkdtemp(prefix="offline-smoke-", dir=Path(os.environ["GEMS_DATA_DIR"]) / "pilot"))
original = root / "original.txt"
original.write_text("GEMS Linux offline test\n", encoding="utf-8")
manifest = root / "manifest.json"
manifest.write_text(json.dumps({"records": [{
    "identifier": "linux-smoke-1",
    "metadata": {"title": "Linux offline test"},
    "files": [{"path": str(original), "filename": "sample.txt"}],
}]}), encoding="utf-8")
result = process_export(manifest, root)
assert result.row_count == 1 and result.file_count == 1
with result.csv_path.open(encoding="utf-8", newline="") as handle:
    assert list(csv.DictReader(handle))[0]["title"] == "Linux offline test"
assert (result.objects_dir / "sample.txt").read_text() == original.read_text()
print("PASS. Pilot manifest for browser testing:", manifest)
PY
```

Keep the printed path for the next step. The disposable smoke directory is
intentionally retained for inspection. Delete only that named directory later,
after checking it contains no real collection data.

## 7. Launch the browser service through SSH

In a Linux terminal, from the checkout:

```bash
umask 077
./run.sh --web --env-file "$GEMS_ENV_FILE"
```

Keep it in the foreground for initial testing. From another Linux terminal:

```bash
curl --fail --silent --show-error -o /dev/null -w 'HTTP %{http_code}\n' \
  http://127.0.0.1:8550/
ss -ltn 'sport = :8550'
```

The listener must be `127.0.0.1:8550`, not `0.0.0.0` or a public address.
An HTTP response is only a readiness check, not a completed browser test.

From a second terminal on the **Mac**:

```bash
ssh -N -o ExitOnForwardFailure=yes -L 8550:127.0.0.1:8550 dg-landing
```

Open <http://127.0.0.1:8550> on the Mac. Enter the Linux pilot manifest path
from step 6 and run step 2 in the UI. Inspect the completed job, result files,
and job log. Leave the optional field map blank for this minimal smoke test.

For a real collection test, use the copied Grinnell map under
`GEMS_CONFIG_DIR/maps/alma-dc-to-grinnell.json`, and supply the Linux MODS folder
if needed. Use a small approved MMS-ID selection and a pilot destination for
retrieval. Retrieval always fetches the entire selection; start/limit apply
only to mapping. Start with a record limit of 1 and inspect all output before
testing larger batches.

## 8. Acceptance checklist before using production data

- [ ] Record Linux OS/architecture, Python version, Git revision, and package
  versions (`.venv/bin/python -m pip freeze`); tests and `pip check` pass.
- [ ] The requested 500 GB local `/data` store is provisioned; GEMS/DART space
  allocation, retention, free-space monitoring, and backups are agreed.
- [ ] Offline and browser smoke exports write correct objects/CSV to `/data`.
- [ ] Authorized Alma retrieval and signed-link refresh work from dg-landing.
- [ ] Template-map batches merge correctly, IDs remain stable, and MODS fills
  only fields empty in Alma.
- [ ] Progress, failures, skipped records, and filename clashes are visible.
- [ ] Second browser tab is read-only. Closing the operator tab transfers
  control, while any running job continues; history/job URL restores status.
- [ ] A second web process using the same roots refuses startup while the first
  holds the lock. This must be verified on the actual `/data` filesystem.
- [ ] Cancel a disposable job, wait for it to stop, and inspect partial output.
- [ ] Restart with a completed job and confirm persisted history. On a
  disposable test job, exercise forced termination and verify the unfinished
  job is **interrupted**, never automatically resumed or reported successful.
- [ ] With administrator supervision and isolated pilot storage, simulate
  unavailable storage and restoration. Never unmount the production `/data`
  volume simply to test this. Verify explicit failure/no home-directory
  fallback, restore storage, and restart a write-blocked service.
- [ ] Restore a backup into separate pilot roots and validate its files/state.

No concurrent desktop/CLI/maintenance/DART writer may touch the active output
tree. These other tools do not participate in the web service lock.

### Moving the pilot to the new /data store

Do not mount the new volume over the temporary files or delete the pilot
source as part of this procedure.

1. Stop GEMS with Ctrl+C and wait for worker shutdown. Stop every other writer
   touching either tree. Back up the pilot and record source/destination paths.
2. Have the administrator provision and verify the new 500 GB local store and
   the restricted `/data/gems/config` and `/data/gems/data` directories. Confirm
   their backing filesystem with `findmnt -T`, available capacity with `df -h`,
   and read/write access for the intended operator/service account. Do not
   create these paths on an unmounted mountpoint. Use empty destinations for
   this migration; stop and reconcile any existing application state first.
3. On dg-landing, copy both complete trees, including hidden files, markers,
   settings, secrets, job history, and complete run groups. The following
   commands assume the recommended `$HOME/gems-pilot` source and approved
   `/data/gems` destination. Run the dry-runs first:

   ```bash
   rsync -anv "$HOME/gems-pilot/config/" /data/gems/config/
   rsync -anv "$HOME/gems-pilot/data/" /data/gems/data/
   ```

   After reviewing the output, perform the copies:

   ```bash
   rsync -av "$HOME/gems-pilot/config/" /data/gems/config/
   rsync -av "$HOME/gems-pilot/data/" /data/gems/data/
   ```

   Do not use `--delete`. Resolve any ownership/mode errors with the
   administrator; do not ignore errors or broaden access to secrets.
4. Before editing destination files, verify contents with checksum dry-runs:

   ```bash
   rsync -rnci "$HOME/gems-pilot/config/" /data/gems/config/
   rsync -rnci "$HOME/gems-pilot/data/" /data/gems/data/
   ```

   Require zero exit status and no reported file changes. Also review file
   inventory, permissions, and backup/restore; checksums alone do not establish
   those properties or detect extra destination files.
5. Set the three shell variables to the `/data` values in step 2. Edit the
   **destination** environment file so both roots point to `/data/gems/...`.
   Process variables override file values, so update them in every launch
   shell and update any launcher or `GEMS_ENV_FILE` pointer. Verify restrictive
   permissions on the copied environment file.
6. Review saved settings, maps, and prepared manifests for absolute temporary
   paths. Copying files does not rewrite embedded paths in settings, manifests,
   or job history. Preserve historical records; translate actual filesystem
   references in reviewed working copies, preserving metadata, IDs, and URLs.
   Do not blanket-replace archival JSON or edit job history to force retries.
   Select the new manifest/map/destination paths in the browser and submit new
   jobs; old history may still display its original temporary paths.
7. Run the step 4 initialization/check command against the destination roots.
   Repeat the offline and browser smoke tests, then the step 8 acceptance
   checks on the actual `/data` filesystem, including locking, interruption,
   storage failure, permissions, and backup/restore. Keep the temporary source
   until acceptance and backup review; do not run writers against both copies.

## 9. Continue development on Linux

In VS Code Remote - SSH, open `~/GitHub/GEMS`, select
`.venv/bin/python`, and stay on `linux`. Edit and test there, or push changes
from the Mac and pull them into a clean server checkout; avoid conflicting
uncommitted work on both machines.

```bash
git status --short
git pull --ff-only
# Only when dependency metadata changes or the selected runtime is missing:
.venv/bin/python -m pip install -e '.[web]'
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python -m pip check
git diff --check
```

Stop the foreground service with Ctrl+C and wait for worker shutdown before
updating code. Restart and retest. Launch does not install dependencies on
every run; `./run.sh --install --web` explicitly refreshes the selected runtime.
Keep development and real processing separated by data roots. Do not delete
job state or edit job JSON to force retries; review partial output and submit
a new job.

The [service](gems/service.py), [web UI](gems/web.py), and
[storage layer](gems/storage.py) are separate from the existing
[desktop UI](gems/app.py); both reuse the [pipeline](gems/pipeline.py).
Keep the [service tests](tests/test_service.py) and existing desktop/pipeline
tests passing, and verify desktop behavior on the Mac before merging to `main`.
DART is a separate follow-up; do not migrate its state implicitly with GEMS.

## 10. Move to managed hosting only after acceptance

Have the administrator adapt [scripts/gems-web.service](scripts/gems-web.service):

1. Use a dedicated service account and a release checkout/venv outside home
   directories, matching the unit's `/opt/gems` paths or updating them.
2. Replace both `ReadWritePaths` placeholders; add `RequiresMountsFor=` with
   approved configuration/data paths in `[Unit]` so their backing mounts are ready.
3. Provision `/etc/gems/bootstrap.env` with a non-secret `GEMS_ENV_FILE` pointer
   to `/data/gems/config/gems.env` (or the approved protected file). Confirm all
   required read paths are accessible under `ProtectSystem`/`ProtectHome`,
   including legacy inputs and CA bundles.
4. Test the edited unit and its effective permissions. Its five-minute stop
   timeout may need adjustment for real downloads and storage behavior.
5. Install dependencies at deployment time. Record/pin an approved Linux
   dependency set after passing tests; no cross-platform lock is supplied yet.
6. Use systemd/journal monitoring, backups, and a tested rollback procedure.
   Reverting code does not revert mutated manifests or CSVs.

Continue using the SSH tunnel until approved HTTPS and institutional
authentication protect **both HTTP and WebSocket** traffic. Loopback is not
user authentication; other local server users may reach it. The service is
not ready for untrusted users or general network exposure.
