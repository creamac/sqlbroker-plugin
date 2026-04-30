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
SERVER_VERSION = "2.8.3"
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
    conn = pyodbc.connect(";".join(parts), timeout=10, autocommit=True)
    return conn, c.get("policy", "readonly")


# ---------- Connection pool (v2.5) ----------
# Reuses pyodbc.Connection objects per (alias, database) tuple. pyodbc has
# its own ODBC handle pooling on top, but a Python-level pool also avoids
# rebuilding the connection-string + ODBC manager round-trip per request.
import threading
import time
from contextlib import contextmanager
from queue import Empty, Queue

POOL_MAX_PER_KEY = int(os.environ.get("MCP_SQL_POOL_MAX", "4"))
POOL_IDLE_TTL    = int(os.environ.get("MCP_SQL_POOL_TTL", "300"))  # seconds
_pool: dict = {}
_pool_lock = threading.Lock()


def _pool_key(alias, database):
    return (alias, database or "")


def _checkout(alias, database):
    """Get a healthy pooled connection or build a new one."""
    key = _pool_key(alias, database)
    with _pool_lock:
        q = _pool.setdefault(key, Queue())
    while True:
        try:
            conn, last_used, policy = q.get_nowait()
        except Empty:
            return get_connection(alias, database)
        # Drop stale or dead connections
        if time.time() - last_used > POOL_IDLE_TTL:
            try: conn.close()
            except Exception: pass
            continue
        try:
            # Ping + reset session-level state so a previous user's
            # SET LOCK_TIMEOUT / SET TRANSACTION ISOLATION LEVEL doesn't leak
            # into the next request. Reuses the existing connection.
            cur = conn.cursor()
            cur.execute("SET LOCK_TIMEOUT 30000; SET TRANSACTION ISOLATION LEVEL READ COMMITTED; SELECT 1")
            cur.fetchall()
            cur.close()
            return conn, policy
        except Exception:
            try: conn.close()
            except Exception: pass
            continue


def _checkin(alias, database, conn, policy):
    """Return a connection to the pool, or close it if pool is full."""
    key = _pool_key(alias, database)
    q = _pool.get(key)
    if q is None or q.qsize() >= POOL_MAX_PER_KEY:
        try: conn.close()
        except Exception: pass
        return
    q.put((conn, time.time(), policy))


def invalidate_pool(alias=None):
    """Close + drop pool entries for an alias (or all if alias=None).
    Call after removing/rotating an alias (in-process only — manage_conn.py
    runs out-of-process; that's why we close stale connections at checkout
    time too)."""
    with _pool_lock:
        keys = list(_pool.keys()) if alias is None else [k for k in _pool if k[0] == alias]
        for k in keys:
            q = _pool.pop(k, None)
            if q is None:
                continue
            while True:
                try:
                    conn, _, _ = q.get_nowait()
                    try: conn.close()
                    except Exception: pass
                except Empty:
                    break


@contextmanager
def pooled_connection(alias, database):
    """Context manager: yields (conn, policy); returns conn to pool on success."""
    conn, policy = _checkout(alias, database)
    success = False
    try:
        yield conn, policy
        success = True
    finally:
        if success:
            _checkin(alias, database, conn, policy)
        else:
            try: conn.close()
            except Exception: pass


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
    with pooled_connection(alias, None) as (conn, _policy):
        cur = conn.cursor()
        cur.execute("SELECT name FROM sys.databases ORDER BY name")
        return {"databases": [r[0] for r in cur.fetchall()]}


# ---------- Schema introspection tools (v2.5) ----------
# These run canned, framework-controlled SQL against sys catalog views.
# They bypass the policy regex (queries are not user-supplied) but stay
# read-only — every query is a SELECT from a sys.* view.
_OBJECT_TYPE_MAP = {
    # short-name -> sys.objects.type values
    "proc":      ("P", "PC"),                # SQL stored proc + CLR stored proc
    "table":     ("U",),                     # user table
    "view":      ("V",),
    "function":  ("FN", "IF", "TF", "FS", "FT"),
    "trigger":   ("TR",),
    "any":       None,                       # no filter
}


def tool_list_objects(args):
    alias = args["alias"]
    with pooled_connection(alias, args.get("database")) as (conn, _):
        cur = conn.cursor()
        types = _OBJECT_TYPE_MAP.get(args.get("type", "any"), None)
        pattern = args.get("name_pattern", "%")
        params = [pattern]
        sql = (
            "SELECT s.name + '.' + o.name AS qualified_name, "
            "       o.type_desc, o.create_date, o.modify_date "
            "FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id "
            "WHERE o.name LIKE ? AND o.is_ms_shipped = 0 "
        )
        if types:
            placeholders = ",".join(["?"] * len(types))
            sql += f"AND o.type IN ({placeholders}) "
            params.extend(types)
        sql += "ORDER BY o.name"
        cur.execute(sql, params)
        rows = []
        for r in cur.fetchall():
            rows.append({
                "name": r[0],
                "type": r[1],
                "created": _coerce(r[2]),
                "modified": _coerce(r[3]),
            })
        return {"objects": rows, "count": len(rows)}


def tool_get_definition(args):
    alias = args["alias"]
    obj = args["object_name"]
    with pooled_connection(alias, args.get("database")) as (conn, _):
        cur = conn.cursor()
        # Resolve object_id, fall back to OBJECT_DEFINITION which handles schema.name
        cur.execute(
            "SELECT OBJECT_DEFINITION(OBJECT_ID(?)) AS definition, "
            "       o.type_desc "
            "FROM sys.objects o WHERE o.object_id = OBJECT_ID(?)",
            obj, obj,
        )
        row = cur.fetchone()
        if not row or row[0] is None:
            return {"object_name": obj, "definition": None, "error": "Object not found or no definition (e.g. encrypted)"}
        return {
            "object_name": obj,
            "type": row[1],
            "definition": row[0],
        }


def tool_get_table_schema(args):
    alias = args["alias"]
    table = args["table_name"]
    with pooled_connection(alias, args.get("database")) as (conn, _):
        cur = conn.cursor()
        # Columns + types + nullable + PK
        cur.execute(
            """
            SELECT
                c.name           AS column_name,
                t.name           AS type_name,
                c.max_length,
                c.precision,
                c.scale,
                c.is_nullable,
                c.is_identity,
                CASE WHEN ic.column_id IS NOT NULL THEN 1 ELSE 0 END AS is_pk,
                dc.definition    AS default_value
            FROM sys.columns c
            JOIN sys.types t      ON t.user_type_id = c.user_type_id
            LEFT JOIN sys.indexes pk
                   ON pk.object_id = c.object_id AND pk.is_primary_key = 1
            LEFT JOIN sys.index_columns ic
                   ON ic.object_id = c.object_id
                  AND ic.column_id = c.column_id
                  AND ic.index_id = pk.index_id
            LEFT JOIN sys.default_constraints dc
                   ON dc.parent_object_id = c.object_id
                  AND dc.parent_column_id = c.column_id
            WHERE c.object_id = OBJECT_ID(?)
            ORDER BY c.column_id
            """,
            table,
        )
        cols = []
        for r in cur.fetchall():
            cols.append({
                "name": r[0],
                "type": r[1],
                "max_length": r[2],
                "precision": r[3],
                "scale": r[4],
                "nullable": bool(r[5]),
                "identity": bool(r[6]),
                "primary_key": bool(r[7]),
                "default": r[8],
            })
        if not cols:
            return {"table_name": table, "error": "Table not found"}

        # Indexes (non-PK)
        cur.execute(
            """
            SELECT i.name, i.type_desc, i.is_unique,
                   STUFF((
                     SELECT ',' + c.name
                     FROM sys.index_columns ic
                     JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
                     WHERE ic.object_id = i.object_id AND ic.index_id = i.index_id
                     ORDER BY ic.key_ordinal
                     FOR XML PATH('')
                   ), 1, 1, '') AS columns
            FROM sys.indexes i
            WHERE i.object_id = OBJECT_ID(?) AND i.is_primary_key = 0 AND i.type > 0
            ORDER BY i.name
            """,
            table,
        )
        indexes = [{"name": r[0], "type": r[1], "unique": bool(r[2]), "columns": r[3]}
                   for r in cur.fetchall()]
        return {"table_name": table, "columns": cols, "indexes": indexes}


def tool_get_dependencies(args):
    alias = args["alias"]
    obj = args["object_name"]
    with pooled_connection(alias, args.get("database")) as (conn, _):
        cur = conn.cursor()
        # What this object references (uses)
        cur.execute(
            """
            SELECT DISTINCT
                CASE WHEN d.referenced_schema_name IS NOT NULL
                     THEN d.referenced_schema_name + '.' + d.referenced_entity_name
                     ELSE d.referenced_entity_name END AS name,
                ro.type_desc
            FROM sys.sql_expression_dependencies d
            LEFT JOIN sys.objects ro ON ro.object_id = d.referenced_id
            WHERE d.referencing_id = OBJECT_ID(?)
            ORDER BY name
            """,
            obj,
        )
        uses = [{"name": r[0], "type": r[1]} for r in cur.fetchall()]

        # What references this object
        cur.execute(
            """
            SELECT DISTINCT
                s.name + '.' + o.name AS name,
                o.type_desc
            FROM sys.sql_expression_dependencies d
            JOIN sys.objects o ON o.object_id = d.referencing_id
            JOIN sys.schemas s ON s.schema_id = o.schema_id
            WHERE d.referenced_id = OBJECT_ID(?)
            ORDER BY name
            """,
            obj,
        )
        used_by = [{"name": r[0], "type": r[1]} for r in cur.fetchall()]

        return {
            "object_name": obj,
            "uses": uses,
            "used_by": used_by,
        }


# ---------- Server / data tools (v2.6) ----------
_ENGINE_EDITION = {
    1: "Personal/Desktop", 2: "Standard", 3: "Enterprise", 4: "Express",
    5: "Azure SQL Database", 6: "Azure Synapse", 8: "Azure SQL Managed Instance",
    9: "Azure SQL Edge", 11: "Azure SQL Hyperscale",
}


def tool_get_server_info(args):
    alias = args["alias"]
    with pooled_connection(alias, args.get("database")) as (conn, _):
        cur = conn.cursor()
        cur.execute("""
            SELECT
                CAST(SERVERPROPERTY('ProductVersion') AS NVARCHAR(50)) AS version,
                CAST(SERVERPROPERTY('ProductLevel') AS NVARCHAR(50))   AS patch_level,
                CAST(SERVERPROPERTY('Edition') AS NVARCHAR(100))       AS edition,
                CAST(SERVERPROPERTY('EngineEdition') AS INT)           AS engine_edition,
                CAST(SERVERPROPERTY('InstanceName') AS NVARCHAR(100))  AS instance,
                CAST(SERVERPROPERTY('MachineName') AS NVARCHAR(100))   AS machine,
                CAST(SERVERPROPERTY('Collation') AS NVARCHAR(100))     AS collation,
                CAST(SERVERPROPERTY('IsClustered') AS INT)             AS is_clustered,
                CAST(SERVERPROPERTY('IsHadrEnabled') AS INT)           AS is_hadr,
                @@VERSION                                              AS version_string
        """)
        r = cur.fetchone()
        if not r:
            return {"error": "no info"}
        ver = r[0]
        major = int(ver.split(".")[0]) if ver else None
        # SQL Server major version → product year
        ver_name_map = {9: "2005", 10: "2008/2008R2", 11: "2012", 12: "2014",
                        13: "2016", 14: "2017", 15: "2019", 16: "2022"}
        # Uptime (DMV; SQL 2005+)
        uptime_seconds = None
        try:
            cur.execute("SELECT DATEDIFF(SECOND, sqlserver_start_time, GETDATE()) FROM sys.dm_os_sys_info")
            uptime_seconds = cur.fetchone()[0]
        except Exception:
            pass
        return {
            "version": ver,
            "version_major": major,
            "version_name": ver_name_map.get(major, "unknown"),
            "patch_level": r[1],
            "edition": r[2],
            "engine_edition": _ENGINE_EDITION.get(r[3], f"unknown({r[3]})"),
            "instance": r[4],
            "machine": r[5],
            "collation": r[6],
            "is_clustered": bool(r[7]),
            "is_hadr_enabled": bool(r[8]),
            "uptime_seconds": uptime_seconds,
            "version_string": (r[9].splitlines()[0] if r[9] else None),
        }


def tool_find_in_definitions(args):
    alias = args["alias"]
    search = args["search_text"]
    types = _OBJECT_TYPE_MAP.get(args.get("type", "any"), None)
    with pooled_connection(alias, args.get("database")) as (conn, _):
        cur = conn.cursor()
        params = [f"%{search}%"]
        sql = (
            "SELECT s.name + '.' + o.name AS qname, o.type_desc, "
            "       LEN(m.definition) AS definition_length "
            "FROM sys.sql_modules m "
            "JOIN sys.objects o ON o.object_id = m.object_id "
            "JOIN sys.schemas s ON s.schema_id = o.schema_id "
            "WHERE m.definition LIKE ? AND o.is_ms_shipped = 0 "
        )
        if types:
            placeholders = ",".join(["?"] * len(types))
            sql += f"AND o.type IN ({placeholders}) "
            params.extend(types)
        sql += "ORDER BY o.name"
        cur.execute(sql, params)
        rows = [{"name": r[0], "type": r[1], "definition_length": r[2]}
                for r in cur.fetchall()]
        return {"search_text": search, "matches": rows, "count": len(rows)}


def tool_preview_table(args):
    alias = args["alias"]
    table = args["table_name"]
    top_n = int(args.get("top_n", 10))
    if top_n < 1 or top_n > 1000:
        raise ValueError("top_n must be between 1 and 1000")
    with pooled_connection(alias, args.get("database")) as (conn, _):
        cur = conn.cursor()
        # Validate the object exists and is a table or view, then build a
        # safely-bracketed schema.name from sys.objects (no string concat
        # of user input into the FROM clause).
        cur.execute(
            "SELECT s.name AS schema_name, o.name AS object_name, o.type_desc "
            "FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id "
            "WHERE o.object_id = OBJECT_ID(?) "
            "  AND (OBJECTPROPERTY(o.object_id, 'IsTable') = 1 "
            "    OR OBJECTPROPERTY(o.object_id, 'IsView') = 1) ",
            table,
        )
        row = cur.fetchone()
        if not row:
            # OBJECTPROPERTY check failed — try a system-catalog fallback by
            # parsing schema.name from input (sys.* views aren't in sys.objects
            # with the usual type codes but OBJECT_ID() resolves them).
            cur.execute("SELECT OBJECT_ID(?)", table)
            oid = cur.fetchone()[0]
            if not oid:
                return {"error": f"Table or view '{table}' not found"}
            cur.execute(
                "SELECT OBJECT_SCHEMA_NAME(?), OBJECT_NAME(?)", oid, oid,
            )
            sn, on = cur.fetchone()
            if not sn or not on:
                return {"error": f"Could not resolve schema/name for '{table}'"}
            schema_name, obj_name, obj_type = sn, on, "SYSTEM_OR_CATALOG_VIEW"
        else:
            schema_name, obj_name, obj_type = row
        # Bracket-escape: ] in identifiers becomes ]]
        safe = "[{}].[{}]".format(
            schema_name.replace("]", "]]"),
            obj_name.replace("]", "]]"),
        )
        cur.execute(f"SELECT TOP ({top_n}) * FROM {safe}")
        cols = [d[0] for d in cur.description]
        rows = [{cols[i]: _coerce(r[i]) for i in range(len(cols))}
                for r in cur.fetchall()]
        return {
            "object_name": f"{schema_name}.{obj_name}",
            "type": obj_type,
            "columns": cols,
            "rows": rows,
            "count": len(rows),
        }


def tool_get_active_queries(args):
    alias = args["alias"]
    top_n = int(args.get("top_n", 50))
    with pooled_connection(alias, args.get("database")) as (conn, _):
        cur = conn.cursor()
        try:
            cur.execute(f"""
            SELECT TOP ({top_n})
                r.session_id,
                r.blocking_session_id,
                r.status,
                r.command,
                r.wait_type,
                r.wait_time,
                r.cpu_time,
                r.total_elapsed_time,
                r.reads,
                r.writes,
                r.logical_reads,
                DB_NAME(r.database_id) AS db,
                SUBSTRING(t.text, (r.statement_start_offset/2)+1,
                  CASE WHEN r.statement_end_offset = -1 THEN DATALENGTH(t.text)/2
                       ELSE (r.statement_end_offset - r.statement_start_offset)/2 + 1 END
                ) AS sql_text
            FROM sys.dm_exec_requests r
            OUTER APPLY sys.dm_exec_sql_text(r.sql_handle) t
            WHERE r.session_id <> @@SPID
              AND r.session_id > 50
            ORDER BY r.total_elapsed_time DESC
        """)
        except pyodbc.ProgrammingError as e:
            msg = str(e)
            if "VIEW SERVER STATE" in msg.upper() or "permission" in msg.lower():
                return {
                    "error": "permission_denied",
                    "message": (
                        "The alias's SQL login lacks VIEW SERVER STATE — required "
                        "for sys.dm_exec_requests / sys.dm_exec_sql_text. "
                        "Grant via:  GRANT VIEW SERVER STATE TO [<login>];  "
                        "(or use a privileged alias)."
                    ),
                    "queries": [],
                    "count": 0,
                }
            raise
        cols = [d[0] for d in cur.description]
        rows = [{cols[i]: _coerce(r[i]) for i in range(len(cols))}
                for r in cur.fetchall()]
        return {"queries": rows, "count": len(rows)}


# ---------- Schema-comparison and detail tools (v2.7) ----------
def tool_compare_definitions(args):
    """Diff the source code of an object across two aliases (or two databases)."""
    alias_a = args["alias_a"]
    alias_b = args["alias_b"]
    obj = args["object_name"]
    def_a = _fetch_definition(alias_a, args.get("database_a"), obj)
    def_b = _fetch_definition(alias_b, args.get("database_b"), obj)
    present_a, present_b = def_a is not None, def_b is not None
    if not (present_a and present_b):
        return {
            "object_name": obj,
            "alias_a": alias_a, "alias_b": alias_b,
            "definition_a_present": present_a,
            "definition_b_present": present_b,
            "error": f"Object missing on {'A' if not present_a else 'B'}",
        }
    if def_a == def_b:
        return {"match": True, "object_name": obj,
                "alias_a": alias_a, "alias_b": alias_b}
    import difflib
    # Memory cap: pre-trim each side at LINE_LIMIT before difflib so
    # multi-MB procs don't blow up the broker. Diff still useful for
    # reviewing the first few thousand lines of drift.
    LINE_LIMIT = 5000
    a_all = def_a.splitlines(keepends=True)
    b_all = def_b.splitlines(keepends=True)
    a_lines = a_all[:LINE_LIMIT]
    b_lines = b_all[:LINE_LIMIT]
    input_truncated = len(a_all) > LINE_LIMIT or len(b_all) > LINE_LIMIT
    diff = list(difflib.unified_diff(
        a_lines, b_lines,
        fromfile=alias_a, tofile=alias_b, n=3,
    ))
    # Trim very large diffs to avoid blowing the response size
    full = "".join(diff)
    truncated = False
    if len(full) > 50_000:
        full = full[:50_000] + "\n[... truncated ...]"
        truncated = True
    return {
        "match": False, "object_name": obj,
        "alias_a": alias_a, "alias_b": alias_b,
        "diff": full, "truncated": truncated,
        "input_truncated": input_truncated,
        "lines_a": len(a_all), "lines_b": len(b_all),
        "size_a": len(def_a), "size_b": len(def_b),
    }


def _fetch_definition(alias, database, obj):
    with pooled_connection(alias, database) as (conn, _):
        cur = conn.cursor()
        cur.execute("SELECT OBJECT_DEFINITION(OBJECT_ID(?))", obj)
        r = cur.fetchone()
        return r[0] if r else None


def tool_find_in_columns(args):
    """Find columns by name across all user tables and views."""
    alias = args["alias"]
    search = args["search_text"]
    with pooled_connection(alias, args.get("database")) as (conn, _):
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                s.name + '.' + o.name AS table_name,
                o.type_desc           AS object_type,
                c.name                AS column_name,
                t.name                AS type_name,
                c.is_nullable,
                c.is_identity,
                c.column_id
            FROM sys.columns c
            JOIN sys.objects o ON o.object_id = c.object_id
            JOIN sys.schemas s ON s.schema_id = o.schema_id
            JOIN sys.types t   ON t.user_type_id = c.user_type_id
            WHERE c.name LIKE ?
              AND o.is_ms_shipped = 0
              AND o.type IN ('U','V')
            ORDER BY s.name, o.name, c.column_id
            """,
            f"%{search}%",
        )
        rows = [{
            "table": r[0],
            "object_type": r[1],
            "column": r[2],
            "type": r[3],
            "nullable": bool(r[4]),
            "identity": bool(r[5]),
        } for r in cur.fetchall()]
        return {"search_text": search, "matches": rows, "count": len(rows)}


def tool_get_proc_params(args):
    """Return the parameter list (name, type, output flag, default) of a proc/function."""
    alias = args["alias"]
    obj = args["object_name"]
    with pooled_connection(alias, args.get("database")) as (conn, _):
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                p.name              AS param_name,
                t.name              AS type_name,
                p.max_length,
                p.precision,
                p.scale,
                p.is_output,
                p.has_default_value,
                p.default_value,
                p.parameter_id
            FROM sys.parameters p
            JOIN sys.types t ON t.user_type_id = p.user_type_id
            WHERE p.object_id = OBJECT_ID(?)
            ORDER BY p.parameter_id
            """,
            obj,
        )
        params = []
        return_type = None
        for r in cur.fetchall():
            entry = {
                "name": r[0] or "(return_value)",
                "type": r[1],
                "max_length": r[2],
                "precision": r[3],
                "scale": r[4],
                "is_output": bool(r[5]),
                "has_default": bool(r[6]),
                "default_value": r[7],
                "ordinal": r[8],
            }
            if r[8] == 0:
                # parameter_id 0 = return type for scalar functions
                return_type = entry
            else:
                params.append(entry)
        if not params and return_type is None:
            return {"object_name": obj, "error": "Object not found or has no parameters"}
        return {
            "object_name": obj,
            "parameters": params,
            "parameter_count": len(params),
            "return_type": return_type,
        }


def tool_execute_sql(args):
    alias = args["alias"]
    database = args.get("database")
    query = args["query"]
    max_rows = int(args.get("max_rows", MAX_ROWS_DEFAULT))
    with pooled_connection(alias, database) as (conn, policy):
        err = check_policy(policy, query)
        if err:
            raise PermissionError(err)
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
            "description": "Run T-SQL on an alias (subject to its policy).",
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
    "list_objects": {
        "spec": {
            "name": "list_objects",
            "description": "Find DB objects (procs/tables/views/functions/triggers) by LIKE pattern.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "alias":        {"type": "string"},
                    "database":     {"type": "string"},
                    "name_pattern": {"type": "string", "default": "%",
                                     "description": "SQL LIKE pattern, e.g. '%[_]approve%'"},
                    "type":         {"type": "string", "default": "any",
                                     "enum": ["proc", "table", "view", "function", "trigger", "any"]},
                },
                "required": ["alias"],
                "additionalProperties": False,
            },
        },
        "fn": tool_list_objects,
    },
    "get_definition": {
        "spec": {
            "name": "get_definition",
            "description": "Return the source CREATE statement of a proc, view, function, or trigger.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "alias":       {"type": "string"},
                    "database":    {"type": "string"},
                    "object_name": {"type": "string",
                                    "description": "Schema-qualified or bare name, e.g. 'dbo.usp_foo'"},
                },
                "required": ["alias", "object_name"],
                "additionalProperties": False,
            },
        },
        "fn": tool_get_definition,
    },
    "get_table_schema": {
        "spec": {
            "name": "get_table_schema",
            "description": "Columns (type, nullable, identity, PK, default) and indexes of a table in one call.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "alias":      {"type": "string"},
                    "database":   {"type": "string"},
                    "table_name": {"type": "string"},
                },
                "required": ["alias", "table_name"],
                "additionalProperties": False,
            },
        },
        "fn": tool_get_table_schema,
    },
    "get_dependencies": {
        "spec": {
            "name": "get_dependencies",
            "description": "Return both directions: objects this object 'uses' and objects that 'use' it.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "alias":       {"type": "string"},
                    "database":    {"type": "string"},
                    "object_name": {"type": "string"},
                },
                "required": ["alias", "object_name"],
                "additionalProperties": False,
            },
        },
        "fn": tool_get_dependencies,
    },
    "get_server_info": {
        "spec": {
            "name": "get_server_info",
            "description": "SQL Server fingerprint: version (year), edition, instance, host, collation, uptime.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "alias":    {"type": "string"},
                    "database": {"type": "string"},
                },
                "required": ["alias"],
                "additionalProperties": False,
            },
        },
        "fn": tool_get_server_info,
    },
    "find_in_definitions": {
        "spec": {
            "name": "find_in_definitions",
            "description": "Full-text grep across proc/view/function/trigger bodies.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "alias":       {"type": "string"},
                    "database":    {"type": "string"},
                    "search_text": {"type": "string", "description": "Substring to search for inside object definitions."},
                    "type":        {"type": "string", "default": "any",
                                    "enum": ["proc", "view", "function", "trigger", "any"]},
                },
                "required": ["alias", "search_text"],
                "additionalProperties": False,
            },
        },
        "fn": tool_find_in_definitions,
    },
    "preview_table": {
        "spec": {
            "name": "preview_table",
            "description": "Safe SELECT TOP n * from a table or view.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "alias":      {"type": "string"},
                    "database":   {"type": "string"},
                    "table_name": {"type": "string"},
                    "top_n":      {"type": "integer", "default": 10, "minimum": 1, "maximum": 1000},
                },
                "required": ["alias", "table_name"],
                "additionalProperties": False,
            },
        },
        "fn": tool_preview_table,
    },
    "get_active_queries": {
        "spec": {
            "name": "get_active_queries",
            "description": "Currently-running queries on the server (excludes broker + system sessions).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "alias":    {"type": "string"},
                    "database": {"type": "string"},
                    "top_n":    {"type": "integer", "default": 50, "minimum": 1, "maximum": 500},
                },
                "required": ["alias"],
                "additionalProperties": False,
            },
        },
        "fn": tool_get_active_queries,
    },
    "compare_definitions": {
        "spec": {
            "name": "compare_definitions",
            "description": "Diff CREATE statement of an object across two aliases.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "alias_a":     {"type": "string"},
                    "alias_b":     {"type": "string"},
                    "object_name": {"type": "string"},
                    "database_a":  {"type": "string"},
                    "database_b":  {"type": "string"},
                },
                "required": ["alias_a", "alias_b", "object_name"],
                "additionalProperties": False,
            },
        },
        "fn": tool_compare_definitions,
    },
    "find_in_columns": {
        "spec": {
            "name": "find_in_columns",
            "description": "Find columns by name pattern across user tables/views.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "alias":       {"type": "string"},
                    "database":    {"type": "string"},
                    "search_text": {"type": "string", "description": "Substring of the column name."},
                },
                "required": ["alias", "search_text"],
                "additionalProperties": False,
            },
        },
        "fn": tool_find_in_columns,
    },
    "get_proc_params": {
        "spec": {
            "name": "get_proc_params",
            "description": "Parameter list (name, type, output, default) of a proc/function.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "alias":       {"type": "string"},
                    "database":    {"type": "string"},
                    "object_name": {"type": "string"},
                },
                "required": ["alias", "object_name"],
                "additionalProperties": False,
            },
        },
        "fn": tool_get_proc_params,
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
            # Surface install_dir + version so skills can detect where the
            # broker is deployed without scanning common paths. Backward-compat:
            # old clients only checked `ok` and `server`.
            body = json.dumps({
                "ok": True,
                "server": "sqlbroker",
                "version": SERVER_VERSION,
                "install_dir": HERE,
            }).encode("utf-8")
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
