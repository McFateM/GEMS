# Running GEMS and DART from a Remote Windows Workstation

Both GEMS and DART move large files between local storage, campus network
shares, and Azure Blob Storage. Running them on a workstation that sits
*inside* the Grinnell campus network avoids pushing gigabytes through a VPN
tunnel: network-share copies stay on the fast LAN, and Azure transfers ride
the campus internet connection instead of your home uplink.

This document covers connecting from this Mac to the remote Windows
workstation at **132.161.47.174** and getting both tools installed there.

> **Campus note:** 132.161.47.174 is a Grinnell-internal address, so the Mac
> must be on the VPN (or on campus) before any of the connections below will
> work.

---

## 0. First: test the connection (2 minutes, no installs)

Do these checks on the Mac **with the VPN connected**, before setting anything
up. They tell you exactly where any blocker is.

### 0a. Is the workstation reachable?

```bash
ping -c 3 132.161.47.174
```

- **Replies come back** → machine is online and reachable; go to 0b.
- **100% packet loss / timeouts** → the VPN isn't routing to campus, or the
  machine is off or asleep. Confirm the VPN is actually connected and retry;
  if it still fails, someone near the machine (or ITS) needs to wake/power it.

### 0b. Is Remote Desktop listening?

```bash
nc -vz -w 3 132.161.47.174 3389
```

- **"Connection to 132.161.47.174 port 3389 ... succeeded!"** → RDP is
  enabled; go to 0c.
- **"Operation timed out" / "Connection refused"** → Remote Desktop is not
  enabled on the workstation (or a firewall blocks it). Someone with admin
  access must turn it on: *Settings → System → Remote Desktop → On* — likely
  an ITS request.

### 0c. Try a real RDP login

1. Install **Windows App** from the Mac App Store (free, by Microsoft;
   formerly *Microsoft Remote Desktop*).
2. Open it → **+ → Add PC** → PC name: `132.161.47.174` → save.
3. Double-click it. Credentials: try `GRINNELL\yourusername` (domain account),
   or `.\yourusername` for a local account. Accept any certificate warning —
   that is normal on first connect.

- **Windows desktop appears** → everything works; proceed to section 2.
- **"Your credentials did not work"** → RDP is fine; you just need your
  account added to the machine's *Remote Desktop Users* group (ITS request).
- **Cannot connect at all** → same as 0b's failure: Remote Desktop must be
  enabled on the workstation first.

**Rule of thumb:** 0a failing = VPN or machine off; 0b failing = RDP not
enabled; 0c failing on credentials = permissions only. The first two are fixed
on the Windows side — that is when to contact ITS.

---

## 1. About "Screen Sharing" (VNC)

macOS's built-in **Screen Sharing** app speaks VNC. Windows has **no built-in
VNC server**, so Screen Sharing can only connect to the Windows box if a VNC
server (e.g. [TightVNC](https://www.tightvnc.com/) or
[UltraVNC](https://uvnc.com/)) has been installed there. That is usually *not*
the case on a managed campus machine.

**The native and recommended way to reach a Windows workstation is RDP
(Remote Desktop Protocol).** It is built into Windows, gives a full desktop
session, and performs much better than VNC over a VPN.

### 1a. One-time prerequisite on the Windows workstation

1. **Enable Remote Desktop** on the Windows machine:
   *Settings → System → Remote Desktop → On* (Windows 10/11 Pro or Enterprise;
   Windows Home does not include the RDP server).
2. Make sure your Grinnell account is allowed to log on remotely (it is by
   default for the machine's administrators / Remote Desktop Users group).
3. Know the account name you will use, typically `GRINNELL\yourusername` or
   `.\localuser`.

If you do not have admin rights on that workstation, ask ITS to enable Remote
Desktop and add your account.

### 1b. Connect from the Mac

Microsoft's free **Windows App** (formerly *Microsoft Remote Desktop*) is the
Mac RDP client:

1. Install **Windows App** from the Mac App Store
   (search "Windows App" by Microsoft Corporation).
2. Open it → **+ → Add PC**:
   - **PC name:** `132.161.47.174`
   - **User account:** add your Grinnell credentials so you are not prompted
     each time.
   - Friendly name: e.g. `Campus workstation`.
3. Double-click the saved PC. You now have a full Windows desktop.
4. Optional conveniences in the PC's settings:
   - **Devices & Audio → Folders** — redirect a Mac folder into the session
     (handy for moving small files; large data should live on the Windows
     side or on network shares).
   - Enable **clipboard sharing** (on by default) so you can copy/paste
     commands and paths between Mac and Windows.

**Alternative:** the free [Royal TSX](https://www.royalapps.com/ts/mac/features)
client also speaks RDP if you prefer it.

> If you ever *do* find TightVNC running on the Windows box, you can use the
> built-in Screen Sharing app instead: Finder → **Go → Connect to Server…** →
> `vnc://132.161.47.174`. But RDP is the better default.

### 1c. Terminal-only access (optional)

If you only need a shell and not a desktop:

- Windows 10/11 can run an **OpenSSH Server**
  (*Settings → Apps → Optional Features → Add a feature → OpenSSH Server*).
  Once running, from the Mac: `ssh yourusername@132.161.47.174`.
- This is handy for scripting, but both GEMS and DART are Flet **desktop**
  apps, so you will want the RDP graphical session to actually run them.

---

## 2. Installing GEMS and DART on the Windows workstation

Both apps run fine on Windows from source (DART even ships a
`scripts\run.bat`). The repository includes a bootstrap script that does the
whole setup: [scripts/bootstrap_remote_windows.ps1](scripts/bootstrap_remote_windows.ps1).

**In the RDP session**, open **PowerShell** and run:

```powershell
# Allow this script to run (current user only, one time)
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# Download and run the bootstrap (adjust the path to wherever you fetched it)
# Simplest: clone the GEMS repo and run it from there, e.g.:
#   git clone https://github.com/McFateM/GEMS.git
#   .\GEMS\scripts\bootstrap_remote_windows.ps1
```

Or copy `scripts\bootstrap_remote_windows.ps1` onto the machine (clipboard
paste into Notepad, redirected folder, or a network share) and run it.

### What the bootstrap does

1. Checks for **git** and **Python 3.11+**; if missing, installs them via
   `winget` (built into current Windows 10/11). If `winget` is unavailable it
   prints manual download links and stops.
2. Clones the three sibling repositories (GEMS and DART both expect
   `common-DG-utilities` as a sibling checkout):
   - `https://github.com/McFateM/GEMS.git`
   - `https://github.com/Digital-Grinnell/DART.git`
   - `https://github.com/McFateM/common-DG-utilities.git`
3. Creates a `.venv` in each app and installs its `python_requirements.txt`
   (which pulls the sibling `common-DG-utilities` as an editable package).
4. Drops convenience launchers `run-gems.bat` and `run-dart.bat` on the
   Windows desktop.

Flags (all optional):

```powershell
.\bootstrap_remote_windows.ps1 -InstallRoot "D:\DG"   # default: ~\GitHub
.\bootstrap_remote_windows.ps1 -SkipDart               # GEMS only
.\bootstrap_remote_windows.ps1 -SkipGems               # DART only
```

### After the bootstrap

- **Run DART:** double-click `run-dart.bat` on the desktop (or run
  `scripts\run.bat` in the DART folder). It reuses the existing `.venv`.
- **Run GEMS:** double-click `run-gems.bat`. GEMS has no Windows launcher in
  the repo, so the bootstrap creates one equivalent to `run.sh`
  (activate `.venv`, `python -m gems`).
- **Update either app:** `git pull` in its folder; the launcher reinstalls
  dependencies if the requirements changed (DART's `run.bat` does this
  automatically; for GEMS just re-run `pip install -r python_requirements.txt`
  inside its `.venv` if a pull mentions new dependencies).

---

## 3. Data paths on the remote machine

- **GEMS destination folder:** set it in the *Retrieve from Alma* section (or
  use the default). On the campus workstation, point it at the same location
  the Mac uses — e.g. the mapped drive equivalent of `/Volumes/DGIngest/.GEMS-data`
  (perhaps `S:\DGIngest\.GEMS-data` or a UNC path like
  `\\server\share\DGIngest\.GEMS-data`), or a local disk on the workstation if
  the files will later be moved. Ask ITS how the DGIngest share is mounted on
  that machine.
- **Azure Blob Storage:** DART's Function 4 talks directly to Azure; from the
  campus network these transfers no longer traverse your VPN.
- **Alma API:** GEMS needs the same `.env` contract as on the Mac — copy your
  `.env` (with `ALMA_API_KEY` and `ALMA_API_REGION`) into the GEMS folder on
  the workstation. The key is never stored in GEMS's settings file.
- **DART settings:** DART keeps its own app settings on the Windows machine;
  configure Function 0 there on first run.

---

## 4. Performance tips

- Keep the **working data on the Windows workstation's local disk** or on the
  campus file share — never on a folder redirected from the Mac over RDP,
  which would route every file through the VPN.
- RDP is efficient, but on a slow home connection reduce the session
  resolution / color depth in Windows App's PC settings.
- The RDP session keeps running if you disconnect (the apps keep working).
  Choose **Disconnect**, not **Sign out**, when you leave — sign out would
  kill running exports.
- Long DART/GEMS jobs survive a VPN drop as long as the RDP session was only
  disconnected, not signed out.

---

## 5. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Windows App can't reach 132.161.47.174 | Not on VPN, or Remote Desktop disabled on the workstation |
| Credentials rejected | Use `GRINNELL\username`; confirm the account is in the machine's Remote Desktop Users |
| `python` / `git` not found after install | Close and reopen PowerShell so PATH refreshes |
| `winget` missing | Install "App Installer" from the Microsoft Store, or install git + Python manually from their websites |
| pip install of `seeklight` fails in DART | Needs git on PATH (it clones from GitHub); reinstall git with "Git from the command line" enabled |
| Flet window blank/spinning | Stuck Flet client — close the app, kill any `flet` process in Task Manager, relaunch |
| Signed Alma download URLs failing mid-run | They expire after ~1 hour; GEMS refreshes them automatically, but keep runs reasonably sized |
