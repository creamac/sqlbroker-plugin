<#
.SYNOPSIS
  Portable installer for MCP SQL Broker on Windows.

.DESCRIPTION
  - Verifies Python 3.10+ on PATH (or use -PythonExe)
  - Copies server.py / manage_conn.py / requirements.txt to InstallDir
  - Creates a venv, installs pyodbc + pywin32 (no fastmcp/pydantic; Smart App Control safe)
  - Optionally registers a Windows service via NSSM and starts it
  - Health-checks the HTTP endpoint

.PARAMETER InstallDir
  Target directory. Default: D:\util\mcp-sqlbroker

.PARAMETER NssmPath
  Path to nssm.exe. If not provided, common locations are searched.

.PARAMETER PythonExe
  Override system python. Default: result of `python` on PATH.

.PARAMETER Port
  Port for the HTTP MCP endpoint. Default: 8765

.PARAMETER BindHost
  Bind address. Default: 127.0.0.1 (localhost only — recommended)

.PARAMETER ServiceName
  NSSM service name. Default: mcp-sqlbroker

.PARAMETER ServiceUser
  Run service as this user (requires -ServicePassword). Default: LocalSystem.

.PARAMETER SkipService
  Install files only; do not register the Windows service.

.EXAMPLE
  .\deploy.ps1
  .\deploy.ps1 -InstallDir 'C:\apps\mcp-sqlbroker' -NssmPath 'C:\tools\nssm.exe' -Port 9000
  .\deploy.ps1 -SkipService
#>
[CmdletBinding()]
param(
  [string]$InstallDir   = 'D:\util\mcp-sqlbroker',
  [string]$NssmPath     = '',
  [string]$PythonExe    = '',
  [int]   $Port         = 8765,
  [string]$BindHost     = '127.0.0.1',
  [string]$ServiceName  = 'mcp-sqlbroker',
  [string]$ServiceUser  = '',
  [string]$ServicePassword = '',
  [switch]$SkipService
)

$ErrorActionPreference = 'Stop'

function Info($m) { Write-Host "[*] $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[+] $m" -ForegroundColor Green }
function Warn($m) { Write-Warning $m }
function Fail($m) { Write-Host "[X] $m" -ForegroundColor Red; exit 1 }

# --- 1) Python ---
if (-not $PythonExe) {
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if (-not $cmd) { Fail 'python not on PATH. Install Python 3.10+ from python.org or pass -PythonExe.' }
  $PythonExe = $cmd.Source
}
$ver = (& $PythonExe -c "import sys;print('{0}.{1}'.format(*sys.version_info[:2]))").Trim()
if ([version]$ver -lt [version]'3.10') {
  Fail "Python $ver too old (need >=3.10)"
}
Ok "Python $ver at $PythonExe"

# --- 2) Install dir + copy source files ---
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$srcFiles = @('server.py', 'manage_conn.py', 'requirements.txt', 'README.md')
foreach ($f in $srcFiles) {
  $src = Join-Path $here $f
  if (Test-Path $src) {
    Copy-Item $src -Destination $InstallDir -Force
  } elseif ($f -ne 'README.md') {
    Fail "Required source file '$f' missing next to deploy.ps1"
  }
}
Ok "Files copied to $InstallDir"

# --- 3) venv + deps ---
$venv = Join-Path $InstallDir '.venv'
$venvPy = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
  Info "Creating venv at $venv"
  & $PythonExe -m venv $venv
}
& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -m pip install --quiet -r (Join-Path $InstallDir 'requirements.txt')
# Quick smoke test of imports
& $venvPy -c "import pyodbc, win32crypt; print('deps OK')"
if ($LASTEXITCODE -ne 0) { Fail 'Dependency import test failed' }
Ok 'Dependencies installed'

if ($SkipService) {
  Ok 'Installation finished (service registration skipped per -SkipService).'
  Write-Host "`nUsage:"
  Write-Host "  $venvPy `"$InstallDir\manage_conn.py`" add"
  Write-Host "  $venvPy `"$InstallDir\server.py`""
  exit 0
}

# --- 4) NSSM service ---
if (-not $NssmPath) {
  $candidates = @('D:\util\nssm.exe', 'C:\util\nssm.exe', 'C:\Program Files\nssm\nssm.exe', 'C:\ProgramData\chocolatey\bin\nssm.exe')
  foreach ($c in $candidates) { if (Test-Path $c) { $NssmPath = $c; break } }
  if (-not $NssmPath) {
    $cmd = Get-Command nssm -ErrorAction SilentlyContinue
    if ($cmd) { $NssmPath = $cmd.Source }
  }
}
if (-not (Test-Path $NssmPath)) {
  Fail "nssm.exe not found. Pass -NssmPath or install NSSM (https://nssm.cc/download)."
}
Ok "Using NSSM at $NssmPath"

# Tear down any prior copy of the service
& $NssmPath stop   $ServiceName 2>$null | Out-Null
& $NssmPath remove $ServiceName confirm 2>$null | Out-Null

& $NssmPath install $ServiceName $venvPy (Join-Path $InstallDir 'server.py') | Out-Null
& $NssmPath set $ServiceName AppDirectory $InstallDir | Out-Null
& $NssmPath set $ServiceName Start SERVICE_AUTO_START | Out-Null
& $NssmPath set $ServiceName AppEnvironmentExtra `
    "MCP_SQL_HOST=$BindHost" `
    "MCP_SQL_PORT=$Port" `
    "MCP_SQL_CONFIG=$InstallDir\connections.json" `
    "MCP_SQL_LOG=$InstallDir\service.log" `
  | Out-Null
& $NssmPath set $ServiceName AppStdout (Join-Path $InstallDir 'service.out.log') | Out-Null
& $NssmPath set $ServiceName AppStderr (Join-Path $InstallDir 'service.err.log') | Out-Null
& $NssmPath set $ServiceName AppRotateFiles 1 | Out-Null
& $NssmPath set $ServiceName AppRotateBytes 5242880 | Out-Null
& $NssmPath set $ServiceName Description 'MCP SQL Broker - alias-based MSSQL connection broker over HTTP/JSON-RPC' | Out-Null

if ($ServiceUser) {
  if (-not $ServicePassword) { Fail 'ServiceUser requires ServicePassword' }
  & $NssmPath set $ServiceName ObjectName $ServiceUser $ServicePassword | Out-Null
  Info "Service will run as $ServiceUser"
}

& $NssmPath start $ServiceName | Out-Null
Start-Sleep -Seconds 2
$status = (& $NssmPath status $ServiceName).Trim()
Ok "Service '$ServiceName' status: $status"

# --- 5) Health check ---
try {
  $r = Invoke-WebRequest -Uri "http://${BindHost}:${Port}/health" -TimeoutSec 5 -UseBasicParsing
  if ($r.StatusCode -eq 200) { Ok "Health check passed: $($r.Content)" }
} catch {
  Warn "Health check failed (service may need a moment to start): $_"
  Warn "Check $InstallDir\service.err.log"
}

# --- 6) Next steps ---
Write-Host ''
Write-Host 'Next steps:' -ForegroundColor Yellow
Write-Host "  1) Add a connection alias:"
Write-Host "       cd $InstallDir"
Write-Host "       .\.venv\Scripts\python.exe manage_conn.py add"
Write-Host ''
Write-Host "  2) Wire up Claude Code MCP config (~\.claude.json or workspace settings):"
Write-Host '       "mcpServers": {'
Write-Host "         `"sqlbroker`": { `"url`": `"http://${BindHost}:${Port}/mcp`" }"
Write-Host '       }'
Write-Host ''
Write-Host "  3) Test:"
Write-Host "       .\.venv\Scripts\python.exe manage_conn.py test <alias>"
