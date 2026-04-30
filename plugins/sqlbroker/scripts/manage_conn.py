"""CLI to manage MCP SQL Broker connection aliases.

Usage:
  python manage_conn.py add <alias> [--host HOST] [--user USER] [--password PWD] ...
  python manage_conn.py list
  python manage_conn.py remove <alias>
  python manage_conn.py test <alias> [--database DB]

Passwords are stored in the OS-native keyring (Windows Credential Manager,
macOS Keychain, Linux Secret Service) — they never appear in
connections.json or in this process's command line.
"""
import argparse
import getpass
import json
import os
import sys

# Embedded Python on Windows ships with `python313._pth` that disables the
# default "script's directory on sys.path" behavior, so `from server import ...`
# fails when this script is invoked by absolute path from a different cwd
# (e.g. `python.exe D:\util\mcp-sqlbroker\manage_conn.py`). Insert our own dir
# first so the import always resolves regardless of how the user invokes us.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from server import (
    CONFIG_PATH,
    delete_password,
    get_connection,
    store_password,
)


def load():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"connections": {}}


def save(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"Saved {CONFIG_PATH}")


def cmd_add(args):
    cfg = load()
    alias = args.alias or input("alias: ").strip()
    if not alias:
        sys.exit("alias is required")
    if alias in cfg["connections"] and not args.force:
        sys.exit(f"alias '{alias}' already exists. Use --force to overwrite.")

    host = args.host or input("host (e.g. 192.168.1.10\\SQLINSTANCE or db.example.com,1433): ").strip()
    auth_mode = (
        args.auth_mode
        or input("auth_mode (sql|windows|aad-spn) [sql]: ").strip()
        or "sql"
    )
    if auth_mode not in ("sql", "windows", "aad-spn"):
        sys.exit(f"Invalid auth_mode: {auth_mode}")

    user = ""
    pwd = None
    if auth_mode == "sql":
        user = args.user or input("user: ").strip()
        pwd = args.password if args.password is not None else getpass.getpass("password: ")
    elif auth_mode == "aad-spn":
        user = args.user or input("client_id (UUID of service principal): ").strip()
        pwd = (
            args.password
            if args.password is not None
            else getpass.getpass("client_secret: ")
        )
    elif auth_mode == "windows":
        # No user / password — broker uses its own Windows identity
        if args.user:
            print("Note: --user is ignored for windows auth (uses broker process identity)")
        if args.password is not None:
            print("Note: --password is ignored for windows auth")

    db = (
        args.database
        if args.database is not None
        else input("default_database (blank to skip): ").strip()
    )
    policy = (
        args.policy
        or input("policy (readonly|full|exec-only) [readonly]: ").strip()
        or "readonly"
    )
    if policy not in ("readonly", "full", "exec-only"):
        sys.exit(f"Invalid policy: {policy}")
    # Default driver: ODBC 17 for sql/windows, ODBC 18 for aad-spn (required)
    driver = args.driver or (
        "ODBC Driver 18 for SQL Server" if auth_mode == "aad-spn"
        else "ODBC Driver 17 for SQL Server"
    )

    entry = {
        "host": host,
        "auth_mode": auth_mode,
        "default_database": db,
        "policy": policy,
        "driver": driver,
    }
    if user:
        entry["user"] = user
    cfg["connections"][alias] = entry
    save(cfg)
    # store_password() does its own read-modify-write of connections.json,
    # so it MUST run after save(cfg) above — otherwise the entry-write
    # would clobber the password_enc field that store_password just added.
    if pwd is not None:
        store_password(alias, pwd)

    if auth_mode == "windows":
        print(
            f"Added alias '{alias}' (host={host}, policy={policy}, auth=windows). "
            "NOTE: the broker service must run as a Windows account that has SQL "
            "access. SYSTEM works for local SQL Server only; for cross-machine "
            "Windows Auth, run the service as a domain user via "
            "deploy.ps1 -ServiceUser/-ServicePassword."
        )
        return
    print(f"Added alias '{alias}' (host={host}, user={user}, policy={policy}, auth={auth_mode}); "
          f"password encrypted to master.key")


def cmd_list(_args):
    cfg = load()
    if not cfg["connections"]:
        print("(no connections configured)")
        return
    print(f"{'alias':25}  {'host':35}  {'user':15}  {'policy':10}  {'default_db'}")
    print("-" * 110)
    for alias, c in cfg["connections"].items():
        print(
            f"{alias:25}  {c['host']:35}  {c['user']:15}  "
            f"{c['policy']:10}  {c.get('default_database', '')}"
        )


def cmd_remove(args):
    cfg = load()
    if args.alias not in cfg["connections"]:
        sys.exit(f"alias '{args.alias}' not found")
    del cfg["connections"][args.alias]
    save(cfg)
    delete_password(args.alias)
    print(f"Removed alias '{args.alias}' (config + keyring entry)")


def cmd_test(args):
    conn, policy = get_connection(args.alias, args.database)
    try:
        cur = conn.cursor()
        cur.execute("SELECT @@SERVERNAME, DB_NAME(), SUSER_SNAME(), @@VERSION")
        row = cur.fetchone()
        print(f"OK alias='{args.alias}' policy={policy}")
        print(f"  server  : {row[0]}")
        print(f"  database: {row[1]}")
        print(f"  login   : {row[2]}")
        print(f"  version : {row[3].splitlines()[0]}")
    finally:
        conn.close()


def cmd_rotate(args):
    """Replace the password for an existing alias without touching other fields."""
    cfg = load()
    if args.alias not in cfg["connections"]:
        sys.exit(f"alias '{args.alias}' not found")
    pwd = (
        args.password
        if args.password is not None
        else getpass.getpass(f"new password for '{args.alias}': ")
    )
    if not pwd:
        sys.exit("password cannot be empty")
    store_password(args.alias, pwd)
    print(f"Rotated password for alias '{args.alias}'")


def cmd_migrate(_args):
    """Migrate v1 password_dpapi entries into the OS keyring (Windows only)."""
    cfg = load()
    pending = [a for a, c in cfg["connections"].items() if "password_dpapi" in c]
    if not pending:
        print("No legacy aliases to migrate.")
        return
    try:
        import base64
        import win32crypt
    except ImportError:
        sys.exit(
            "pywin32 is required to decrypt v1 DPAPI passwords. "
            "Install it once: `pip install pywin32`, then rerun migrate."
        )
    migrated, failed = [], []
    for alias in pending:
        c = cfg["connections"][alias]
        try:
            blob = base64.b64decode(c["password_dpapi"])
            _, plain = win32crypt.CryptUnprotectData(blob, None, None, None, 0x04)
            from server import store_password
            store_password(alias, plain.decode("utf-8"))
            del c["password_dpapi"]
            migrated.append(alias)
        except Exception as e:
            failed.append((alias, str(e)))
    save(cfg)
    print(f"Migrated {len(migrated)}/{len(pending)} alias(es): {migrated}")
    for a, e in failed:
        print(f"  FAILED: {a}: {e}")


def main():
    p = argparse.ArgumentParser(description="MCP SQL Broker connection manager")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="Add or update an alias")
    a.add_argument("alias", nargs="?")
    a.add_argument("--host")
    a.add_argument("--user")
    a.add_argument("--password")
    a.add_argument("--database")
    a.add_argument("--policy", choices=["readonly", "full", "exec-only"])
    a.add_argument("--driver")
    a.add_argument(
        "--auth-mode",
        dest="auth_mode",
        choices=["sql", "windows", "aad-spn"],
        help="Auth mode (default: sql). 'windows' = Trusted_Connection (no user/password). "
             "'aad-spn' = Azure AD service principal (user=client_id, password=client_secret).",
    )
    a.add_argument("--force", action="store_true")
    a.set_defaults(func=cmd_add)

    sub.add_parser("list", help="List aliases").set_defaults(func=cmd_list)

    r = sub.add_parser("remove", help="Remove an alias")
    r.add_argument("alias")
    r.set_defaults(func=cmd_remove)

    rot = sub.add_parser("rotate", help="Change password for an existing alias")
    rot.add_argument("alias")
    rot.add_argument("--password")
    rot.set_defaults(func=cmd_rotate)

    t = sub.add_parser("test", help="Test connection for an alias")
    t.add_argument("alias")
    t.add_argument("--database")
    t.set_defaults(func=cmd_test)

    sub.add_parser(
        "migrate",
        help="Migrate v1 password_dpapi entries into the OS keyring (Windows only)",
    ).set_defaults(func=cmd_migrate)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
