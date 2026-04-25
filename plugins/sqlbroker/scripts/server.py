"""MCP SQL Broker - HTTP MCP server with alias-based MSSQL connection broker.

Speaks JSON-RPC 2.0 over HTTP per the MCP "streamable HTTP" transport.
Passwords are encrypted with a per-install random 256-bit key
(`master.key` next to connections.json) using AES-128-CBC + HMAC-SHA256
(Fernet wire format). Works in any process context — service-as-SYSTEM,
user shell, sudo daemon — as long as the process can read master.key.
Threat model: equivalent to v1 DPAPI LOCAL_MACHINE — anyone with code
execution on the host can decrypt; secrets cannot leave the host.
"""
import base64
import datetime
import decimal
import hashlib
import hmac
import json
import logging
import os
import re
import struct
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

import pyodbc
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("MCP_SQL_CONFIG", os.path.join(HERE, "connections.json"))
MASTER_KEY_PATH = os.environ.get("MCP_SQL_MASTER_KEY", os.path.join(HERE, "master.key"))
HOST = os.environ.get("MCP_SQL_HOST", "127.0.0.1")
PORT = int(os.environ.get("MCP_SQL_PORT", "8765"))
LOG_PATH = os.environ.get("MCP_SQL_LOG", os.path.join(HERE, "service.log"))
PROTOCOL_VERSION = "2024-11-05"
SERVER_VERSION = "2.4.0"
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


# ---------- Master key + Fernet-format encryption (pycryptodome) ----------
def _load_master_key() -> bytes:
    """Read or generate the 32-byte master key."""
    if not os.path.exists(MASTER_KEY_PATH):
        key = get_random_bytes(32)
        # Atomic create
        tmp = MASTER_KEY_PATH + ".tmp"
        with open(tmp, "wb") as f:
            f.write(key)
        os.replace(tmp, MASTER_KEY_PATH)
    with open(MASTER_KEY_PATH, "rb") as f:
        key = f.read()
    if len(key) != 32:
        raise RuntimeError(
            f"master.key at {MASTER_KEY_PATH} is {len(key)} bytes; expected 32."
        )
    return key


_MASTER_KEY: bytes | None = None


def _master_key() -> bytes:
    global _MASTER_KEY
    if _MASTER_KEY is None:
        _MASTER_KEY = _load_master_key()
    return _MASTER_KEY


def _encrypt(plaintext: str) -> str:
    """Fernet-style: 0x80 | timestamp | iv | ct | hmac. base64-url encoded."""
    key = _master_key()
    sig_key, enc_key = key[:16], key[16:]
    iv = get_random_bytes(16)
    msg = plaintext.encode("utf-8")
    pad = 16 - (len(msg) % 16)
    msg_padded = msg + bytes([pad]) * pad
    ct = AES.new(enc_key, AES.MODE_CBC, iv).encrypt(msg_padded)
    body = b"\x80" + struct.pack(">Q", int(time.time())) + iv + ct
    sig = hmac.new(sig_key, body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(body + sig).decode("ascii")


def _decrypt(token: str) -> str:
    key = _master_key()
    sig_key, enc_key = key[:16], key[16:]
    raw = base64.urlsafe_b64decode(token.encode("ascii"))
    body, sig = raw[:-32], raw[-32:]
    expect = hmac.new(sig_key, body, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expect):
        raise ValueError("master.key did not match (HMAC mismatch).")
    iv = body[9:25]
    ct = body[25:]
    pt = AES.new(enc_key, AES.MODE_CBC, iv).decrypt(ct)
    pad = pt[-1]
    return pt[:-pad].decode("utf-8")


# Public storage API used by manage_conn.py
def store_password(alias: str, password: str) -> None:
    """Encrypt and save into connections.json under the alias's password_enc field."""
    cfg = _read_config_raw()
    if alias not in cfg.get("connections", {}):
        cfg.setdefault("connections", {})[alias] = {}
    cfg["connections"][alias]["password_enc"] = _encrypt(password)
    _write_config(cfg)


def get_password(alias: str) -> str:
    cfg = _read_config_raw()
    c = cfg.get("connections", {}).get(alias)
    if not c or "password_enc" not in c:
        raise KeyError(
            f"No encrypted password for alias '{alias}'. Re-add via /sqlbroker:add."
        )
    return _decrypt(c["password_enc"])


def delete_password(alias: str) -> None:
    cfg = _read_config_raw()
    c = cfg.get("connections", {}).get(alias)
    if c and "password_enc" in c:
        del c["password_enc"]
        _write_config(cfg)


def _read_config_raw() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {"connections": {}}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_config(cfg: dict) -> None:
    """Atomic write to avoid corruption on crash mid-write."""
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


# ---------- Config + auto-migration to master.key encryption ----------
def _migrate_legacy(cfg: dict) -> bool:
    """One-shot upgrade path:
       - v1 DPAPI: 'password_dpapi' field → re-encrypt with master.key
       - v2.0-2.2 keyring: alias has no password field; pull from OS keyring
         and re-encrypt with master.key (drops the keyring entry).
       Both paths are idempotent; this runs once per stale alias."""
    changed = False
    conns = cfg.get("connections", {})

    # 1) DPAPI legacy (Windows v1 only) — needs pywin32
    dpapi_pending = [a for a, c in conns.items() if "password_dpapi" in c]
    if dpapi_pending:
        try:
            import win32crypt
        except ImportError:
            log.warning(
                "Found legacy DPAPI password fields for aliases %s but pywin32 is "
                "not installed. Re-add these aliases via /sqlbroker:add.",
                dpapi_pending,
            )
        else:
            for alias in dpapi_pending:
                c = conns[alias]
                try:
                    blob = base64.b64decode(c["password_dpapi"])
                    _, plain = win32crypt.CryptUnprotectData(blob, None, None, None, 0x04)
                    c["password_enc"] = _encrypt(plain.decode("utf-8"))
                    del c["password_dpapi"]
                    log.info("Migrated alias '%s' from DPAPI to master.key", alias)
                    changed = True
                except Exception as e:
                    log.error("DPAPI migration failed for alias '%s': %s", alias, e)

    # 2) Keyring legacy (v2.0-2.2 — passwords lived in OS keyring).
    # Skip aliases that don't need a password at all (auth_mode=windows).
    keyring_pending = [
        a for a, c in conns.items()
        if "password_enc" not in c
        and "password_dpapi" not in c
        and c.get("auth_mode", "sql") != "windows"
    ]
    if keyring_pending:
        try:
            import keyring as _kr
        except ImportError:
            log.warning(
                "Aliases %s have no password field. Re-add them via /sqlbroker:add.",
                keyring_pending,
            )
        else:
            kr_service = os.environ.get("MCP_SQL_KEYRING_SERVICE", "mcp-sqlbroker")
            for alias in keyring_pending:
                try:
                    plain = _kr.get_password(kr_service, alias)
                    if plain is None:
                        log.warning(
                            "Alias '%s' has no keyring entry either; needs re-add.",
                            alias,
                        )
                        continue
                    conns[alias]["password_enc"] = _encrypt(plain)
                    try:
                        _kr.delete_password(kr_service, alias)
                    except Exception:
                        pass
                    log.info("Migrated alias '%s' from OS keyring to master.key", alias)
                    changed = True
                except Exception as e:
                    log.error("Keyring migration failed for alias '%s': %s", alias, e)

    return changed


def load_config() -> dict:
    cfg = _read_config_raw()
    if _migrate_legacy(cfg):
        _write_config(cfg)
    return cfg


# ---------- Policy ----------
_DML_DDL = (
    r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|CREATE|ALTER|GRANT|REVOKE|"
    r"BACKUP|RESTORE|BULK\s+INSERT)\b"
)
_READONLY_BLOCK = re.compile(_DML_DDL + r"|\b(EXEC|EXECUTE)\b", re.IGNORECASE)
_EXEC_ONLY_BLOCK = re.compile(_DML_DDL, re.IGNORECASE)


def _strip_sql_comments(q: str) -> str:
    """Strip comments AND replace string-literal contents with empty so the
    policy regex doesn't see SQL keywords that happen to appear inside
    strings (e.g. SELECT '/*' AS x WHERE '*/' = 'UPDATE')."""
    # Replace 'string contents' (with '' as escaped quote) with empty quotes
    q = re.sub(r"'(?:[^']|'')*'", "''", q)
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
    auth_mode = c.get("auth_mode", "sql")
    driver = c.get("driver", "ODBC Driver 17 for SQL Server")
    db = database or c.get("default_database", "")
    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={c['host']}",
        "TrustServerCertificate=yes",
        "Encrypt=no",
        "Connection Timeout=10",
    ]
    if auth_mode == "sql":
        # Classic SQL login — username + master.key-encrypted password
        pwd = get_password(alias)
        parts += [f"UID={c['user']}", f"PWD={pwd}"]
    elif auth_mode == "windows":
        # Trusted_Connection=yes — uses the broker process's Windows identity.
        # NOTE: the broker service usually runs as SYSTEM, which works for
        # local SQL Server if the SYSTEM account has DB rights, but cannot
        # authenticate over the network. For cross-machine Windows Auth, run
        # the service as a domain account (deploy.ps1 -ServiceUser/-Password).
        parts.append("Trusted_Connection=yes")
    elif auth_mode == "aad-spn":
        # Azure AD service-principal — requires ODBC Driver 18+
        parts += [
            "Authentication=ActiveDirectoryServicePrincipal",
            f"UID={c['user']}",            # client_id (UUID)
            f"PWD={get_password(alias)}",  # client_secret
        ]
    else:
        raise ValueError(f"Unknown auth_mode '{auth_mode}' for alias '{alias}'")
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
