#!/bin/bash

export DISPLAY=:0
day_of_week=$(date +%u) 

if [ "$day_of_week" -eq 6 ] || [ "$day_of_week" -eq 7 ]; then
    echo "Es ist Wochenende (Samstag oder Sonntag). Der PC wird jetzt heruntergefahren."
    poweroff
else
    echo "Heute ist kein Wochenende. Der PC bleibt an."
fi
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

source SCRIPT_DIR/mouse.sh&

source SCRIPT_DIR/venv/bin/activate 
sleep 2
python SCRIPT_DIR/toogether.py&

google-chrome --disable-background-timer-throttling --disable-renderer-backgrounding --autoplay-policy=no-user-gesture-required --start-fullscreen "http://127.0.0.1:5500/main" --new-window&

