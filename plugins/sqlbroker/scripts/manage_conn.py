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
    user = args.user or input("user: ").strip()
    pwd = args.password if args.password is not None else getpass.getpass("password: ")
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
    driver = args.driver or "ODBC Driver 17 for SQL Server"

    store_password(alias, pwd)
    cfg["connections"][alias] = {
        "host": host,
        "user": user,
        "default_database": db,
        "policy": policy,
        "driver": driver,
    }
    save(cfg)
    print(f"Added alias '{alias}' (host={host}, user={user}, policy={policy}); "
          f"password saved to OS keyring")


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
    a.add_argument("--force", action="store_true")
    a.set_defaults(func=cmd_add)

    sub.add_parser("list", help="List aliases").set_defaults(func=cmd_list)

    r = sub.add_parser("remove", help="Remove an alias")
    r.add_argument("alias")
    r.set_defaults(func=cmd_remove)

    t = sub.add_parser("test", help="Test connection for an alias")
    t.add_argument("alias")
    t.add_argument("--database")
    t.set_defaults(func=cmd_test)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
