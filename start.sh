#!/bin/bash

# Keine Leerzeichen um das '='
SCRIPT_DIR="/root/my-applications/dashboard"

# Display & X-Server-Berechtigung setzen
export DISPLAY=:0
export XAUTHORITY="/root/.Xauthority"

# Python direkt aus der virtuellen Umgebung im Hintergrund starten
"$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/toogether.py" &

# Wartezeit, damit der Webserver hochfahren kann
sleep 2

# Chrome starten (inkl. --no-sandbox für Root-Betrieb)
google-chrome \
  --no-sandbox \
  --disable-background-timer-throttling \
  --disable-renderer-backgrounding \
  --autoplay-policy=no-user-gesture-required \
  --start-fullscreen \
  --new-window \
  "http://127.0.0.1:5500/news" &