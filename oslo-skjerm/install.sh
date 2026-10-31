#!/usr/bin/env bash
# Installerer Oslo-skjerm på OKDO/Radxa Rock 4C+ med Debian-image.
# Kjøres fra pakkemappen på maskinen:  sudo bash install.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Kjør med sudo:  sudo bash install.sh" >&2
  exit 1
fi

# Brukeren som er innlogget på skjermen og får kiosk-vinduet
BRUKER="${SUDO_USER:-radxa}"
HJEM="$(getent passwd "$BRUKER" | cut -d: -f6)"
KILDE="$(cd "$(dirname "$0")" && pwd)"
MAPPE=/opt/oslo-skjerm

echo "==> Installerer pakker"
apt-get update
apt-get install -y python3 ca-certificates tzdata chromium x11-xserver-utils

echo "==> Kopierer filer til $MAPPE"
install -d "$MAPPE"
cp -r "$KILDE/server.py" "$KILDE/config.json" "$KILDE/web" "$MAPPE/"
chmod -R a+rX "$MAPPE"

echo "==> Oppretter systemtjeneste som henter data i bakgrunnen"
cat > /etc/systemd/system/oslo-skjerm.service <<EOF
[Unit]
Description=Oslo-skjerm: avganger og vær
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 $MAPPE/server.py
WorkingDirectory=$MAPPE
User=nobody
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now oslo-skjerm.service

echo "==> Lager autostart som åpner skjermsiden i fullskjerm ($BRUKER)"
install -d -o "$BRUKER" -g "$BRUKER" "$HJEM/.config/autostart"
cat > "$HJEM/.config/autostart/oslo-skjerm.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Oslo-skjerm
Exec=sh -c "xset s off; xset -dpms; xset s noblank; sleep 8; chromium --kiosk --noerrdialogs --disable-infobars --no-first-run http://127.0.0.1:8080"
X-GNOME-Autostart-enabled=true
EOF
chown "$BRUKER:$BRUKER" "$HJEM/.config/autostart/oslo-skjerm.desktop"

echo
echo "Ferdig. Start på nytt med:  sudo reboot"
echo "Sjekk data:                 curl http://127.0.0.1:8080/api/data"
echo "Se logg:                    journalctl -u oslo-skjerm -f"
