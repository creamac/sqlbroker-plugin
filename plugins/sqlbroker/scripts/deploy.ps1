<#
.SYNOPSIS
  One-shot installer for MCP SQL Broker on Windows.

.DESCRIPTION
  Self-contained, no prerequisites beyond Windows + admin shell. Will:
   1. Download Python 3.13 embeddable distribution (no system Python needed)
   2. Bootstrap pip, install pyodbc + keyring
   3. Auto-install ODBC Driver 18 for SQL Server if missing
   4. Register a Windows Scheduled Task (`mcp-sqlbroker`) that runs the
      broker at boot as SYSTEM and auto-restarts on failure (NSSM-free).
   5. Health-check the HTTP endpoint
#>
[CmdletBinding()]
param(
  [string]$InstallDir      = 'D:\util\mcp-sqlbroker',
  [int]   $Port            = 8765,
  [string]$BindHost        = '127.0.0.1',
  [string]$ServiceName     = 'mcp-sqlbroker',
  [string]$ServiceUser     = '',
  [string]$ServicePassword = '',
  [switch]$SkipOdbc,
  [switch]$SkipService,
  [switch]$AutoWire,        # auto-yes on the ~/.claude.json wiring prompt
  [switch]$SkipMcpWire,     # don't touch ~/.claude.json at all
  [switch]$RefreshOnly      # only copy files + bounce service; skip Python/ODBC/Task setup
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
$srcFiles = @('server.py', 'manage_conn.py', 'stdio_proxy.py', 'run_stdio_proxy.bat', 'README.md')
foreach ($f in $srcFiles) {
  $src = Join-Path $here $f
  if (Test-Path $src) {
    Copy-Item $src -Destination $InstallDir -Force
  } elseif ($f -ne 'README.md') {
    Fail "Required source file '$f' missing next to deploy.ps1"
  }
}
Ok "Files copied to $InstallDir"

# Rewrite run_stdio_proxy.bat to point at THIS install's embedded Python
# (the shipped wrapper hardcodes a few default paths; we want a stable
# wrapper that always launches the right interpreter regardless of
# -InstallDir override).
$wrapperDest = Join-Path $InstallDir 'run_stdio_proxy.bat'
$pyAbs = Join-Path $InstallDir 'python313\python.exe'
$proxyAbs = Join-Path $InstallDir 'stdio_proxy.py'
@"
@echo off
"$pyAbs" "$proxyAbs" %*
"@ | Set-Content -Path $wrapperDest -Encoding ASCII

# --- Refresh-only mode: skip Python/ODBC/Task setup, just bounce the
#     existing service so it picks up the new server.py / manage_conn.py.
if ($RefreshOnly) {
  Info '-RefreshOnly: skipping Python, ODBC, and service registration'
  $existingTask = Get-ScheduledTask -TaskName $ServiceName -ErrorAction SilentlyContinue
  if (-not $existingTask) {
    Fail "No existing scheduled task '$ServiceName' to refresh. Run /sqlbroker:install first."
  }
  Stop-ScheduledTask -TaskName $ServiceName -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2
  Start-ScheduledTask -TaskName $ServiceName
  Start-Sleep -Seconds 3
  $ok = $false
  for ($i = 0; $i -lt 5; $i++) {
    try {
      $r = Invoke-WebRequest -Uri "http://${BindHost}:${Port}/health" -TimeoutSec 3 -UseBasicParsing
      if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { Start-Sleep -Seconds 1 }
  }
  if ($ok) {
    # Print broker version
    try {
      $body = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
      $resp = Invoke-RestMethod -Method Post -Uri "http://${BindHost}:${Port}/mcp" -ContentType 'application/json' -Body $body
      Ok "Broker now running version $($resp.result.serverInfo.version)"
    } catch { Ok 'Broker is running (version probe failed but health is OK)' }
  } else {
    Fail "Health check failed after refresh. Tail $InstallDir\service.err.log"
  }
  exit 0
}

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
Info 'Installing pyodbc, pycryptodome'
& $pyExe -m pip install --quiet --no-warn-script-location --upgrade pyodbc pycryptodome
& $pyExe -c "import pyodbc; from Crypto.Cipher import AES; print('deps OK')"
if ($LASTEXITCODE -ne 0) { Fail 'Dependency import test failed' }
Ok 'pyodbc and pycryptodome ready'

# Detect legacy aliases that need migration helpers:
#   - v1 (password_dpapi)        -> needs pywin32 for one-time migration
#   - v2.0-2.2 (no password_enc) -> needs keyring to migrate from OS keyring
$cfgPath = Join-Path $InstallDir 'connections.json'
if (Test-Path $cfgPath) {
  $needPywin32 = $false
  $needKeyring = $false
  try {
    $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
    foreach ($k in $cfg.connections.PSObject.Properties.Name) {
      $c = $cfg.connections.$k
      if ($c.password_dpapi) { $needPywin32 = $true }
      elseif (-not $c.password_enc) { $needKeyring = $true }
    }
  } catch {}
  if ($needPywin32) {
    Info 'Detected legacy DPAPI aliases - installing pywin32 for one-time migration'
    & $pyExe -m pip install --quiet --no-warn-script-location pywin32
  }
  if ($needKeyring) {
    Info 'Detected legacy keyring aliases - installing keyring for one-time migration'
    & $pyExe -m pip install --quiet --no-warn-script-location keyring
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

# --- 4) Windows Task Scheduler service (no NSSM needed) ---
# Migrate / clean up any previous NSSM service so we don't have two copies running
$existingNssmService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existingNssmService) {
  Info "Found legacy NSSM service '$ServiceName'; stopping and removing"
  $oldNssm = @(
    (Join-Path $InstallDir 'nssm.exe'),
    'D:\util\nssm.exe',
    'C:\util\nssm.exe',
    'C:\Program Files\nssm\nssm.exe'
  ) | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($oldNssm) {
    & $oldNssm stop   $ServiceName 2>&1 | Out-Null
    & $oldNssm remove $ServiceName confirm 2>&1 | Out-Null
  } else {
    sc.exe stop   $ServiceName 2>&1 | Out-Null
    sc.exe delete $ServiceName 2>&1 | Out-Null
  }
}

# Tear down any prior scheduled task with the same name
$existingTask = Get-ScheduledTask -TaskName $ServiceName -ErrorAction SilentlyContinue
if ($existingTask) {
  Stop-ScheduledTask -TaskName $ServiceName -ErrorAction SilentlyContinue
  Unregister-ScheduledTask -TaskName $ServiceName -Confirm:$false -ErrorAction SilentlyContinue
}

# Use a wrapper batch that exports MCP_SQL_* env vars and chains to the broker.
$wrapperBat = Join-Path $InstallDir '_run_broker.bat'
@"
@echo off
set MCP_SQL_HOST=$BindHost
set MCP_SQL_PORT=$Port
set MCP_SQL_CONFIG=$InstallDir\connections.json
set MCP_SQL_LOG=$InstallDir\service.log
"$pyExe" "$InstallDir\server.py"
"@ | Set-Content -Path $wrapperBat -Encoding ASCII

$action = New-ScheduledTaskAction -Execute $wrapperBat -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtStartup
if ($ServiceUser) {
  if (-not $ServicePassword) { Fail 'ServiceUser requires ServicePassword' }
  $principal = New-ScheduledTaskPrincipal -UserId $ServiceUser -LogonType Password -RunLevel Highest
  $regArgs = @{ User = $ServiceUser; Password = $ServicePassword }
} else {
  $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
  $regArgs = @{}
}
$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -DontStopOnIdleEnd `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -RestartCount 99 `
  -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit (New-TimeSpan -Days 0)

Register-ScheduledTask `
  -TaskName $ServiceName `
  -Description 'MCP SQL Broker - alias-based MSSQL connection broker over HTTP/JSON-RPC' `
  -Action $action `
  -Trigger $trigger `
  -Principal $principal `
  -Settings $settings `
  -Force `
  @regArgs | Out-Null

Start-ScheduledTask -TaskName $ServiceName

Start-Sleep -Seconds 2
$task = Get-ScheduledTask -TaskName $ServiceName
$info = Get-ScheduledTaskInfo -TaskName $ServiceName
Ok "Scheduled task '$ServiceName' state=$($task.State) lastRun=$($info.LastRunTime) lastResult=$($info.LastTaskResult)"

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

# --- 6) MCP wiring (interactive prompt unless -AutoWire / -SkipMcpWire) ---
$wrapperBat = Join-Path $InstallDir 'run_stdio_proxy.bat'
$claudeJson = Join-Path $env:USERPROFILE '.claude.json'

Write-Host ''
if ($SkipMcpWire) {
  $ans = 'n'
} elseif ($AutoWire) {
  Info "Auto-wiring MCP entry into $claudeJson (--AutoWire passed)"
  $ans = 'y'
} else {
  $ans = Read-Host "Add the sqlbroker MCP entry to $claudeJson now? (Y/n)"
}
if ($ans -eq '' -or $ans -match '^(y|yes)$') {
  if (Test-Path $claudeJson) {
    Copy-Item $claudeJson "$claudeJson.bak.$(Get-Date -Format yyyyMMddHHmmss)" -Force
  } else {
    Set-Content -Path $claudeJson -Value '{}' -Encoding UTF8
  }
  # Patch via Python to preserve Unicode + key order. PowerShell 5.1's
  # ConvertTo-Json escapes non-ASCII and has depth quirks.
  $env:MCP_CLAUDE_JSON = $claudeJson
  $env:MCP_WRAPPER     = $wrapperBat
  $patchSrc = @'
import json, os
p = os.environ['MCP_CLAUDE_JSON']
with open(p, 'r', encoding='utf-8') as f:
    obj = json.load(f)
if not isinstance(obj.get('mcpServers'), dict):
    obj['mcpServers'] = {}
obj['mcpServers']['sqlbroker'] = {'command': os.environ['MCP_WRAPPER'], 'args': []}
with open(p, 'w', encoding='utf-8') as f:
    json.dump(obj, f, ensure_ascii=False, indent=2)
print("Wrote MCP entry 'sqlbroker' to", p)
'@
  $patchSrc | & $pyExe -
  Remove-Item Env:\MCP_CLAUDE_JSON, Env:\MCP_WRAPPER -ErrorAction SilentlyContinue
  Ok "Wrote MCP entry 'sqlbroker' to $claudeJson (backup saved next to it)"
  Write-Host '  Then in Claude Code: /reload-plugins (or restart it)' -ForegroundColor Yellow
} else {
  Write-Host ''
  Write-Host 'Skipped. Paste this under "mcpServers" in ~\.claude.json yourself:' -ForegroundColor Yellow
  $entry = [ordered]@{ sqlbroker = [ordered]@{ command = $wrapperBat; args = @() } }
  Write-Host ($entry | ConvertTo-Json -Depth 5)
}

Write-Host ''
Write-Host 'Done.' -ForegroundColor Yellow
Write-Host '  Add a connection from Claude Code:'
Write-Host '    /sqlbroker:add <alias>'
Write-Host ''
Write-Host '  Or run the CLI directly:'
Write-Host "    $pyExe `"$InstallDir\manage_conn.py`" add"
