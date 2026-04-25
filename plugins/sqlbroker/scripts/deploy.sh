#!/usr/bin/env bash
# One-shot installer for MCP SQL Broker on Linux and macOS.
#
# Will:
#   1. Verify python3 is on PATH (asks user to install if missing).
#   2. Create a venv at $INSTALL_DIR/.venv and install pyodbc + keyring.
#   3. Hint at ODBC Driver 18 install if no driver is present.
#   4. Register a service:
#        Linux  -> systemd unit at /etc/systemd/system/mcp-sqlbroker.service
#        macOS  -> launchd plist at /Library/LaunchDaemons/com.creamac.mcp-sqlbroker.plist
#   5. Start it and health-check http://127.0.0.1:8765/health.
#
# Run with sudo (needed to install system services).

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/mcp-sqlbroker}"
PORT="${PORT:-8765}"
BIND_HOST="${BIND_HOST:-127.0.0.1}"
SERVICE_NAME="${SERVICE_NAME:-mcp-sqlbroker}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Flag parsing — checked at relevant steps below
AUTO_WIRE=0
SKIP_MCP_WIRE=0
REFRESH_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --auto-wire)     AUTO_WIRE=1 ;;
    --skip-mcp-wire) SKIP_MCP_WIRE=1 ;;
    --refresh-only)  REFRESH_ONLY=1 ;;
  esac
done

ok()   { printf '\033[32m[+]\033[0m %s\n' "$*"; }
info() { printf '\033[36m[*]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[!]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[31m[X]\033[0m %s\n' "$*" >&2; exit 1; }

OS="$(uname -s)"
case "$OS" in
  Linux|Darwin) ;;
  *) fail "Unsupported OS: $OS" ;;
esac

# 0) Root check (only if registering a service)
if [[ "${1:-}" != "--skip-service" ]] && [[ "$EUID" -ne 0 ]]; then
  fail "Run with sudo. Service registration needs root."
fi

# 1) Python
PY="$(command -v python3 || true)"
if [[ -z "$PY" ]]; then
  if [[ "$OS" == "Darwin" ]]; then
    fail "python3 not found. Install via: brew install python@3.13  (or python.org)"
  else
    fail "python3 not found. Install via: apt-get install -y python3 python3-venv  (or your distro's equivalent)"
  fi
fi
PY_VER="$("$PY" -c 'import sys; print("%d.%d"%sys.version_info[:2])')"
ok "python3 $PY_VER at $PY"

# 2) Install dir + copy source
mkdir -p "$INSTALL_DIR"
for f in server.py manage_conn.py stdio_proxy.py run_stdio_proxy.sh README.md; do
  src="$SCRIPT_DIR/$f"
  if [[ -f "$src" ]]; then
    cp "$src" "$INSTALL_DIR/"
  fi
done
chmod +x "$INSTALL_DIR/run_stdio_proxy.sh" 2>/dev/null || true
ok "Files copied to $INSTALL_DIR"

# Refresh-only mode: skip venv/deps/service registration, just bounce service
if [[ "$REFRESH_ONLY" -eq 1 ]]; then
  info "--refresh-only: skipping venv/deps/service registration"
  # Pre-flight: confirm the venv is still present
  if [[ ! -x "$INSTALL_DIR/.venv/bin/python3" ]]; then
    fail "venv missing at $INSTALL_DIR/.venv. --refresh-only cannot rebuild it. Re-run deploy.sh without --refresh-only first."
  fi
  if [[ "$OS" == "Linux" ]]; then
    systemctl restart "$SERVICE_NAME" || fail "systemctl restart failed"
  elif [[ "$OS" == "Darwin" ]]; then
    launchctl unload  "/Library/LaunchDaemons/com.creamac.${SERVICE_NAME}.plist" 2>/dev/null || true
    launchctl load    "/Library/LaunchDaemons/com.creamac.${SERVICE_NAME}.plist"
  fi
  sleep 2
  if curl -fsS --max-time 5 "http://${BIND_HOST}:${PORT}/health" >/dev/null 2>&1; then
    ok "Refresh complete; service is healthy."
  else
    fail "Health check failed after refresh. Tail $INSTALL_DIR/service.log"
  fi
  exit 0
fi

# 3) venv + deps
VENV="$INSTALL_DIR/.venv"
VENV_PY="$VENV/bin/python3"
if [[ ! -x "$VENV_PY" ]]; then
  info "Creating venv at $VENV"
  "$PY" -m venv "$VENV"
fi
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet pyodbc pycryptodome
"$VENV_PY" -c "import pyodbc; from Crypto.Cipher import AES; print('deps OK')"
ok "pyodbc and pycryptodome ready"

# Detect legacy aliases without password_enc (v2.0-2.2) and add keyring for migration
CFG="$INSTALL_DIR/connections.json"
if [[ -f "$CFG" ]] && "$VENV_PY" -c "
import json,sys
cfg=json.load(open(sys.argv[1]))
need = any('password_enc' not in c and 'password_dpapi' not in c
           for c in cfg.get('connections', {}).values())
sys.exit(0 if need else 1)
" "$CFG" 2>/dev/null; then
  info 'Detected legacy keyring aliases - installing keyring for one-time migration'
  "$VENV_PY" -m pip install --quiet keyring
fi

# 4) ODBC driver hint
DRIVERS="$("$VENV_PY" -c 'import pyodbc; print("|".join(pyodbc.drivers()))' || true)"
if [[ "$DRIVERS" != *"ODBC Driver 1"* ]]; then
  if [[ "$OS" == "Darwin" ]]; then
    warn "No ODBC driver detected. Install ODBC Driver 18 for SQL Server:"
    warn "  brew tap microsoft/mssql-release"
    warn "  brew install msodbcsql18 mssql-tools18"
  else
    warn "No ODBC driver detected. Install ODBC Driver 18 for SQL Server:"
    warn "  https://learn.microsoft.com/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server"
  fi
else
  ok "ODBC drivers detected: $DRIVERS"
fi

if [[ "${1:-}" == "--skip-service" ]]; then
  ok "Installation finished (service registration skipped)."
  echo "Manual usage: $VENV_PY $INSTALL_DIR/manage_conn.py add"
  exit 0
fi

# 5) Service registration
if [[ "$OS" == "Linux" ]]; then
  UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
  cat > "$UNIT_PATH" <<EOF
[Unit]
Description=MCP SQL Broker - alias-based MSSQL connection broker
After=network.target

[Service]
Type=simple
ExecStart=${VENV_PY} ${INSTALL_DIR}/server.py
WorkingDirectory=${INSTALL_DIR}
Environment=MCP_SQL_HOST=${BIND_HOST}
Environment=MCP_SQL_PORT=${PORT}
Environment=MCP_SQL_CONFIG=${INSTALL_DIR}/connections.json
Environment=MCP_SQL_LOG=${INSTALL_DIR}/service.log
Restart=on-failure
RestartSec=5
User=root
Group=root

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
  ok "systemd unit registered at $UNIT_PATH"
  systemctl --no-pager --lines 5 status "$SERVICE_NAME" || true

elif [[ "$OS" == "Darwin" ]]; then
  PLIST_PATH="/Library/LaunchDaemons/com.creamac.${SERVICE_NAME}.plist"
  cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.creamac.${SERVICE_NAME}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${VENV_PY}</string>
    <string>${INSTALL_DIR}/server.py</string>
  </array>
  <key>WorkingDirectory</key><string>${INSTALL_DIR}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>MCP_SQL_HOST</key><string>${BIND_HOST}</string>
    <key>MCP_SQL_PORT</key><string>${PORT}</string>
    <key>MCP_SQL_CONFIG</key><string>${INSTALL_DIR}/connections.json</string>
    <key>MCP_SQL_LOG</key><string>${INSTALL_DIR}/service.log</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${INSTALL_DIR}/service.out.log</string>
  <key>StandardErrorPath</key><string>${INSTALL_DIR}/service.err.log</string>
</dict>
</plist>
EOF
  chown root:wheel "$PLIST_PATH"
  chmod 644 "$PLIST_PATH"
  launchctl unload "$PLIST_PATH" 2>/dev/null || true
  launchctl load "$PLIST_PATH"
  ok "launchd plist registered at $PLIST_PATH"
fi

# 6) Health check
sleep 2
ok_count=0
for i in 1 2 3 4 5; do
  if curl -fsS --max-time 3 "http://${BIND_HOST}:${PORT}/health" >/dev/null 2>&1; then
    body="$(curl -fsS "http://${BIND_HOST}:${PORT}/health")"
    ok "Health check passed: $body"
    ok_count=1
    break
  fi
  sleep 1
done
[[ $ok_count -eq 0 ]] && warn "Health check failed; tail $INSTALL_DIR/service.log"

# 7) MCP wiring (interactive consent before touching ~/.claude.json)
WRAPPER_SH="$INSTALL_DIR/run_stdio_proxy.sh"

# When run under sudo, $HOME may be /root. Look up the calling user's
# REAL home directory portably (admin-renamed homes / non-default paths).
TARGET_HOME=""
if [[ -n "${SUDO_USER:-}" ]]; then
  if [[ "$OS" == "Darwin" ]]; then
    TARGET_HOME="$(dscl . -read "/Users/$SUDO_USER" NFSHomeDirectory 2>/dev/null \
      | awk '/^NFSHomeDirectory:/ {print $2}')"
  else
    TARGET_HOME="$(getent passwd "$SUDO_USER" 2>/dev/null | cut -d: -f6)"
  fi
fi
[[ -z "$TARGET_HOME" ]] && TARGET_HOME="$HOME"
CLAUDE_JSON="$TARGET_HOME/.claude.json"

echo
if [[ "$SKIP_MCP_WIRE" -eq 1 ]]; then
  ANS="n"
elif [[ "$AUTO_WIRE" -eq 1 ]]; then
  info "--auto-wire: writing MCP entry to $CLAUDE_JSON without prompt"
  ANS="y"
else
  read -r -p "Add the sqlbroker MCP entry to $CLAUDE_JSON now? (Y/n) " ANS
fi
if [[ -z "$ANS" || "$ANS" =~ ^[Yy]$ || "$ANS" =~ ^[Yy][Ee][Ss]$ ]]; then
  if [[ -f "$CLAUDE_JSON" ]]; then
    cp "$CLAUDE_JSON" "$CLAUDE_JSON.bak.$(date +%Y%m%d%H%M%S)"
  else
    echo '{}' > "$CLAUDE_JSON"
  fi
  # Use the venv python (has json stdlib; doesn't need extra deps)
  WRAPPER_SH="$WRAPPER_SH" CLAUDE_JSON="$CLAUDE_JSON" "$VENV_PY" - <<'PY'
import json, os
p = os.environ["CLAUDE_JSON"]
wrapper = os.environ["WRAPPER_SH"]
with open(p, "r", encoding="utf-8") as f:
    obj = json.load(f)
if not isinstance(obj.get("mcpServers"), dict):
    obj["mcpServers"] = {}
obj["mcpServers"]["sqlbroker"] = {"command": wrapper, "args": []}
with open(p, "w", encoding="utf-8") as f:
    json.dump(obj, f, ensure_ascii=False, indent=2)
print(f"Wrote MCP entry 'sqlbroker' to {p}")
PY
  # Restore ownership if we ran as sudo
  if [[ -n "${SUDO_USER:-}" ]]; then
    chown "$SUDO_USER" "$CLAUDE_JSON" 2>/dev/null || true
  fi
  ok "Run /reload-plugins in Claude Code (or restart it)"
else
  cat <<EOF

Skipped. Paste this under "mcpServers" in $CLAUDE_JSON yourself:

  "sqlbroker": {
    "command": "$WRAPPER_SH",
    "args": []
  }

EOF
fi

cat <<EOF

Done. Add a connection from Claude Code:
  /sqlbroker:add <alias>

Or run the CLI directly:
  $VENV_PY $INSTALL_DIR/manage_conn.py add
EOF
