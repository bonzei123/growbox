from flask import Flask, render_template, request, jsonify, send_from_directory, Response
import datetime
import os
import glob
import subprocess
import time
import sqlite3
import requests

app = Flask(__name__)

# --- Home Assistant API Konfiguration ---
# WICHTIG: Ersetzen Sie diese Platzhalter durch Ihre echten Werte
HA_CONFIG = {
    "HA_URL": "http://192.168.0.167:8123", # IP Ihres Home Assistant Servers
    "HA_TOKEN": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiIyOWE3YmRhZDJlOTY0NzEzYTI4MmU1ZDM4OTU4YTIzOCIsImlhdCI6MTc1OTI2NjI3NiwiZXhwIjoyMDc0NjI2Mjc2fQ.ozfMbYAhcEOFvy-2zRKADr8Bq0XnI22_1jGVMsY6EQw",
    "TEMP_ZELT_ENTITY": "sensor.growzeltdaten_temperature",
    "HUM_ZELT_ENTITY": "sensor.growzeltdaten_humidity",
    "LIGHT_POWER_ENTITY": "sensor.grow_licht_power"
}

# --- Datenbank Konfiguration ---
DB_NAME = '/home/pi/growbox_monitor/growbox_data.db'
PHOTO_DIR = "/home/pi/growbox_photos"
TIMELAPSE_DIR = "/home/pi/growbox_timelapses"
LATEST_PHOTO_PATH = os.path.join(PHOTO_DIR, 'latest_photo.jpg')

# Stelle sicher, dass die Verzeichnisse existieren
os.makedirs(TIMELAPSE_DIR, exist_ok=True)
os.makedirs(PHOTO_DIR, exist_ok=True)

# WICHTIG: Pfade anpassen (vom 'which'-Befehl)
FFMPEG_PATH = "/usr/bin/ffmpeg"
RPICAM_STILL_PATH = "/usr/bin/rpicam-still"

# --- Hilfsfunktion für Home Assistant API Abrufe ---
def get_ha_sensor_state(entity_id):
    """Ruft den Zustand eines Sensors von der Home Assistant API ab."""
    url = f"{HA_CONFIG['HA_URL']}/api/states/{entity_id}"
    headers = {
        "Authorization": f"Bearer {HA_CONFIG['HA_TOKEN']}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status() # Löst Ausnahme für schlechte Statuscodes aus (4xx oder 5xx)
        data = response.json()
        return data.get("state", "N/A")
    except requests.exceptions.RequestException as e:
        print(f"Fehler beim Abruf von HA Sensor {entity_id}: {e}")
        return "N/A"

# --- DS18B20 Temperatursensor Logik ---
base_dir = '/sys/bus/w1/devices/'
device_folder = ''
device_file = ''

def find_ds18b20():
    """Findet den Temperatursensor beim Start."""
    global device_folder, device_file
    try:
        # Sucht nach Ordnern, die mit '28-' beginnen (DS18B20-ID)
        folders = [f for f in os.listdir(base_dir) if f.startswith('28-')]
        if folders:
            device_folder = os.path.join(base_dir, folders[0])
            device_file = os.path.join(device_folder, 'w1_slave')
            print(f"DS18B20 sensor found at: {device_folder}")
            return True
        else:
            print("No DS18B20 sensor found.")
            return False
    except FileNotFoundError:
        print("1-Wire directory not found. Is 1-Wire enabled?")
        return False
    except Exception as e:
        print(f"Error finding DS18B20: {e}")
        return False

def read_temp_raw():
    """Liest die Rohdaten vom Sensor."""
    try:
        if not device_file:
            if not find_ds18b20():
                return None
        with open(device_file, 'r') as f:
            lines = f.readlines()
        return lines
    except Exception as e:
        print(f"Error reading raw temp: {e}")
        return None

def read_temp():
    """Konvertiert die Rohdaten in Celsius."""
    lines = read_temp_raw()
    if lines is None:
        return "N/A"

    # Stellt sicher, dass die CRC-Prüfung "YES" liefert
    while lines[0].strip()[-3:] != 'YES':
        time.sleep(0.2)
        lines = read_temp_raw()
        if lines is None:
            return "N/A"

    equals_pos = lines[1].find('t=')
    if equals_pos != -1:
        temp_string = lines[1][equals_pos+2:]
        temp_c = float(temp_string) / 1000.0
        return round(temp_c, 2)
    return "N/A"


# --- Kamera Stream API (liest nur aus dem Dateisystem) ---
@app.route('/latest_photo')
def latest_photo():
    """
    Liefert das neueste Bild vom Dateisystem.
    Das Bild wird durch das separate Skript 'update_camera_image.py' aktualisiert.
    """
    if os.path.exists(LATEST_PHOTO_PATH):
        # send_from_directory handhabt den korrekten MIME-Typ
        return send_from_directory(PHOTO_DIR, 'latest_photo.jpg', mimetype='image/jpeg')
    else:
        # Fallback, wenn kein Bild verfügbar ist
        return "No image available. Run update_camera_image.py.", 503


# --- API-Endpunkt für Temperaturdaten (Repariert und Robust) ---
@app.route('/api/temperature_data')
def get_temperature_data():
    """
    Liefert Temperaturdaten für den Chart (JSON-Format).
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Standardmäßig 24 Stunden, konvertiert von Stunden in Sekunden (1h = 3600s)
        hours = request.args.get('hours', type=int, default=24)

        # Berechne den ISO-Zeitpunkt für die Abfrage
        time_ago = datetime.datetime.now() - datetime.timedelta(hours=hours)
        time_ago_iso = time_ago.isoformat()

        # Abfrage der Daten aus der Datenbank
        cursor.execute("SELECT timestamp, value FROM temperatures WHERE timestamp >= ? ORDER BY timestamp ASC", (time_ago_iso,))
        data = cursor.fetchall()

        if not data:
            # Fallback bei leeren Daten
            print("DB ist leer oder keine Daten für den Zeitraum. Fallback-Daten werden generiert.")

            # Generiere Dummy-Daten (um den Chart nicht crashen zu lassen)
            labels = []
            values = []
            start_time = datetime.datetime.now() - datetime.timedelta(hours=hours)
            num_points = (hours * 12) # 12 Punkte pro Stunde (alle 5 Minuten)

            for i in range(num_points):
                point_time = start_time + datetime.timedelta(minutes=i * 5)
                labels.append(point_time.isoformat())
                # Generiere plausible, aber fiktive Temperaturwerte
                sample_temp = 22.0 + (i % 20 - 10) * 0.2 + (i % 5 - 2.5) * 0.5
                values.append(round(sample_temp, 2))

            return jsonify({'labels': labels, 'values': values})

        # Echte Daten extrahieren und zurückgeben
        labels = [row[0] for row in data]
        values = [row[1] for row in data]
        return jsonify({'labels': labels, 'values': values})

    except sqlite3.Error as e:
        print(f"Datenbankfehler: {e}. Fallback wird verwendet.")
        # Generiere Fallback-Daten auch bei Datenbankverbindungsfehlern
        hours = request.args.get('hours', type=int, default=24)
        labels = []
        values = []
        start_time = datetime.datetime.now() - datetime.timedelta(hours=hours)
        num_points = (hours * 12)

        for i in range(num_points):
            point_time = start_time + datetime.timedelta(minutes=i * 5)
            labels.append(point_time.isoformat())
            # Generiere plausible, aber fiktive Temperaturwerte
            sample_temp = 22.0 + (i % 20 - 10) * 0.2 + (i % 5 - 2.5) * 0.5
            values.append(round(sample_temp, 2))

        return jsonify({'labels': labels, 'values': values}), 500

    finally:
        if conn:
            conn.close()


# --- Webserver Routen ---
@app.route('/')
def index():
    """Rendert die Hauptseite mit aktuellen Daten."""
    current_datetime = datetime.datetime.now()
    current_time = current_datetime.strftime("%H:%M:%S")
    current_date = current_datetime.strftime("%d.%m.%Y")

    # 1. Lokale (Pi) Temperatur abrufen
    temperature_pi = read_temp()
    
    # 2. HA Zelt-Daten abrufen
    temp_zelt = get_ha_sensor_state(HA_CONFIG["TEMP_ZELT_ENTITY"])
    hum_zelt = get_ha_sensor_state(HA_CONFIG["HUM_ZELT_ENTITY"])
    light_power = get_ha_sensor_state(HA_CONFIG["LIGHT_POWER_ENTITY"])

    return render_template('index.html',
                           current_time=current_time,
                           current_date=current_date,
                           temperature=temperature_pi, # Das ist die Pi-Temperatur
                           temp_zelt=temp_zelt,       # Neu: Zelt-Temperatur
                           hum_zelt=hum_zelt,         # Neu: Zelt-Luftfeuchtigkeit
                           light_power=light_power)   # Neu: Lampenstärke

@app.route('/create_timelapse', methods=['POST'])
def create_timelapse():
    """Erstellt ein Zeitraffervideo aus den archivierten Bildern."""
    os.makedirs(PHOTO_DIR, exist_ok=True)
    os.makedirs(TIMELAPSE_DIR, exist_ok=True)

    # Temporäre Links für ffmpeg aufräumen
    for f in glob.glob(os.path.join(TIMELAPSE_DIR, 'temp_*.jpg')):
        os.remove(f)

    # Archivierte Fotos verwenden (die alle 30 Minuten gespeichert werden)
    photos = sorted(glob.glob(os.path.join(PHOTO_DIR, 'archive_photo_*.jpg')))

    if not photos:
        return render_template('timelapse_status.html', message="Keine archivierten Fotos gefunden, um einen Zeitraffer zu erstellen.", video_url=None), 404

    # Erstelle symbolische Links, damit ffmpeg die Bilder sequenziell verarbeiten kann
    for i, photo_path in enumerate(photos):
        link_path = os.path.join(TIMELAPSE_DIR, f"temp_{i:05d}.jpg")
        try:
            os.symlink(photo_path, link_path)
        except FileExistsError:
            pass

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_video = os.path.join(TIMELAPSE_DIR, f"timelapse_{timestamp}.mp4")

    # FFMPEG-Befehl
    command = [
        FFMPEG_PATH, "-y",
        "-framerate", "10",
        "-i", os.path.join(TIMELAPSE_DIR, "temp_%05d.jpg"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", "23",
        output_video
    ]

    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
        message = f"Zeitraffer '{os.path.basename(output_video)}' erfolgreich erstellt!"
    except subprocess.CalledProcessError as e:
        message = f"Fehler beim Erstellen des Zeitraffers: {e.stderr}"
    except FileNotFoundError:
        message = "FFmpeg ist nicht installiert oder Pfad ist falsch."
    finally:
        # Temporäre Links wieder entfernen
        for f in glob.glob(os.path.join(TIMELAPSE_DIR, 'temp_*.jpg')):
            os.remove(f)

    return render_template('timelapse_status.html', message=message, video_url=os.path.basename(output_video))

@app.route('/timelapses')
def list_timelapses():
    """Zeigt eine Liste der erstellten Zeitraffervideos an."""
    os.makedirs(TIMELAPSE_DIR, exist_ok=True)
    timelapses = sorted([f for f in os.listdir(TIMELAPSE_DIR) if f.endswith('.mp4')], reverse=True)
    return render_template('timelapse_list.html', timelapses=timelapses)

@app.route('/timelapses/<filename>')
def download_timelapse(filename):
    """Ermöglicht den Download eines Zeitraffers."""
    return send_from_directory(TIMELAPSE_DIR, filename, as_attachment=True)

@app.route('/favicon.ico')
def favicon():
    """Standard-Favicon-Route."""
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

if __name__ == '__main__':
    find_ds18b20()
    # Starte die App
    app.run(host='0.0.0.0', port=8000, debug=True)
