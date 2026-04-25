<#
.SYNOPSIS
  Option B: install Python from python.org (system-wide), rebuild venv, refresh
  the mcp-sqlbroker NSSM service so it can run as LocalSystem.
#>
param(
  [string]$Installer   = 'D:\util\python-installer.exe',
  [string]$PythonDir   = 'C:\Python313',
  [string]$InstallDir  = 'D:\util\mcp-sqlbroker',
  [string]$NssmPath    = 'D:\util\nssm.exe',
  [string]$ServiceName = 'mcp-sqlbroker'
)
$ErrorActionPreference = 'Stop'

function Info($m) { Write-Host "[*] $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[+] $m" -ForegroundColor Green }
function Warn($m) { Write-Warning $m }
function Fail($m) { Write-Host "[X] $m" -ForegroundColor Red; exit 1 }

# Wrap NSSM calls so that PS 5.1 does not turn its stderr writes into terminating
# errors when ErrorActionPreference=Stop. Returns the captured output text.
function Invoke-Nssm {
  param([Parameter(ValueFromRemainingArguments=$true)][string[]]$NssmArgs)
  $eap = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    $out = & $NssmPath @NssmArgs 2>&1 | Out-String
    return $out
  } finally {
    $ErrorActionPreference = $eap
  }
}

# 0) Admin check
$current = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal $current).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Fail 'Run this script in an Administrator PowerShell.' }

if (-not (Test-Path $Installer)) { Fail "Installer not found: $Installer" }
if (-not (Test-Path $NssmPath))  { Fail "NSSM not found: $NssmPath" }

# 1) Install Python (idempotent)
$pyExe = Join-Path $PythonDir 'python.exe'
if (Test-Path $pyExe) {
  Ok "Python already at $pyExe, skipping installer"
} else {
  Info "Running silent installer to $PythonDir [AllUsers, no PATH change]"
  $argsList = @(
    '/quiet',
    'InstallAllUsers=1',
    'PrependPath=0',
    'Include_launcher=1',
    'Include_test=0',
    'Include_doc=0',
    "TargetDir=$PythonDir"
  )
  $p = Start-Process -FilePath $Installer -ArgumentList $argsList -Wait -PassThru
  if ($p.ExitCode -ne 0) { Fail "Python installer exit code $($p.ExitCode)" }
  if (-not (Test-Path $pyExe)) { Fail "python.exe not found at $pyExe after install" }
  Ok "Python installed at $pyExe"
}

$ver = (& $pyExe -c "import sys; print(str(sys.version_info[0])+'.'+str(sys.version_info[1])+'.'+str(sys.version_info[2]))").Trim()
Ok "Interpreter: $pyExe (Python $ver)"

# 2) Stop service before replacing venv (ignore if already stopped)
Invoke-Nssm stop $ServiceName | Out-Null

# 3) Rebuild venv
$venv   = Join-Path $InstallDir '.venv'
$venvPy = Join-Path $venv 'Scripts\python.exe'

if (Test-Path $venv) {
  Info "Removing old venv: $venv"
  Remove-Item -Recurse -Force $venv
}
Info "Creating venv with $pyExe"
& $pyExe -m venv $venv
if (-not (Test-Path $venvPy)) { Fail "venv python missing after creation: $venvPy" }

& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -m pip install --quiet -r (Join-Path $InstallDir 'requirements.txt')
& $venvPy -c "import pyodbc, win32crypt; print('deps OK')"
if ($LASTEXITCODE -ne 0) { Fail 'Dependency import test failed in new venv' }
Ok 'venv rebuilt; deps installed'

$cfg = Get-Content (Join-Path $venv 'pyvenv.cfg') -Raw
if ($cfg -match 'WindowsApps') {
  Warn 'pyvenv.cfg still references WindowsApps - check installer'
} else {
  Ok 'pyvenv.cfg points to system Python'
}

# 4) Refresh NSSM service
Invoke-Nssm set $ServiceName Application $venvPy                                  | Out-Null
Invoke-Nssm set $ServiceName AppParameters (Join-Path $InstallDir 'server.py')    | Out-Null
Invoke-Nssm set $ServiceName AppDirectory $InstallDir                             | Out-Null
Invoke-Nssm set $ServiceName ObjectName 'LocalSystem'                             | Out-Null
Invoke-Nssm reset $ServiceName Throttle                                           | Out-Null
Invoke-Nssm start $ServiceName                                                    | Out-Null
Start-Sleep -Seconds 3
$status = (Invoke-Nssm status $ServiceName).Trim()
Ok "Service status: $status"

# 5) Health check
$ok = $false
for ($i = 0; $i -lt 5; $i++) {
  try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8765/health' -TimeoutSec 3 -UseBasicParsing
    if ($r.StatusCode -eq 200) { Ok "Health: $($r.Content)"; $ok = $true; break }
  } catch { Start-Sleep -Seconds 1 }
}
if (-not $ok) {
  Warn 'Health check failed. Tail service logs:'
  Write-Host "  $InstallDir\service.err.log"
  Write-Host "  $InstallDir\service.log"
}

Write-Host ''
Write-Host 'Done. Service runs as LocalSystem against system Python.' -ForegroundColor Yellow
Write-Host 'Add to Claude Code MCP config:'
Write-Host '  "mcpServers": { "sqlbroker": { "url": "http://127.0.0.1:8765/mcp" } }'
