#!/bin/bash
# Установка общей базы для Telegram Mini App «Учёт рекламы». Запускать от root.
set -e
DOMAIN="ads.marmelad-horeca.ru"
SRC="https://dodotmbot.github.io/ad-tracker"
APP=/opt/adtracker

echo "== Учёт рекламы: установка =="
read -rp "Вставьте токен бота и нажмите Enter: " BOT_TOKEN
[ -n "$BOT_TOKEN" ] || { echo "Токен пустой, запустите скрипт снова."; exit 1; }

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 nginx certbot python3-certbot-nginx curl dnsutils

mkdir -p "$APP"
curl -fsSL "$SRC/server.py?t=$(date +%s)" -o "$APP/server.py"
curl -fsSL "$SRC/index.html?t=$(date +%s)" -o "$APP/index.html"
printf 'BOT_TOKEN=%s\n' "$BOT_TOKEN" > "$APP/.env"
chmod 600 "$APP/.env"
chown -R www-data:www-data "$APP"
chown root:root "$APP/.env"

cat > /etc/systemd/system/adtracker.service <<UNIT
[Unit]
Description=Ad tracker for Telegram Mini App
After=network.target

[Service]
EnvironmentFile=$APP/.env
ExecStart=/usr/bin/python3 $APP/server.py
WorkingDirectory=$APP
User=www-data
Restart=always

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now adtracker
systemctl restart adtracker
sleep 1
CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8787/api/items || true)
[ "$CODE" = "401" ] && echo "Сервер приложения работает." || { echo "Сервер приложения не отвечает (код $CODE). Смотрите: journalctl -u adtracker -n 30"; exit 1; }

cat > /etc/nginx/sites-available/adtracker <<NGINX
server {
    listen 80;
    server_name $DOMAIN;
    client_max_body_size 1m;
    location / {
        proxy_pass http://127.0.0.1:8787;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
NGINX
ln -sf /etc/nginx/sites-available/adtracker /etc/nginx/sites-enabled/adtracker
nginx -t
systemctl reload nginx || systemctl restart nginx
command -v ufw >/dev/null 2>&1 && ufw status | grep -q active && ufw allow 80,443/tcp || true

MYIP=$(curl -s4 https://api.ipify.org || true)
DNSIP=$(dig +short A "$DOMAIN" | tail -n1)
echo "IP сервера: $MYIP, адрес $DOMAIN указывает на: ${DNSIP:-ничего}"
if [ -z "$DNSIP" ] || { [ -n "$MYIP" ] && [ "$DNSIP" != "$MYIP" ]; }; then
  echo "DNS ещё не обновился. Подождите 10-30 минут и выполните одну команду:"
  echo "certbot --nginx -d $DOMAIN --non-interactive --agree-tos --register-unsafely-without-email --redirect"
  exit 0
fi
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email --redirect
echo
echo "Готово: https://$DOMAIN/"
