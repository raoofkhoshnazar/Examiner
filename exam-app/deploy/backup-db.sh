#!/usr/bin/env bash
# پشتیبان‌گیری روزانه از دیتابیس آزمون — cron: 0 3 * * * /opt/vazheban-exam/deploy/backup-db.sh
# نسخهٔ سالم و اتمیک با API پشتیبان‌گیری SQLite؛ ۱۴ نسخهٔ آخر نگه داشته می‌شود.
set -euo pipefail

DB="${DB:-/var/lib/vazheban-exam/exam.db}"
DEST="${DEST:-/var/backups/vazheban-exam}"
KEEP="${KEEP:-14}"
PY="${PY:-python3}"

mkdir -p "$DEST"
chmod 700 "$DEST"

DB="$DB" DEST="$DEST" KEEP="$KEEP" "$PY" - <<'PYEOF'
import glob, os, sqlite3, sys, time

db, dest, keep = os.environ["DB"], os.environ["DEST"], int(os.environ["KEEP"])
out = os.path.join(dest, "exam-" + time.strftime("%Y%m%d-%H%M%S") + ".db")

try:
    src, dst = sqlite3.connect(db), sqlite3.connect(out)
    with dst:
        src.backup(dst)
    src.close()
    check = dst.execute("PRAGMA integrity_check").fetchone()[0]
    dst.close()
except Exception as exc:
    print("backup failed:", exc, file=sys.stderr)
    if os.path.exists(out):
        os.remove(out)
    sys.exit(1)

if check != "ok":
    print("integrity check failed:", check, file=sys.stderr)
    os.remove(out)
    sys.exit(1)

os.chmod(out, 0o600)
old = sorted(glob.glob(os.path.join(dest, "exam-*.db")), key=os.path.getmtime, reverse=True)
for path in old[keep:]:
    os.remove(path)

size = os.path.getsize(out) / 1024
print(f"ok {out} ({size:.0f}K, {len(old[keep:])} نسخهٔ قدیمی پاک شد)")
PYEOF
