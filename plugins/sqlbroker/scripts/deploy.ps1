<#
.SYNOPSIS
  One-shot installer for MCP SQL Broker on Windows.

.DESCRIPTION
  Self-contained, no prerequisites beyond Windows + admin shell. Will:
   1. Download Python 3.13 embeddable distribution (no admin Python install needed)
   2. Bootstrap pip, install pyodbc + pywin32 wheels from PyPI
   3. Auto-install ODBC Driver 18 for SQL Server if missing
   4. Auto-download NSSM if missing
   5. Copy server files, register and start the Windows service
   6. Health-check the HTTP endpoint

.PARAMETER InstallDir
  Target directory. Default: D:\util\mcp-sqlbroker

.PARAMETER NssmPath
  Path to nssm.exe. If empty, common locations are searched, then auto-downloaded.

.PARAMETER Port
  Port for the HTTP MCP endpoint. Default: 8765

.PARAMETER BindHost
  Bind address. Default: 127.0.0.1 (localhost only).

.PARAMETER ServiceName
  NSSM service name. Default: mcp-sqlbroker

.PARAMETER SkipOdbc
  Skip the ODBC Driver 18 auto-install step.

.PARAMETER SkipService
  Install files only; do not register the Windows service.

.EXAMPLE
  .\deploy.ps1
  .\deploy.ps1 -InstallDir 'C:\apps\mcp-sqlbroker' -Port 9000
#>
[CmdletBinding()]
param(
  [string]$InstallDir   = 'D:\util\mcp-sqlbroker',
  [string]$NssmPath     = '',
  [int]   $Port         = 8765,
  [string]$BindHost     = '127.0.0.1',
  [string]$ServiceName  = 'mcp-sqlbroker',
  [string]$ServiceUser  = '',
  [string]$ServicePassword = '',
  [switch]$SkipOdbc,
  [switch]$SkipService
)

$ErrorActionPreference = 'Stop'

function Info($m) { Write-Host "[*] $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[+] $m" -ForegroundColor Green }
function Warn($m) { Write-Warning $m }
function Fail($m) { Write-Host "[X] $m" -ForegroundColor Red; exit 1 }

# --- 0) Admin check ---
$current = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal $current).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin -and -not $SkipService) {
  Fail 'Run this script in an Administrator PowerShell (needed for NSSM service registration and ODBC install).'
}

# --- 1) Install dir + copy source files ---
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$srcFiles = @('server.py', 'manage_conn.py', 'README.md')
foreach ($f in $srcFiles) {
  $src = Join-Path $here $f
  if (Test-Path $src) {
    Copy-Item $src -Destination $InstallDir -Force
  } elseif ($f -ne 'README.md') {
    Fail "Required source file '$f' missing next to deploy.ps1"
  }
}
Ok "Files copied to $InstallDir"

# --- 2) Embedded Python ---
$pyDir       = Join-Path $InstallDir 'python313'
$pyExe       = Join-Path $pyDir 'python.exe'
$PythonVersion = '3.13.3'
$PythonZipUrl  = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"

if (-not (Test-Path $pyExe)) {
  Info "Downloading Python $PythonVersion embedded distribution"
  $zip = Join-Path $env:TEMP "python-$PythonVersion-embed.zip"
  try {
    Invoke-WebRequest -Uri $PythonZipUrl -OutFile $zip -UseBasicParsing
  } catch { Fail "Python embed download failed: $_" }

  if (Test-Path $pyDir) { Remove-Item -Recurse -Force $pyDir }
  Expand-Archive -Path $zip -DestinationPath $pyDir -Force
  Remove-Item -Force $zip

  # Patch python313._pth to enable site-packages
  $pth = Get-ChildItem $pyDir -Filter 'python*._pth' | Select-Object -First 1
  if ($pth) {
    $content = Get-Content $pth.FullName
    $patched = $content | ForEach-Object {
      if ($_ -match '^\s*#\s*import site\s*$') { 'import site' } else { $_ }
    }
    if ($patched -notcontains 'import site') { $patched += 'import site' }
    $patched | Set-Content $pth.FullName -Encoding ASCII
  }

  Info 'Bootstrapping pip'
  $getPip = Join-Path $env:TEMP 'get-pip.py'
  Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile $getPip -UseBasicParsing
  & $pyExe $getPip --no-warn-script-location 2>&1 | Out-Null
  Remove-Item -Force $getPip
  Ok "Embedded Python ready at $pyExe"
} else {
  Ok "Embedded Python already at $pyExe"
}

# Install / refresh deps
Info 'Installing pyodbc, keyring'
& $pyExe -m pip install --quiet --no-warn-script-location --upgrade pyodbc keyring
& $pyExe -c "import pyodbc, keyring; print('deps OK')"
if ($LASTEXITCODE -ne 0) { Fail 'Dependency import test failed' }
Ok 'pyodbc and keyring ready'

# Detect legacy v1 aliases (password_dpapi) and install pywin32 for one-time
# migration to OS keyring on first server start.
$cfgPath = Join-Path $InstallDir 'connections.json'
if (Test-Path $cfgPath) {
  $needLegacy = $false
  try {
    $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
    foreach ($k in $cfg.connections.PSObject.Properties.Name) {
      if ($cfg.connections.$k.password_dpapi) { $needLegacy = $true; break }
    }
  } catch {}
  if ($needLegacy) {
    Info 'Detected legacy DPAPI aliases — installing pywin32 for one-time migration'
    & $pyExe -m pip install --quiet --no-warn-script-location pywin32
  }
}

# --- 3) ODBC Driver 18 ---
if (-not $SkipOdbc) {
  $drivers = & $pyExe -c "import pyodbc; print('|'.join(pyodbc.drivers()))"
  if ($drivers -notmatch 'ODBC Driver 1[78] for SQL Server') {
    Info 'Downloading ODBC Driver 18 for SQL Server'
    $odbcUrl = 'https://go.microsoft.com/fwlink/?linkid=2280794'   # MSI redirect for ODBC 18.4
    $odbcMsi = Join-Path $env:TEMP 'msodbcsql18.msi'
    try {
      Invoke-WebRequest -Uri $odbcUrl -OutFile $odbcMsi -UseBasicParsing
      Info 'Installing ODBC Driver 18 silently (admin)'
      $p = Start-Process msiexec.exe -ArgumentList "/i `"$odbcMsi`" /qn IACCEPTMSODBCSQLLICENSETERMS=YES" -Wait -PassThru
      Remove-Item -Force $odbcMsi -ErrorAction SilentlyContinue
      if ($p.ExitCode -eq 0) {
        Ok 'ODBC Driver 18 installed'
      } else {
        Warn "ODBC installer returned exit code $($p.ExitCode); pyodbc connections may fail until a driver is installed."
      }
    } catch {
      Warn "ODBC auto-install failed: $_. Install manually from learn.microsoft.com/sql/connect/odbc"
    }
  } else {
    Ok "ODBC driver detected: $drivers"
  }
} else {
  Info 'Skipping ODBC auto-install per -SkipOdbc'
}

if ($SkipService) {
  Ok 'Installation finished (service registration skipped per -SkipService).'
  Write-Host ''
  Write-Host 'Manual usage:'
  Write-Host "  $pyExe `"$InstallDir\manage_conn.py`" add"
  Write-Host "  $pyExe `"$InstallDir\server.py`""
  exit 0
}

# --- 4) NSSM service ---
if (-not $NssmPath) {
  $candidates = @(
    (Join-Path $InstallDir 'nssm.exe'),
    'D:\util\nssm.exe',
    'C:\util\nssm.exe',
    'C:\Program Files\nssm\nssm.exe',
    'C:\ProgramData\chocolatey\bin\nssm.exe'
  )
  foreach ($c in $candidates) { if (Test-Path $c) { $NssmPath = $c; break } }
  if (-not $NssmPath) {
    $cmd = Get-Command nssm -ErrorAction SilentlyContinue
    if ($cmd) { $NssmPath = $cmd.Source }
  }
}
if (-not (Test-Path $NssmPath)) {
  $bundled = Join-Path $InstallDir 'nssm.exe'
  Info 'NSSM not found, downloading nssm-2.24 from nssm.cc'
  $tmpZip = Join-Path $env:TEMP 'nssm-2.24.zip'
  $tmpDir = Join-Path $env:TEMP 'nssm-2.24-extract'
  try {
    Invoke-WebRequest -Uri 'https://nssm.cc/release/nssm-2.24.zip' -OutFile $tmpZip -UseBasicParsing
    if (Test-Path $tmpDir) { Remove-Item -Recurse -Force $tmpDir }
    Expand-Archive -Path $tmpZip -DestinationPath $tmpDir -Force
    $arch = if ([Environment]::Is64BitOperatingSystem) { 'win64' } else { 'win32' }
    $src = Get-ChildItem -Path $tmpDir -Recurse -Filter 'nssm.exe' |
           Where-Object { $_.FullName -match "\\$arch\\" } |
           Select-Object -First 1
    if (-not $src) { Fail 'Could not locate nssm.exe inside the downloaded archive' }
    Copy-Item $src.FullName $bundled -Force
    Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
    Remove-Item -Force $tmpZip -ErrorAction SilentlyContinue
    $NssmPath = $bundled
    Ok "NSSM bundled at $bundled"
  } catch {
    Fail "NSSM download failed: $_. Install manually from https://nssm.cc/download and rerun with -NssmPath."
  }
}
Ok "Using NSSM at $NssmPath"

# Tear down any prior copy of the service (ignore stderr noise)
$ErrorActionPreference = 'Continue'
& $NssmPath stop   $ServiceName 2>&1 | Out-Null
& $NssmPath remove $ServiceName confirm 2>&1 | Out-Null
$ErrorActionPreference = 'Stop'

& $NssmPath install $ServiceName $pyExe (Join-Path $InstallDir 'server.py') | Out-Null
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

$ErrorActionPreference = 'Continue'
& $NssmPath reset $ServiceName Throttle 2>&1 | Out-Null
& $NssmPath start $ServiceName 2>&1 | Out-Null
$ErrorActionPreference = 'Stop'

Start-Sleep -Seconds 2
$status = (& $NssmPath status $ServiceName 2>&1 | Out-String).Trim()
Ok "Service '$ServiceName' status: $status"

# --- 5) Health check ---
$ok = $false
for ($i = 0; $i -lt 5; $i++) {
  try {
    $r = Invoke-WebRequest -Uri "http://${BindHost}:${Port}/health" -TimeoutSec 3 -UseBasicParsing
    if ($r.StatusCode -eq 200) { Ok "Health check passed: $($r.Content)"; $ok = $true; break }
  } catch { Start-Sleep -Seconds 1 }
}
if (-not $ok) {
  Warn "Health check failed. Tail $InstallDir\service.err.log"
}

# --- 6) Next steps ---
Write-Host ''
Write-Host 'Done.' -ForegroundColor Yellow
Write-Host '  Add a connection from Claude Code:'
Write-Host '    /sqlbroker:add <alias>'
Write-Host ''
Write-Host '  Or run the CLI directly:'
Write-Host "    $pyExe `"$InstallDir\manage_conn.py`" add"
