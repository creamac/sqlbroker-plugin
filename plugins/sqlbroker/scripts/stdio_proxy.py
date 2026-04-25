"""Stdio-to-HTTP proxy for the sqlbroker MCP server.

Claude Code plugin manifests only accept stdio-transport MCP servers.
The sqlbroker broker runs on HTTP at http://127.0.0.1:8765/mcp, so this
shim reads JSON-RPC requests from stdin (one per line), POSTs each to the
broker, and writes the response back to stdout.

Pure stdlib — no venv or external packages required.

Env overrides:
  MCP_SQL_BROKER_URL      — broker endpoint (default http://127.0.0.1:8765/mcp)
  MCP_SQL_BROKER_TIMEOUT  — per-request timeout seconds (default 60)
"""
import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get("MCP_SQL_BROKER_URL", "http://127.0.0.1:8765/mcp")
TIMEOUT = float(os.environ.get("MCP_SQL_BROKER_TIMEOUT", "60"))


def _err(rid, msg, code=-32000):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}}


def _id_from(line):
    try:
        return json.loads(line).get("id")
    except Exception:
        return None


def _write(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = urllib.request.Request(
                URL,
                data=line.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = resp.read().decode("utf-8")
            sys.stdout.write(body)
            if not body.endswith("\n"):
                sys.stdout.write("\n")
            sys.stdout.flush()
        except urllib.error.URLError as e:
            _write(_err(_id_from(line), f"sqlbroker unreachable at {URL}: {e}"))
        except Exception as e:
            _write(_err(_id_from(line), f"{type(e).__name__}: {e}"))


if __name__ == "__main__":
    main()
