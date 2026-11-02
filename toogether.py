"""
toogether.py - Performantes NEXT Dashboard Backend
- Zuverlässiger Hintergrund-Scraper für to:gether (Haiilo / COYO)
- Asynchrone In-Browser-Konvertierung von Bildern zu Base64
- Sofortige Antwortzeiten (<5ms) durch intelligentes In-Memory- und Disk-Caching
- Parallele & gecachte Wetterabfragen
- Robuste Fehlerbehandlung: Ausfälle führen nie zum Absturz oder zu einer leeren Seite
"""

import os
import time
import json
import base64
import logging
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, request, render_template, jsonify, send_from_directory

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("toogether")

app = Flask(__name__)

# Konfiguration
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
CACHE_FILE = os.path.join(CACHE_DIR, "toogether_cache.html")
os.makedirs(CACHE_DIR, exist_ok=True)

TARGET_URL = "https://to.gether.one/home/next-newsticker"
LOGIN_USER = "hrmail+dashboard@noz-next.de"
LOGIN_PASS = "Start123?"

SCRAPE_INTERVAL_SECONDS = 10 * 60  # Alle 10 Minuten aktualisieren
RETRY_DELAY_SECONDS = 2 * 60       # Bei Fehlern nach 2 Minuten erneut versuchen


# ==============================================================================
# HINTERGRUND-SCRAPER & CACHE MANAGER
# ==============================================================================

class ToogetherScraper:
    def __init__(self):
        self._lock = threading.Lock()
        self._cached_html = ""
        self._last_update = None
        self._last_status = "Initialisiere..."
        self._is_fetching = False
        self._stop_event = threading.Event()
        self._force_trigger = threading.Event()

        # Cache von Festplatte laden, falls vorhanden
        self._load_cache_from_disk()

    def _load_cache_from_disk(self):
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    content = f.read()
                if len(content) > 1000 and "content" in content:
                    self._cached_html = content
                    mtime = os.path.getmtime(CACHE_FILE)
                    self._last_update = datetime.fromtimestamp(mtime)
                    self._last_status = f"Aus lokalem Cache geladen ({self._last_update.strftime('%H:%M:%S')})"
                    logger.info("Bestehender Cache erfolgreich von Festplatte geladen.")
            except Exception as e:
                logger.error(f"Fehler beim Lesen des Festplatten-Caches: {e}")

    def _save_cache_to_disk(self, html_content):
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                f.write(html_content)
        except Exception as e:
            logger.error(f"Fehler beim Schreiben des Festplatten-Caches: {e}")

    def get_cached_html(self):
        with self._lock:
            if self._cached_html:
                return self._cached_html

        # Fallback-Seite, falls der erste Abruf noch läuft
        return """<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="3">
    <title>to:gether wird geladen</title>
    <style>
        body {
            font-family: 'Source Sans Pro', -apple-system, BlinkMacSystemFont, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background: #f8f9fa;
            color: #555;
            flex-direction: column;
        }
        .spinner {
            width: 48px;
            height: 48px;
            border: 5px solid #e0e0e0;
            border-top: 5px solid #00a7e7;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-bottom: 20px;
        }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        p { font-size: 18px; margin: 0; }
    </style>
</head>
<body>
    <div class="spinner"></div>
    <p>to:gether Newsticker wird initialisiert...</p>
</body>
</html>"""

    def get_status(self):
        with self._lock:
            return {
                "has_cache": bool(self._cached_html),
                "cache_size_bytes": len(self._cached_html),
                "last_update": self._last_update.isoformat() if self._last_update else None,
                "status": self._last_status,
                "is_fetching": self._is_fetching
            }

    def trigger_refresh(self):
        self._force_trigger.set()

    def _create_driver(self):
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--blink-settings=imagesEnabled=true")

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.set_page_load_timeout(35)
        return driver

    def _perform_scrape(self):
        driver = None
        start_time = time.time()
        logger.info("Starte Aktualisierung von to:gether...")

        try:
            driver = self._create_driver()
            driver.get(TARGET_URL)

            # Prüfe, ob Anmeldefenster erscheint
            try:
                username_el = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((
                        By.CSS_SELECTOR,
                        "cat-input[name='username'], cat-input[formcontrolname='username'], input[name='username']"
                    ))
                )
                logger.info("Login-Formular erkannt. Führe automatische Anmeldung durch...")

                # Username eingeben (unterstützt Shadow DOM falls cat-input)
                try:
                    u_input = username_el.shadow_root.find_element(By.CSS_SELECTOR, "input")
                except Exception:
                    u_input = username_el
                u_input.clear()
                u_input.send_keys(LOGIN_USER)

                # Passwort eingeben
                password_el = driver.find_element(
                    By.CSS_SELECTOR,
                    "cat-input[name='password'], cat-input[formcontrolname='password'], input[name='password']"
                )
                try:
                    p_input = password_el.shadow_root.find_element(By.CSS_SELECTOR, "input")
                except Exception:
                    p_input = password_el
                p_input.clear()
                p_input.send_keys(LOGIN_PASS)

                # Login-Button klicken oder Enter drücken
                try:
                    btn = driver.find_element(
                        By.CSS_SELECTOR,
                        "cat-button[name='login'], cat-button[data-test='button-submit'], button[type='submit']"
                    )
                    btn.click()
                except Exception:
                    p_input.send_keys(Keys.RETURN)

                logger.info("Login-Anfrage übermittelt.")

            except Exception:
                logger.info("Kein Login-Formular sichtbar, eventuell bereits autorisiert.")

            # Warte auf das Ziel-Element: main.content
            logger.info("Warte auf main.content...")
            WebDriverWait(driver, 25).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "main.content"))
            )

            # Kurze Pause für finale Rendering-Schritte der Angular-Komponenten
            time.sleep(3)

            # In-Browser-Konvertierung: Alle Bilder in main.content asynchron zu Base64 umwandeln
            logger.info("Konvertiere Bilder direkt im Browser zu Base64...")
            convert_js = """
            const callback = arguments[arguments.length - 1];
            (async () => {
                const images = Array.from(document.querySelectorAll('main.content img'));
                let success = 0;
                for (const img of images) {
                    try {
                        if (img.src && !img.src.startsWith('data:')) {
                            const resp = await fetch(img.src);
                            const blob = await resp.blob();
                            const reader = new FileReader();
                            await new Promise((resolve) => {
                                reader.onloadend = () => {
                                    img.src = reader.result;
                                    success++;
                                    resolve();
                                };
                                reader.readAsDataURL(blob);
                            });
                        }
                    } catch (e) {
                        // Bei Fehlern Bild überspringen
                    }
                }
                callback({ total: images.length, converted: success });
            })();
            """
            driver.set_script_timeout(20)
            res = driver.execute_async_script(convert_js)
            logger.info(f"Bildkonvertierung abgeschlossen: {res}")

            # HTML parsen und zusammenbauen
            soup = BeautifulSoup(driver.page_source, "lxml")

            base_tag = soup.new_tag("base", href="https://to.gether.one/")
            if soup.head:
                soup.head.insert(0, base_tag)

            head_tag = soup.find("head")
            target_div = soup.find("main", class_="content")

            if not target_div:
                raise ValueError("div mit Klasse 'content' konnte nach Login nicht gefunden werden.")

            # Zusätzliches Styling für reibungslose Einbettung & sauberes Scrollen
            custom_style = """
            <style>
                html, body {
                    background-color: #ffffff !important;
                    margin: 0 !important;
                    padding: 10px 15px !important;
                    font-family: 'Source Sans Pro', -apple-system, BlinkMacSystemFont, sans-serif !important;
                    overflow-x: hidden !important;
                    scrollbar-width: thin;
                }
                ::-webkit-scrollbar {
                    width: 6px;
                }
                ::-webkit-scrollbar-thumb {
                    background: #ccc;
                    border-radius: 4px;
                }
                /* Einheitlich rechtsbündige Datumsangabe bei Blogeinträgen */
                .cat-flex-row.cat-justify-between {
                    display: flex !important;
                    flex-direction: row !important;
                    justify-content: space-between !important;
                    align-items: center !important;
                    width: 100% !important;
                }
                .cat-flex-row.cat-justify-between > a {
                    flex: 1 1 auto !important;
                    min-width: 0 !important;
                    overflow: hidden !important;
                    text-overflow: ellipsis !important;
                    white-space: nowrap !important;
                }
                .date-small {
                    display: none !important;
                }
                .date-large {
                    display: inline-block !important;
                    margin-left: auto !important;
                    text-align: right !important;
                    white-space: nowrap !important;
                    flex-shrink: 0 !important;
                    padding-left: 15px !important;
                    font-size: 0.88rem !important;
                    color: #777777 !important;
                }
            </style>
            """

            full_html = "<!DOCTYPE html>\n<html lang=\"de\">\n"
            if head_tag:
                full_html += str(head_tag) + "\n"
            else:
                full_html += "<head><base href=\"https://to.gether.one/\"></head>\n"
            full_html = full_html.replace("</head>", f"{custom_style}\n</head>")
            full_html += "<body>\n" + str(target_div) + "\n</body>\n</html>"

            # Cache atomar aktualisieren
            with self._lock:
                self._cached_html = full_html
                self._last_update = datetime.now()
                self._last_status = f"Erfolgreich aktualisiert um {self._last_update.strftime('%H:%M:%S')}"

            self._save_cache_to_disk(full_html)
            duration = round(time.time() - start_time, 2)
            logger.info(f"to:gether erfolgreich aktualisiert ({len(full_html)} Bytes) in {duration}s!")
            return True

        except Exception as e:
            logger.error(f"Fehler beim Scrapen von to:gether: {e}", exc_info=True)
            with self._lock:
                self._last_status = f"Fehler bei Aktualisierung: {str(e)[:100]}"
            return False

        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    def run_worker_loop(self):
        logger.info("Hintergrund-Scraper-Thread gestartet.")

        # Falls kein Cache vorhanden ist, sofort scrapen
        if not self._cached_html:
            self._perform_scrape()

        while not self._stop_event.is_set():
            # Warte auf nächstes Intervall oder manuellen Trigger
            triggered = self._force_trigger.wait(timeout=SCRAPE_INTERVAL_SECONDS)
            if triggered:
                self._force_trigger.clear()
                logger.info("Manuelle Aktualisierung getriggert.")

            if self._stop_event.is_set():
                break

            with self._lock:
                self._is_fetching = True

            success = self._perform_scrape()

            with self._lock:
                self._is_fetching = False

            # Wenn ein Fehler aufgetreten ist, früher erneut versuchen
            if not success:
                logger.info(f"Wiederhole Versuch in {RETRY_DELAY_SECONDS} Sekunden...")
                self._stop_event.wait(timeout=RETRY_DELAY_SECONDS)


scraper_service = ToogetherScraper()


# ==============================================================================
# WETTER-ABFRAGEN MIT PARALLELISIERUNG & CACHING
# ==============================================================================

WEATHER_API_KEY = "3e7f4a88efa2db4aec6ea09566195f57"
CITIES = {
    "Osnabrueck": "Osnabrück",
    "Flensburg": "Flensburg",
    "Neubrandenburg": "Neubrandenburg",
    "Hamburg": "Hamburg"
}

weather_cache = {
    "data": None,
    "last_fetched": 0,
    "lock": threading.Lock()
}

def fetch_single_city_weather(city_name):
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?units=metric&q={city_name}&appid={WEATHER_API_KEY}"
        resp = requests.get(url, timeout=6)
        if resp.status_code == 200:
            d = resp.json()
            temp = d["main"]["temp"]
            icon_id = d["weather"][0]["icon"]
            return [temp, icon_id]
        else:
            logger.warning(f"Wetter-API Fehler {resp.status_code} für {city_name}")
            return [20.0, "01d"]
    except Exception as e:
        logger.error(f"Ausnahme bei Wetterabfrage {city_name}: {e}")
        return [20.0, "01d"]

def get_weather_data():
    now = time.time()
    # Cache für 10 Minuten gültig
    with weather_cache["lock"]:
        if weather_cache["data"] and (now - weather_cache["last_fetched"] < 600):
            return weather_cache["data"]

    # Parallel abfragen
    results = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_key = {
            executor.submit(fetch_single_city_weather, city_query): key
            for key, city_query in CITIES.items()
        }
        for future in future_to_key:
            key = future_to_key[future]
            try:
                results[key] = future.result()
            except Exception:
                results[key] = [20.0, "01d"]

    with weather_cache["lock"]:
        weather_cache["data"] = results
        weather_cache["last_fetched"] = now

    return results


# ==============================================================================
# FLASK ROUTEN
# ==============================================================================

@app.route("/")
def index():
    """Gibt den HTML-Inhalt des to:gether Newstickers sofort aus dem Cache zurück (<2ms)."""
    resp = Response(scraper_service.get_cached_html(), mimetype="text/html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp

@app.route("/news")
def news():
    """Zeigt das Hauptdashboard mit Wetter, Uhr und to:gether Iframe."""
    return render_template("main_absence.html")

@app.route("/deskly")
def deskly():
    """Zeigt Deskly Plan 1."""
    return render_template("main_deskly.html")

@app.route("/deskly2")
def deskly2():
    """Zeigt Deskly Plan 2."""
    return render_template("main_deskly2.html")

@app.route("/main")
def wechsel():
    """Rotator-Seite, die zwischen /news, /deskly und /deskly2 wechselt."""
    return render_template("main_wechsel.html")

@app.route("/weather", methods=["GET"])
def weather_endpoint():
    """API-Endpunkt für Wetterdaten im bekannten Format."""
    return jsonify(get_weather_data())

@app.route("/static/<path:filename>")
def static_files(filename):
    """Statische Assets ausliefern."""
    return send_from_directory("static", filename)

@app.route("/api/status")
def status_endpoint():
    """Gibt den Status des Scrapers und Caches als JSON zurück."""
    return jsonify({
        "scraper": scraper_service.get_status(),
        "weather_cache_age_seconds": round(time.time() - weather_cache["last_fetched"], 1) if weather_cache["data"] else None
    })

@app.route("/api/refresh", methods=["POST", "GET"])
def refresh_endpoint():
    """Löst eine sofortige Neuabfrage im Hintergrund aus."""
    scraper_service.trigger_refresh()
    return jsonify({"message": "Hintergrund-Aktualisierung wurde angestoßen."})


# ==============================================================================
# HAUPTPROGRAMM
# ==============================================================================

def start_background_scraper():
    worker_thread = threading.Thread(
        target=scraper_service.run_worker_loop,
        name="ToogetherScraperWorker",
        daemon=True
    )
    worker_thread.start()

# Hintergrund-Thread starten (beim Modul-Import oder Hauptstart)
start_background_scraper()

if __name__ == "__main__":
    logger.info("Starte toogether Server auf Port 5500...")
    # debug=False verhindert doppeltes Starten der Threads durch den Flask Werkzeug-Reloader
    app.run(host="0.0.0.0", port=5500, debug=False, threaded=True)
