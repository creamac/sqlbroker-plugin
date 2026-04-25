@echo off
:: Wrapper that locates a Python interpreter and runs stdio_proxy.py.
:: Order: $MCP_SQL_BROKER_PYTHON, py launcher, plain python.
setlocal
if not "%MCP_SQL_BROKER_PYTHON%"=="" (
  "%MCP_SQL_BROKER_PYTHON%" "%~dp0stdio_proxy.py" %*
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
echo No Python interpreter found. Install Python 3.10+ from python.org or set MCP_SQL_BROKER_PYTHON. 1>&2
exit /b 1
