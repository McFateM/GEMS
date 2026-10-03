<#
.SYNOPSIS
  Bootstrap a Windows workstation for running GEMS and DART from source.

.DESCRIPTION
  Run this inside an RDP (or console) session on the remote Windows machine.
  It will:
    1. Ensure git and Python 3.11+ are installed (via winget when needed).
    2. Clone GEMS, DART, and common-DG-utilities as sibling checkouts.
    3. Create a .venv in each app and install its python_requirements.txt.
    4. Create run-gems.bat / run-dart.bat launchers on the desktop.

.PARAMETER InstallRoot
  Folder that will hold the sibling repos. Default: ~\GitHub

.PARAMETER SkipGems / SkipDart
  Skip installing one of the apps.

.EXAMPLE
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
  .\bootstrap_remote_windows.ps1
  .\bootstrap_remote_windows.ps1 -InstallRoot D:\DG -SkipDart
#>

[CmdletBinding()]
param(
  [string]$InstallRoot = (Join-Path $HOME "GitHub"),
  [switch]$SkipGems,
  [switch]$SkipDart
)

$ErrorActionPreference = "Stop"

$GemsRepo   = "https://github.com/McFateM/GEMS.git"
$DartRepo   = "https://github.com/Digital-Grinnell/DART.git"
$CommonRepo = "https://github.com/McFateM/common-DG-utilities.git"

function Write-Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

# ---------------------------------------------------------------------------
# 1. Prerequisites: git and Python
# ---------------------------------------------------------------------------
function Install-WithWinget($Id, $Name) {
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget is not available. Install '$Name' manually, then re-run this script.`n" +
          "  git:    https://git-scm.com/download/win`n" +
          "  Python: https://www.python.org/downloads/ (check 'Add python.exe to PATH')"
  }
  Write-Host "Installing $Name via winget..."
  winget install --id $Id --exact --silent --accept-source-agreements --accept-package-agreements
}

Write-Step "Checking prerequisites"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Install-WithWinget "Git.Git" "git"
  # Refresh PATH for this session
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
              [System.Environment]::GetEnvironmentVariable("Path","User")
}
Write-Host "git:    $((git --version) -replace 'git version ','')"

$python = Get-Command python -ErrorAction SilentlyContinue
$needPython = $true
if ($python) {
  $ver = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
  if ([version]$ver -ge [version]"3.11") { $needPython = $false }
}
if ($needPython) {
  Install-WithWinget "Python.Python.3.12" "Python 3.12"
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
              [System.Environment]::GetEnvironmentVariable("Path","User")
}
Write-Host "python: $(& python --version)"

# ---------------------------------------------------------------------------
# 2. Clone the sibling repositories
# ---------------------------------------------------------------------------
Write-Step "Cloning repositories into $InstallRoot"
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null

function Ensure-Clone($Url, $Path) {
  if (Test-Path (Join-Path $Path ".git")) {
    Write-Host "Already cloned: $Path (pulling latest)"
    git -C $Path pull --ff-only
  } else {
    git clone $Url $Path
  }
}

# common-DG-utilities must exist BEFORE pip installs (requirements reference
# it as an editable sibling: '-e ../common-DG-utilities').
Ensure-Clone $CommonRepo (Join-Path $InstallRoot "common-DG-utilities")
if (-not $SkipGems) { Ensure-Clone $GemsRepo (Join-Path $InstallRoot "GEMS") }
if (-not $SkipDart) { Ensure-Clone $DartRepo (Join-Path $InstallRoot "DART") }

# ---------------------------------------------------------------------------
# 3. Virtual environments + dependencies
# ---------------------------------------------------------------------------
function Install-App($RepoPath, $EntryHint) {
  Write-Step "Setting up $(Split-Path $RepoPath -Leaf)"
  Push-Location $RepoPath
  try {
    if (-not (Test-Path ".venv")) {
      python -m venv .venv
    }
    $venvPython = Join-Path $RepoPath ".venv\Scripts\python.exe"
    & $venvPython -m pip install --upgrade pip --quiet
    & $venvPython -m pip install -r python_requirements.txt
    Write-Host "[OK] Dependencies installed."
  } finally {
    Pop-Location
  }
}

if (-not $SkipGems) { Install-App (Join-Path $InstallRoot "GEMS") "python -m gems" }
if (-not $SkipDart) { Install-App (Join-Path $InstallRoot "DART") "python app.py" }

# ---------------------------------------------------------------------------
# 4. Desktop launchers
# ---------------------------------------------------------------------------
Write-Step "Creating desktop launchers"
$desktop = [Environment]::GetFolderPath("Desktop")

if (-not $SkipGems) {
  $gemsBat = @"
@echo off
cd /d "$(Join-Path $InstallRoot 'GEMS')"
call .venv\Scripts\activate.bat
python -m gems
pause
"@
  Set-Content -Path (Join-Path $desktop "run-gems.bat") -Value $gemsBat -Encoding ASCII
  Write-Host "[OK] $desktop\run-gems.bat"
}

if (-not $SkipDart) {
  $dartBat = @"
@echo off
cd /d "$(Join-Path $InstallRoot 'DART')"
call .venv\Scripts\activate.bat
python app.py
pause
"@
  Set-Content -Path (Join-Path $desktop "run-dart.bat") -Value $dartBat -Encoding ASCII
  Write-Host "[OK] $desktop\run-dart.bat"
}

# ---------------------------------------------------------------------------
Write-Step "Done"
Write-Host @"
Next steps:
  * GEMS: copy your .env (ALMA_API_KEY / ALMA_API_REGION) into
    $(Join-Path $InstallRoot 'GEMS') before retrieving from Alma.
  * DART: configure Function 0 (app settings) on first run.
  * Launch either app from the desktop .bat files.
See REMOTE_WINDOWS.md in the GEMS repo for the full remote-workflow guide.
"@
