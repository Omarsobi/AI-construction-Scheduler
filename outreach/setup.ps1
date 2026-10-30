# Windows equivalent of setup.sh. Run in PowerShell from the repo:  powershell -ExecutionPolicy Bypass -File outreach\setup.ps1
# Needs: Git for Windows, Python 3.11+, Claude Code logged in (claude login).
$ErrorActionPreference = "Stop"
$v = (& python --version 2>&1)
if ($LASTEXITCODE -ne 0 -or "$v" -notmatch "Python 3\.1[1-9]") { throw "Python 3.11+ not found. Install from python.org and tick 'Add python.exe to PATH', then reopen PowerShell. Got: $v" }
if ($PSScriptRoot -like "C:\Windows\*") { throw "Do not run from C:\Windows. Clone the repo into your user folder, e.g. cd `$HOME" }
$Here = $PSScriptRoot
$Harvey = Join-Path $Here "harvey"
$Pin = "4237f07f5873e270c362b43aec76e60fc4faa9cf"

if (-not (Test-Path (Join-Path $Harvey ".git"))) { git clone https://github.com/ethanplusai/harvey $Harvey }
git -C $Harvey fetch -q origin $Pin
git -C $Harvey checkout -q $Pin

# Two-email sequences. Skip if already applied.
git -C $Harvey apply --check (Join-Path $Here "patches\two-email-sequence.patch") 2>$null
if ($LASTEXITCODE -eq 0) { git -C $Harvey apply (Join-Path $Here "patches\two-email-sequence.patch") }

# Windows symlinks need admin, so copy. Edit the files in outreach\ and re-run this script.
Copy-Item (Join-Path $Here "harvey.local.yaml") (Join-Path $Harvey "harvey.local.yaml") -Force
Copy-Item (Join-Path $Here "skills\product_knowledge.md") (Join-Path $Harvey "skills\product_knowledge.md") -Force

$Py = Join-Path $Harvey ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { python -m venv (Join-Path $Harvey ".venv") }
& $Py -m pip install -q -e "$Harvey[dev]"

Set-Location $Harvey
& (Join-Path $Harvey ".venv\Scripts\harvey.exe") status --check
Write-Host "Done. Next: .venv\Scripts\activate ; harvey signals --confirm HIRING_ROLE,OPEN_ROLES,CONTACT_FOUND,DECISION_MAKER_TITLE,LIKELY_OWNER,EMAIL_STATUS"
