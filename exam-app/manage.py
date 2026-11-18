# -*- coding: utf-8 -*-
"""ساخت/بازنشانی کاربران آزمون.

نمونه:
    python3 manage.py create-users --participants 3 --prefix sup
    python3 manage.py reset-password <username>
    python3 manage.py list
"""
import argparse
import os
import secrets
import sys

import db

FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def random_password(length=10):
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def cmd_create_users(args):
    db.init_db()
    conn = db.connect()
    created = []
    for i in range(1, args.participants + 1):
        username = f"{args.prefix}{i:02d}"
        if db.get_user_by_username(conn, username):
            continue
        pw = random_password()
        db.create_user(conn, username, f"کارشناس پشتیبانی {i:02d}".translate(FA), pw, "participant")
        created.append((username, pw))

    if args.grader:
        existing = conn.execute("SELECT id FROM users WHERE role IN ('grader','admin') LIMIT 1").fetchone()
        if not existing:
            pw = args.grader_password or random_password(12)
            db.create_user(conn, args.grader, "مصحح آزمون", pw, "grader")
            created.append((args.grader, pw))

    print("username,password,role")
    for username, pw in created:
        role = "grader" if username == args.grader else "participant"
        print(f"{username},{pw},{role}")
    if not created:
        print("# هیچ کاربر تازه‌ای ساخته نشد (همه از قبل وجود داشتند)", file=sys.stderr)
    conn.close()


def cmd_reset_password(args):
    db.init_db()
    conn = db.connect()
    row = db.get_user_by_username(conn, args.username)
    if not row:
        print(f"کاربر {args.username} پیدا نشد", file=sys.stderr)
        sys.exit(1)
    pw = args.password or random_password()
    db.set_password(conn, row["id"], pw)
    print(f"{args.username},{pw}")
    conn.close()


def cmd_list(args):
    db.init_db()
    conn = db.connect()
    rows = conn.execute("SELECT id, username, display_name, role, active FROM users ORDER BY role, username").fetchall()
    print("id,username,name,role,active")
    for r in rows:
        print(f"{r['id']},{r['username']},{r['display_name']},{r['role']},{r['active']}")
    conn.close()


def cmd_export(args):
    """خروجی اکسل/CSV نتایج برای مصحح"""
    import app
    db.init_db()
    conn = db.connect()
    rows = app.export_rows(conn) if not args.raw else app.export_raw_rows(conn)
    data = app.csv_bytes(rows)
    with open(args.out, "wb") as f:
        f.write(data)
    print(f"نوشته شد: {args.out} ({len(rows) - 1} ردیف)")
    conn.close()


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(required=True)

    cu = sub.add_parser("create-users")
    cu.add_argument("--participants", type=int, default=2)
    cu.add_argument("--prefix", default="sup")
    cu.add_argument("--grader", default="momarres")
    cu.add_argument("--grader-password", default=os.environ.get("GRADER_PASSWORD", ""))
    cu.set_defaults(func=cmd_create_users)

    rp = sub.add_parser("reset-password")
    rp.add_argument("username")
    rp.add_argument("--password", default="")
    rp.set_defaults(func=cmd_reset_password)

    ls = sub.add_parser("list")
    ls.set_defaults(func=cmd_list)

    ex = sub.add_parser("export")
    ex.add_argument("--out", default="results.csv")
    ex.add_argument("--raw", action="store_true")
    ex.set_defaults(func=cmd_export)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
