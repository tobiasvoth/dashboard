from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, request, render_template, jsonify, send_from_directory
from urllib.parse import urljoin
import base64

app = Flask(__name__)

# Selenium WebDriver initialisieren
chrome_options = webdriver.ChromeOptions()
chrome_options.add_argument("--headless=new")  
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--no-sandbox")
#automatisch verisonen managen
service = Service(ChromeDriverManager().install())

driver = webdriver.Chrome(service=service, options=chrome_options)

# funktion sucht alle Biler aus dem gescrapten html code und fügt bei ihnen den Sourcecode hinzu, damit sie korekt geladen werden
# man muss sich einmal im zu verwendenden Browser anmelden, damit die Bilder auch angezeigt werden
def convert_images_to_base64_alt(soup):
    for img in soup.find_all("img"):
        if img.get("src") and not img["src"].startswith("data"):
            img_url = urljoin("https://to.gether.one/", img["src"])
            try:
                response = requests.get(img_url, stream=True)
                if response.status_code == 200:
                    img_data = base64.b64encode(response.content).decode("utf-8")
                    img["src"] = f"data:image/png;base64,{img_data}"
            except requests.exceptions.RequestException as e:
                print(f"[ERROR] Bild konnte nicht geladen werden: {e}")
    return soup


#prüft, ob Benutzer noch eingeloggt ist und gibt True oder False zurück
def is_logged_in():
    """Prüft, ob der Benutzer noch eingeloggt ist."""
    try:
        WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".cui-button.cui-focus-in.nav-active"))
        )
        print("[INFO] Benutzer ist noch eingeloggt.")
        return True
    except:
        print("[INFO] Sitzung ist abgelaufen, erneute Anmeldung erforderlich.")
        return False
    


def convert_images_to_base64(soup):
    # Alle img-Tags finden
    for img in soup.find_all('img'):
        img_url = img.get('src')
        
        if img_url:
            # Falls die URL relativ ist (z.B. /images/test.jpg), vervollständigen
            if img_url.startswith('/'):
                img_url = "https://to.gether.one" + img_url
            
            try:
                # Bild herunterladen
                response = requests.get(img_url, timeout=5)
                if response.status_code == 200:
                    # Bildtyp bestimmen (jpg, png, etc.)
                    content_type = response.headers.get('content-type')
                    # Bild in Base64 kodieren
                    img_base64 = base64.b64encode(response.content).decode('utf-8')
                    # Das src-Attribut durch den Data-URI ersetzen
                    img['src'] = f"data:{content_type};base64,{img_base64}"
                    print(f"[INFO] Bild erfolgreich eingebettet: {img_url[:50]}...")
            except Exception as e:
                print(f"[ERROR] Fehler beim Laden von {img_url}: {e}")
                
    return soup



# führt Webscraping durch; wenn der Benutzer nicht eingelogt ist wird ein Login durchgeführt
def fetch_page():
    """Lädt die Webseite und führt den Login durch (falls nötig)."""
    
    if not is_logged_in():
        print("[INFO] Führe Login durch...")
        driver.get("https://to.gether.one/home/next-newsticker")

        try:
            # Warte auf das Benutzername-Feld im Shadow DOM
            shadow_host = WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "cat-input[formcontrolname='username']"))
            )
            shadow_root = shadow_host.shadow_root
            username_input = shadow_root.find_element(By.CSS_SELECTOR, "input")
            username_input.send_keys("hrmail+dashboard@noz-next.de")

            # Warte auf das Passwort-Feld im Shadow DOM
            shadow_host = driver.find_element(By.CSS_SELECTOR, "cat-input[formcontrolname='password']")
            shadow_root = shadow_host.shadow_root
            password_input = shadow_root.find_element(By.CSS_SELECTOR, "input")
            password_input.send_keys("Start123?")
            
            # Login bestätigen
            password_input.send_keys(Keys.RETURN)
            print("[INFO] Login erfolgreich!")

            # Warte, bis die Seite geladen ist
            time.sleep(5)

        except Exception as e:
            print(f"[ERROR] Fehler beim Login: {e}")
            return "<h1>Fehler beim Login</h1>"

    # Nach dem Login oder wenn bereits eingeloggt, Seite neu laden
    driver.get("https://to.gether.one/home/next-newsticker")
    WebDriverWait(driver, 20).until(lambda d: d.execute_script("return document.readyState") == "complete" and  driver.execute_script("return window.onload") is not None)

    time.sleep(8)  # Gib der Seite etwas Zeit zum Laden

    # HTML mit BeautifulSoup parsen
    soup = BeautifulSoup(driver.page_source, "lxml")

    # Punkt 3: Base Tag hinzufügen, damit relative Pfade funktionieren
    base_tag = soup.new_tag("base", href="https://to.gether.one/")
    soup.head.insert(0, base_tag)
    soup = convert_images_to_base64(soup)

    # Extrahiere das div mit einer bestimmten Klasse (z.B. "content")
    target_div = soup.find("main", class_="content")

    # Extrahiere den gesamten <head>-Tag
    head = soup.find("head")

    # Gib sowohl den <head>-Tag als auch den Ziel-<div> zurück
    page_content = ""

    # Füge den <head> Tag hinzu
    if head:
        page_content += str(head)

    # Füge das <div> mit der Klasse "content" hinzu
    if target_div:
        print("[INFO] Div mit der Klasse 'content' gefunden")
        page_content += str(target_div)
    else:
        print("[INFO] Div mit der Klasse 'content' wurde nicht gefunden.")
        page_content += "<h1>Das gesuchte div wurde nicht gefunden</h1>"

    return page_content


# Route gibt den html-Code der gescrapten Webseite zurück
@app.route("/")
def index():
    """Ruft die Seite ab und zeigt den Header und das div im IFrame-kompatiblen Format an."""
    
    return Response(fetch_page(), mimetype="text/html")
        



# gibt Seite mit Newsletter und Wetter zurück
@app.route("/news")
def news():
    
    return render_template("main_absence.html")
        
# gibt Seite mit deskly 1 zurück
@app.route("/deskly")
def deskly():
    return render_template("main_deskly.html")
# gibt Seite mit deskly 2 zurück
@app.route("/deskly2")
def deskly2():
    return render_template("main_deskly2.html")

# gibt Webseite zurück, die durch alle drei vorherigen iteriert
@app.route("/main")
def wechsel():
    return render_template("main_wechsel.html")

# gibt static-files zurück
@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)


# Aufruf der Wetter api
api_key = "3e7f4a88efa2db4aec6ea09566195f57"

city_osna = "Osnabrück"
city_flens = "Flensburg"
city_neu = "Neubrandenburg"
city_ham = "Hamburg"


wetter = []

# Macht eine API-Anfrage zu Open-Weather-Map
def weather(city): 
	
	response = requests.get(f"https://api.openweathermap.org/data/2.5/weather?&units=metric&q={city}&appid={api_key}")
	
	
	if response.status_code == 200:
		data = response.json()
			

		temp = data["main"]["temp"]
		icon_id = data["weather"][0]["icon"]
		data_trans = [temp, icon_id]
		return(data_trans)
		



	else:
		print(f"Fehler: {response.status_code}")
		data_trans = 404
		return(data_trans)

	
	
# API wird für unterschiedliche Städte abgefragt
def aufruf ():


	weather_total = {
		
		"Osnabrueck": weather(city_osna),
		"Flensburg": weather(city_flens),
		"Neubrandenburg": weather(city_neu),
		"Hamburg": weather(city_ham)


	}	

	
	
	return weather_total


# API-Endpoint, der Wetterdaten als JSON zurückgibt
@app.route("/weather", methods=["GET"])
def send_json():
	return jsonify(aufruf())



# Initialisierung des Servers auf Portb 5500
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5500, debug=True)











