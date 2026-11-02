#!/bin/bash

# Keine Leerzeichen um das '='
SCRIPT_DIR="/root/my-applications/dashboard"

# Display & X-Server-Berechtigung setzen
export DISPLAY=:0
export XAUTHORITY="/root/.Xauthority"

# Virtuelle Umgebung aktivieren und Skript im Hintergrund starten
source "$SCRIPT_DIR/venv/bin/activate"
python "$SCRIPT_DIR/toogether.py" &

# Wartezeit, damit der Webserver hochfahren kann
sleep 2

# Chrome starten (inkl. --no-sandbox für Root-Betrieb)
google-chrome \
  --no-sandbox \
  --start-fullscreen \
  --new-window \
  "http://127.0.0.1:5500/news" &