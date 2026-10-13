#!/usr/bin/env python3
"""Local operator recovery; run inside the FG MTM API container."""
import argparse
import getpass
import os
import secrets
import sys

def reset_password(service, tenant, branch, username, password):
    from fg_server.contracts import identifier
    for value in (tenant, branch, username):
        identifier(value)
    if not 12 <= len(password) <= 128:
        raise ValueError("Password must contain 12–128 characters.")
    with service.connect() as db:
        account = db.execute(
            "SELECT id,enabled FROM accounts WHERE tenant=%s AND branch=%s AND username=%s FOR UPDATE",
            (tenant, branch, username),
        ).fetchone()
        if not account:
            raise ValueError("No account matches this tenant, branch and username.")
        if not account["enabled"]:
            raise ValueError("Account is disabled; password recovery does not re-enable it.")
        salt = secrets.token_bytes(16)
        verifier = service.hash_password(password, salt)
        db.execute(
            "UPDATE accounts SET salt=%s,verifier=%s,failures=0,locked_until=NULL WHERE id=%s",
            (salt, verifier, account["id"]),
        )
        db.execute("DELETE FROM sessions WHERE account=%s", (account["id"],))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("accounts", help="List account names, scopes and enabled state; no secrets.")
    reset = commands.add_parser("reset-password", help="Replace password and revoke all account sessions.")
    for option in ("tenant", "branch", "username"):
        reset.add_argument("--" + option, required=True)
    args = parser.parse_args()
    from fg_server.service import Service
    service = Service(os.environ["FG_DATABASE_URL"])
    if args.command == "accounts":
        with service.connect() as db:
            rows = db.execute("SELECT tenant,branch,username,role,enabled FROM accounts ORDER BY tenant,branch,username").fetchall()
        import json
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    password = getpass.getpass("New password (12–128 characters): ")
    if password != getpass.getpass("Repeat password: "):
        raise ValueError("Passwords differ; no change made.")
    reset_password(service, args.tenant, args.branch, args.username, password)
    print("Password changed. Previous sessions revoked. Tenant, branch, role and business data preserved.")

if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
