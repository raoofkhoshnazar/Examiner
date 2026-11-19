#!/usr/bin/env bash
# استقرار سامانهٔ آزمون واژه‌بان روی سرور ubuntu-edutech
# اجرا از ریشهٔ همین پوشه:  bash deploy/deploy.sh
set -euo pipefail

SERVER="${SERVER:-root@46.34.163.254}"
APP_DIR="/opt/vazheban-exam"
DATA_DIR="/var/lib/vazheban-exam"
SRC="$(cd "$(dirname "$0")/.." && pwd)"

echo "→ اجرای تست‌ها پیش از استقرار"
cd "$SRC"
python3 -m unittest tests.test_exam || { echo "❌ تست واحد شکست خورد؛ استقرار متوقف شد" >&2; exit 1; }
python3 tests/test_http.py || { echo "❌ تست HTTP شکست خورد؛ استقرار متوقف شد" >&2; exit 1; }
python3 tests/test_responsive.py || { echo "❌ تست رسپانسیو شکست خورد؛ استقرار متوقف شد" >&2; exit 1; }
node --check "$SRC/static/exam.js" 2>/dev/null || true

echo "→ ارسال فایل‌ها به $SERVER:$APP_DIR"
ssh "$SERVER" "mkdir -p $APP_DIR/static $DATA_DIR && chown www-data:www-data $DATA_DIR && rm -rf $APP_DIR/*.py $APP_DIR/static"
tar -czf - --exclude='data' --exclude='__pycache__' --exclude='.git' \
  --exclude='tests' --exclude='*.pyc' -C "$SRC" . \
  | ssh "$SERVER" "tar -xzf - -C $APP_DIR"

echo "→ نصب سرویس systemd"
scp -q "$SRC/deploy/vazheban-exam.service" "$SERVER:/etc/systemd/system/vazheban-exam.service"
ssh "$SERVER" "systemctl daemon-reload && systemctl enable --now vazheban-exam && systemctl restart vazheban-exam"

echo "→ پیکربندی nginx روی 8444"
scp -q "$SRC/deploy/nginx-vazheban.conf" "$SERVER:/etc/nginx/sites-available/vazheban"
ssh "$SERVER" "ln -sf /etc/nginx/sites-available/vazheban /etc/nginx/sites-enabled/vazheban && nginx -t && systemctl reload nginx"

sleep 1
echo "→ بررسی سلامت"
ssh "$SERVER" "curl -fsS http://127.0.0.1:8090/health && echo && systemctl --no-pager --lines=5 status vazheban-exam | head -12"
echo
echo "✅ آماده: https://46-34-163-254.sslip.io:8444/"
