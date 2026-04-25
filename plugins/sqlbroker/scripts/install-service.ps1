<#
  Run this in an *Administrator* PowerShell to install/refresh the
  mcp-sqlbroker Windows service via NSSM.

  Right-click PowerShell → "Run as Administrator", then:
      cd D:\util\mcp-sqlbroker
      .\install-service.ps1
#>
param(
  [string]$NssmPath = 'D:\util\nssm.exe',
  [string]$ServiceName = 'mcp-sqlbroker',
  [string]$InstallDir = 'D:\util\mcp-sqlbroker',
  [int]   $Port = 8765,
  [string]$BindHost = '127.0.0.1'
)
$ErrorActionPreference = 'Stop'

$current = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal $current).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
  Write-Host '[X] Not running as Administrator. Right-click PowerShell -> Run as Administrator.' -ForegroundColor Red
  exit 1
}

$venvPy = Join-Path $InstallDir '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy))   { throw "venv python missing: $venvPy" }
if (-not (Test-Path $NssmPath)) { throw "nssm.exe missing: $NssmPath" }

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
& $NssmPath set $ServiceName Description 'MCP SQL Broker - alias-based MSSQL access for Claude Code' | Out-Null

& $NssmPath start $ServiceName
Start-Sleep -Seconds 2
Write-Host ''
& $NssmPath status $ServiceName

try {
  $r = Invoke-WebRequest -Uri "http://${BindHost}:${Port}/health" -TimeoutSec 5 -UseBasicParsing
  if ($r.StatusCode -eq 200) {
    Write-Host "[+] Health check OK: $($r.Content)" -ForegroundColor Green
  }
} catch {
  Write-Warning "Health check failed: $_"
  Write-Warning "Tail $InstallDir\service.err.log to debug"
}

Write-Host ''
Write-Host 'Add to Claude Code MCP config:' -ForegroundColor Yellow
Write-Host '  "mcpServers": { "sqlbroker": { "url": "http://127.0.0.1:8765/mcp" } }'
