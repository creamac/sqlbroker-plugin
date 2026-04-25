@echo off
:: Locate a Python interpreter and run stdio_proxy.py.
:: Order: $MCP_SQL_BROKER_PYTHON, embedded Python in default install dirs,
:: py launcher, plain python.
setlocal
if not "%MCP_SQL_BROKER_PYTHON%"=="" (
  "%MCP_SQL_BROKER_PYTHON%" "%~dp0stdio_proxy.py" %*
  exit /b %errorlevel%
)
:: Embedded Python from deploy.ps1 (default install paths)
if exist "D:\util\mcp-sqlbroker\python313\python.exe" (
  "D:\util\mcp-sqlbroker\python313\python.exe" "%~dp0stdio_proxy.py" %*
  exit /b %errorlevel%
)
if exist "C:\util\mcp-sqlbroker\python313\python.exe" (
  "C:\util\mcp-sqlbroker\python313\python.exe" "%~dp0stdio_proxy.py" %*
  exit /b %errorlevel%
)
if exist "C:\apps\mcp-sqlbroker\python313\python.exe" (
  "C:\apps\mcp-sqlbroker\python313\python.exe" "%~dp0stdio_proxy.py" %*
  exit /b %errorlevel%
)
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 "%~dp0stdio_proxy.py" %*
  exit /b %errorlevel%
)
where python >nul 2>&1
if %errorlevel%==0 (
  python "%~dp0stdio_proxy.py" %*
  exit /b %errorlevel%
)
echo No Python interpreter found. Run /sqlbroker:install first to set up the embedded Python at D:\util\mcp-sqlbroker\python313, or set MCP_SQL_BROKER_PYTHON to a Python 3.10+ executable. 1>&2
exit /b 1
