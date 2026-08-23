#!/usr/bin/env bash
# Erstinstallation auf einer Debian/Ubuntu-Kiste (z. B. IONOS).
# Aufruf:  sudo bash deploy/install.sh
set -euo pipefail

APP_DIR=/opt/steamhub
APP_USER=steamhub
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Pakete"
apt-get update -qq
apt-get install -y python3 python3-venv python3-pip nginx

echo "==> Benutzer $APP_USER"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"

echo "==> Dateien nach $APP_DIR"
mkdir -p "$APP_DIR"
rsync -a --exclude ".venv" --exclude "data/*.db*" --exclude ".env" "$REPO_DIR"/ "$APP_DIR"/
mkdir -p "$APP_DIR/data"

echo "==> Virtualenv"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo "    -> $APP_DIR/.env angelegt. STEAM_API_KEY eintragen!"
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "==> systemd"
cp "$APP_DIR/deploy/steamhub.service" /etc/systemd/system/
cp "$APP_DIR/deploy/steamhub-collect.service" /etc/systemd/system/
cp "$APP_DIR/deploy/steamhub-collect.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now steamhub.service
systemctl enable --now steamhub-collect.timer

cat <<'EOF'

Fertig. Naechste Schritte:

  1. API-Key eintragen:   sudo nano /opt/steamhub/.env
  2. Spieler hinzufuegen: sudo -u steamhub /opt/steamhub/.venv/bin/python -m app.cli add <profil-url> --nick "Name"
  3. Erster Sammellauf:   sudo -u steamhub /opt/steamhub/.venv/bin/python -m app.cli collect --full
  4. nginx einrichten:    /opt/steamhub/deploy/nginx-steamhub.conf anpassen und verlinken
  5. Status ansehen:      systemctl status steamhub; journalctl -u steamhub-collect -n 50

EOF
