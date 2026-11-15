#!/usr/bin/env bash
# تثبيت البوت على VPS (Ubuntu/Debian). شغّله كـ root من داخل مجلد aqar-bot:
#   sudo bash deploy/install.sh
set -euo pipefail
APP_DIR=/opt/aqar-bot

id aqarbot >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin aqarbot
mkdir -p "$APP_DIR"
cp -r aqarbot requirements.txt "$APP_DIR"/
[ -f "$APP_DIR/.env" ] || cp .env.example "$APP_DIR/.env"

apt-get update -qq && apt-get install -y -qq python3-venv
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
"$APP_DIR/.venv/bin/playwright" install --with-deps chromium
# المتصفح ينحفظ في مجلد المستخدم اللي ثبّته، فننقله لمستخدم البوت
mkdir -p /home/aqarbot/.cache && rm -rf /home/aqarbot/.cache/ms-playwright
cp -r /root/.cache/ms-playwright /home/aqarbot/.cache/
chown -R aqarbot:aqarbot "$APP_DIR" /home/aqarbot/.cache

cp deploy/aqarbot.service /etc/systemd/system/aqarbot.service
systemctl daemon-reload
systemctl enable aqarbot

echo
echo "✅ تم التثبيت. عبّئ الإعدادات في $APP_DIR/.env ثم شغّل:"
echo "   systemctl restart aqarbot && journalctl -u aqarbot -f"
