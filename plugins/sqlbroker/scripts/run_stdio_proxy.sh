#!/usr/bin/env bash
# Locate Python and launch stdio_proxy.py.
# Order: $MCP_SQL_BROKER_PYTHON, broker venv, python3 on PATH.
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -n "${MCP_SQL_BROKER_PYTHON:-}" ]]; then
  exec "$MCP_SQL_BROKER_PYTHON" "$DIR/stdio_proxy.py" "$@"
fi

# Default install locations from deploy.sh
for cand in /opt/mcp-sqlbroker/.venv/bin/python3 /usr/local/opt/mcp-sqlbroker/.venv/bin/python3; do
  if [[ -x "$cand" ]]; then
    exec "$cand" "$DIR/stdio_proxy.py" "$@"
  fi
done

if command -v python3 >/dev/null 2>&1; then
  exec python3 "$DIR/stdio_proxy.py" "$@"
fi

echo "No python3 interpreter found. Run deploy.sh first." >&2
exit 1
