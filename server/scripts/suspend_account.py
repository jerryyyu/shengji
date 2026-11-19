#!/usr/bin/env python3
"""Suspend, unsuspend or show a signed-in account, by id or email.

A suspended account is refused at sign-in (Google and Apple) and its
sessions read as signed out everywhere: HTTP routes and websockets, where
the socket is told ``account_suspended`` and plays on as a guest. Ratings,
rating history and saved games are kept; unsuspending restores the account
as it was. Guests have no account and cannot be suspended. A socket already
open in the running server keeps its account until it reconnects.

On Fly (the image ships this script):

    fly ssh console -C "uv run --no-dev --project /app/server python /app/server/scripts/suspend_account.py show --email a@b.c"
    fly ssh console -C "uv run --no-dev --project /app/server python /app/server/scripts/suspend_account.py suspend --id 42"

``--db`` names another accounts database (default: the server's own,
``shengji.api.accounts.db_path()``). Exit 0 on success, 1 when no account
matches or an email matches several (pass ``--id`` then), 2 on bad usage.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.api import accounts  # noqa: E402


def _describe(row: dict) -> str:
    provider = "apple" if row.get("apple_sub") else "google"
    when = row.get("suspended_at")
    state = (f"suspended since {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime(when))}"
             if when is not None else "active")
    return (f"id={row['id']} provider={provider} email={row.get('email') or '-'} "
            f"name={accounts.effective_name(row) or '-'} rating={row.get('rating')} {state}")


def _find(store: accounts.Store, args: argparse.Namespace) -> dict | None:
    if args.id is not None:
        row = store.user(args.id)
        if row is None:
            print(f"no account with id {args.id}", file=sys.stderr)
        return row
    rows = store.users_by_email(args.email)
    if not rows:
        print(f"no account with email {args.email}", file=sys.stderr)
        return None
    if len(rows) > 1:
        print(f"{len(rows)} accounts have email {args.email}; pass --id:", file=sys.stderr)
        for row in rows:
            print("  " + _describe(row), file=sys.stderr)
        return None
    return rows[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=("suspend", "unsuspend", "show"))
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--id", type=int, help="account id (users.id)")
    who.add_argument("--email", help="account email, case-insensitive")
    parser.add_argument("--db", type=Path, help="accounts database (default: the server's)")
    args = parser.parse_args(argv)

    store = accounts.Store(args.db)
    row = _find(store, args)
    if row is None:
        return 1
    if args.action != "show":
        row = store.set_suspended(int(row["id"]), args.action == "suspend")
        if row is None:
            print("the account was deleted meanwhile", file=sys.stderr)
            return 1
    print(_describe(row))
    print(f"database: {store.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
