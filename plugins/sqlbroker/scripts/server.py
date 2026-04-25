"""MCP SQL Broker - HTTP MCP server with alias-based MSSQL connection broker.

Speaks JSON-RPC 2.0 over HTTP per the MCP "streamable HTTP" transport.
No FastMCP / pydantic dependency (avoids Smart App Control DLL blocks).
"""
import base64
import datetime
import decimal
import json
import logging
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

import pyodbc
import win32crypt

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("MCP_SQL_CONFIG", os.path.join(HERE, "connections.json"))
HOST = os.environ.get("MCP_SQL_HOST", "127.0.0.1")
PORT = int(os.environ.get("MCP_SQL_PORT", "8765"))
LOG_PATH = os.environ.get("MCP_SQL_LOG", os.path.join(HERE, "service.log"))
PROTOCOL_VERSION = "2024-11-05"
SERVER_VERSION = "1.0.0"
MAX_ROWS_DEFAULT = 1000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("sqlbroker")


# ---------- DPAPI ----------
CRYPTPROTECT_LOCAL_MACHINE = 0x04


def encrypt_password(plaintext: str) -> str:
    blob = win32crypt.CryptProtectData(
        plaintext.encode("utf-8"),
        "mcp-sqlbroker",
        None,
        None,
        None,
        CRYPTPROTECT_LOCAL_MACHINE,
    )
    return base64.b64encode(blob).decode("ascii")


def decrypt_password(b64: str) -> str:
    blob = base64.b64decode(b64)
    _, plaintext = win32crypt.CryptUnprotectData(
        blob, None, None, None, CRYPTPROTECT_LOCAL_MACHINE
    )
    return plaintext.decode("utf-8")


# ---------- Config ----------
def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {"connections": {}}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------- Policy ----------
_DML_DDL = (
    r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|CREATE|ALTER|GRANT|REVOKE|"
    r"BACKUP|RESTORE|BULK\s+INSERT)\b"
)
_READONLY_BLOCK = re.compile(_DML_DDL + r"|\b(EXEC|EXECUTE)\b", re.IGNORECASE)
_EXEC_ONLY_BLOCK = re.compile(_DML_DDL, re.IGNORECASE)


def _strip_sql_comments(q: str) -> str:
    q = re.sub(r"--.*?$", "", q, flags=re.MULTILINE)
    q = re.sub(r"/\*.*?\*/", "", q, flags=re.DOTALL)
    return q


def check_policy(policy: str, query: str):
    if policy == "full":
        return None
    cleaned = _strip_sql_comments(query)
    if policy == "readonly":
        m = _READONLY_BLOCK.search(cleaned)
        if m:
            return f"Policy 'readonly' blocked statement: {m.group(0).upper()}"
        return None
    if policy == "exec-only":
        m = _EXEC_ONLY_BLOCK.search(cleaned)
        if m:
            return f"Policy 'exec-only' blocked statement: {m.group(0).upper()}"
        return None
    return f"Unknown policy: {policy}"


# ---------- Connection ----------
def get_connection(alias: str, database):
    cfg = load_config()
    conns = cfg.get("connections", {})
    if alias not in conns:
        raise ValueError(
            f"Unknown alias '{alias}'. Available: {sorted(conns.keys())}"
        )
    c = conns[alias]
    pwd = decrypt_password(c["password_dpapi"])
    driver = c.get("driver", "ODBC Driver 17 for SQL Server")
    db = database or c.get("default_database", "")
    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={c['host']}",
        f"UID={c['user']}",
        f"PWD={pwd}",
        "TrustServerCertificate=yes",
        "Encrypt=no",
        "Connection Timeout=10",
    ]
    if db:
        parts.append(f"DATABASE={db}")
    return pyodbc.connect(";".join(parts), timeout=10), c.get("policy", "readonly")


def _coerce(v):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).hex()
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, (datetime.datetime, datetime.date, datetime.time)):
        return v.isoformat()
    return str(v)


# ---------- Tool implementations ----------
def tool_list_aliases(_args):
    cfg = load_config()
    rows = [
        {
            "alias": k,
            "host": v.get("host"),
            "user": v.get("user"),
            "default_database": v.get("default_database", ""),
            "policy": v.get("policy", "readonly"),
            "driver": v.get("driver", "ODBC Driver 17 for SQL Server"),
        }
        for k, v in cfg.get("connections", {}).items()
    ]
    return {"connections": rows}


def tool_list_databases(args):
    alias = args["alias"]
    conn, _policy = get_connection(alias, None)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sys.databases ORDER BY name")
        return {"databases": [r[0] for r in cur.fetchall()]}
    finally:
        conn.close()


def tool_execute_sql(args):
    alias = args["alias"]
    database = args.get("database")
    query = args["query"]
    max_rows = int(args.get("max_rows", MAX_ROWS_DEFAULT))
    conn, policy = get_connection(alias, database)
    err = check_policy(policy, query)
    if err:
        conn.close()
        raise PermissionError(err)
    try:
        cur = conn.cursor()
        cur.execute(query)
        result_sets = []
        truncated = False
        while True:
            if cur.description:
                cols = [d[0] for d in cur.description]
                rows = []
                for i, r in enumerate(cur.fetchall()):
                    if i >= max_rows:
                        truncated = True
                        break
                    rows.append({cols[j]: _coerce(r[j]) for j in range(len(cols))})
                result_sets.append(
                    {"columns": cols, "rows": rows, "row_count": len(rows)}
                )
            else:
                result_sets.append({"rows_affected": cur.rowcount})
            if not cur.nextset():
                break
        return {"result_sets": result_sets, "truncated": truncated, "policy": policy}
    finally:
        conn.close()


TOOLS = {
    "list_aliases": {
        "spec": {
            "name": "list_aliases",
            "description": "List configured DB connection aliases (no credentials returned).",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        "fn": tool_list_aliases,
    },
    "list_databases": {
        "spec": {
            "name": "list_databases",
            "description": "List databases visible to the SQL login of an alias.",
            "inputSchema": {
                "type": "object",
                "properties": {"alias": {"type": "string"}},
                "required": ["alias"],
                "additionalProperties": False,
            },
        },
        "fn": tool_list_databases,
    },
    "execute_sql": {
        "spec": {
            "name": "execute_sql",
            "description": (
                "Execute a SQL query against a configured alias. "
                "Subject to the alias's policy: readonly | full | exec-only."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "alias": {"type": "string", "description": "Connection alias."},
                    "database": {
                        "type": "string",
                        "description": "Database name. Falls back to alias default if omitted.",
                    },
                    "query": {"type": "string", "description": "T-SQL query."},
                    "max_rows": {
                        "type": "integer",
                        "default": MAX_ROWS_DEFAULT,
                        "description": "Cap rows per result set.",
                    },
                },
                "required": ["alias", "query"],
                "additionalProperties": False,
            },
        },
        "fn": tool_execute_sql,
    },
}


# ---------- JSON-RPC method handlers ----------
def handle_initialize(_params):
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "sqlbroker", "version": SERVER_VERSION},
    }


def handle_tools_list(_params):
    return {"tools": [t["spec"] for t in TOOLS.values()]}


def handle_tools_call(params):
    name = params.get("name")
    args = params.get("arguments", {}) or {}
    if name not in TOOLS:
        raise ValueError(f"Unknown tool: {name}")
    try:
        result = TOOLS[name]["fn"](args)
        return {
            "content": [
                {"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}
            ],
            "isError": False,
        }
    except Exception as e:
        log.exception("tool error: %s", name)
        return {
            "content": [{"type": "text", "text": f"Error: {type(e).__name__}: {e}"}],
            "isError": True,
        }


METHODS = {
    "initialize": handle_initialize,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
    "ping": lambda _p: {},
}


# ---------- HTTP transport ----------
class MCPHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers", "Content-Type, mcp-session-id"
        )

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/health"):
            body = b'{"ok":true,"server":"sqlbroker"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(405)
        self.end_headers()

    def do_POST(self):
        if self.path != "/mcp":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        try:
            req = json.loads(body)
        except Exception:
            self.send_response(400)
            self.end_headers()
            return
        # Batch handling
        is_batch = isinstance(req, list)
        requests = req if is_batch else [req]
        responses = []
        for r in requests:
            resp = self._dispatch(r)
            if resp is not None:
                responses.append(resp)
        if not responses:
            # All notifications
            self.send_response(202)
            self._cors()
            self.end_headers()
            return
        out = responses if is_batch else responses[0]
        body_out = json.dumps(out, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body_out)))
        self._cors()
        self.end_headers()
        self.wfile.write(body_out)

    def _dispatch(self, r):
        is_notification = "id" not in r
        method = r.get("method", "")
        params = r.get("params", {}) or {}
        try:
            handler = METHODS.get(method)
            if handler is None:
                if method.startswith("notifications/"):
                    return None  # ignore notifications silently
                if is_notification:
                    return None
                return {
                    "jsonrpc": "2.0",
                    "id": r.get("id"),
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}",
                    },
                }
            result = handler(params)
            if is_notification:
                return None
            return {"jsonrpc": "2.0", "id": r["id"], "result": result}
        except Exception as e:
            log.exception("handler error")
            if is_notification:
                return None
            return {
                "jsonrpc": "2.0",
                "id": r.get("id"),
                "error": {"code": -32000, "message": str(e)},
            }


class ThreadingHTTP(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    log.info("Starting MCP SQL Broker on http://%s:%d (config=%s)", HOST, PORT, CONFIG_PATH)
    srv = ThreadingHTTP((HOST, PORT), MCPHandler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")


if __name__ == "__main__":
    main()
