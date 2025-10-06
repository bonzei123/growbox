from flask import Flask, render_template, request, jsonify, send_from_directory, Response
import datetime
import os
import glob
import subprocess
import time
import sqlite3
import requests
import re
from datetime import timedelta

app = Flask(__name__)

# --- Globale Konfigurationen ---
# Pfad zum Ordner, in dem die App ausgeführt wird, um Skripte zu finden
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Home Assistant API Konfiguration ---
# WICHTIG: Ersetzen Sie diese Platzhalter durch Ihre echten Werte
HA_CONFIG = {
    "HA_URL": "http://192.168.0.167:8123", # IP Ihres Home Assistant Servers
    "HA_TOKEN": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiIyOWE3YmRhZDJlOTY0NzEzYTI4MmU1ZDM4OTU4YTIzOCIsImlhdCI6MTc1OTI2NjI3NiwiZXhwIjoyMDc0NjI2Mjc2fQ.ozfMbYAhcEOFvy-2zRKADr8Bq0XnI22_1jGVMsY6EQw",
    "TEMP_ZELT_ENTITY": "sensor.growzeltdaten_temperature",
    "HUM_ZELT_ENTITY": "sensor.growzeltdaten_humidity",
    "LIGHT_POWER_ENTITY": "sensor.grow_licht_power",
    "LUEFTER_ENTITY": "switch.grow_luftung_socket_1" # Für zukünftige direkte Steuerung, derzeit in lueftung.py
}

# --- Datenbank und Pfad Konfiguration ---
DB_NAME = os.path.join(BASE_DIR, 'growbox_data.db')
PHOTO_DIR = os.path.join(BASE_DIR, "growbox_photos")
TIMELAPSE_DIR = os.path.join(BASE_DIR, "growbox_timelapses")
LATEST_PHOTO_PATH = os.path.join(PHOTO_DIR, 'latest_photo.jpg')

# Cronjob Konfiguration (ACHTUNG: Muss dem Benutzer entsprechen, der die App ausführt)
# Der Pfad zur Crontab-Datei des Benutzers, der die cronjobs ausführt (meist 'pi')
CRON_USER = os.environ.get('USER', 'pi')
# Pfad zum Python-Binary in der virtuellen Umgebung
PYTHON_PATH = os.path.join(BASE_DIR, 'venv', 'bin', 'python3')
# Pfad zum Lüftungsskript
LUEFTER_SCRIPT_PATH = os.path.join(BASE_DIR, 'lueftung.py')
CRON_IDENTIFIER = "# GROWAUTOMATION_LUEFTER" # Eindeutiger Marker im Crontab

# Stelle sicher, dass die Verzeichnisse existieren
os.makedirs(TIMELAPSE_DIR, exist_ok=True)
os.makedirs(PHOTO_DIR, exist_ok=True)


# --- Hilfsfunktionen für Datenbank und HA API ---

def get_db_connection():
    """Erstellt eine Datenbankverbindung."""
    return sqlite3.connect(DB_NAME)

def get_ha_sensor_state(entity_id):
    """Ruft den Zustand eines Sensors von der Home Assistant API ab."""
    url = f"{HA_CONFIG['HA_URL']}/api/states/{entity_id}"
    headers = {
        "Authorization": f"Bearer {HA_CONFIG['HA_TOKEN']}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()
        return data.get("state", "N/A")
    except requests.exceptions.RequestException as e:
        print(f"Fehler beim Abruf von HA Sensor {entity_id}: {e}")
        return "N/A"

def get_settings():
    """Lädt die aktuellen Lüfter-Cron-Einstellungen aus der DB."""
    conn = get_db_connection()
    cursor = conn.cursor()
    on_minutes = cursor.execute("SELECT value FROM settings WHERE key='luefter_on_minutes'").fetchone()
    off_minutes = cursor.execute("SELECT value FROM settings WHERE key='luefter_off_minutes'").fetchone()
    conn.close()
    
    # Rückgabe des Wertes oder eines leeren Strings als Standard
    return {
        'on_minutes': on_minutes[0] if on_minutes else '0,20,40',
        'off_minutes': off_minutes[0] if off_minutes else '5,25,45'
    }

def save_setting(key, value):
    """Speichert einen Schlüssel/Wert-Paar in der settings Tabelle."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def update_crontab(on_minutes, off_minutes):
    """
    Aktualisiert die Crontab des Benutzers.
    ACHTUNG: subprocess.run erfordert, dass der Benutzer, der die Flask App ausführt,
    die Rechte hat, 'crontab -e' und 'crontab -l' auszuführen.
    """
    try:
        # 1. Aktuelle Crontab lesen
        result = subprocess.run(['crontab', '-l'], capture_output=True, text=True, check=False, user=CRON_USER)
        current_crontab = result.stdout
        
        # 2. Bestehende Lüfter-Einträge entfernen
        new_crontab_lines = []
        in_luefter_block = False
        for line in current_crontab.splitlines():
            if line.startswith(CRON_IDENTIFIER):
                in_luefter_block = True
                continue
            if line.startswith("# END" + CRON_IDENTIFIER):
                in_luefter_block = False
                continue
            if not in_luefter_block and CRON_IDENTIFIER not in line:
                 # Behält alle Zeilen bei, die nicht zum Lüfter-Block gehören
                new_crontab_lines.append(line)
        
        # 3. Neue Lüfter-Einträge hinzufügen
        if on_minutes or off_minutes:
            new_crontab_lines.append(CRON_IDENTIFIER + " START")
            # Aufbau des Cron-Befehls: [Minuten] [Stunden] * * * [PYTHON_PATH] [LUEFTER_SCRIPT] [Command]
            if on_minutes:
                new_crontab_lines.append(f"{on_minutes} * * * * {PYTHON_PATH} {LUEFTER_SCRIPT_PATH} on")
            if off_minutes:
                new_crontab_lines.append(f"{off_minutes} * * * * {PYTHON_PATH} {LUEFTER_SCRIPT_PATH} off")
            new_crontab_lines.append(CRON_IDENTIFIER + " END")

        # 4. Neue Crontab schreiben
        new_crontab = "\n".join(new_crontab_lines) + "\n"
        
        # pipe den neuen Inhalt an 'crontab -'
        process = subprocess.run(['crontab', '-'], input=new_crontab, encoding='utf-8', check=True, user=CRON_USER)

        print(f"Crontab erfolgreich aktualisiert für Benutzer {CRON_USER}.")
        return True, "Cronjobs erfolgreich aktualisiert und gespeichert!"
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Fehler beim Aktualisieren der Crontab: {e.stderr}"
        print(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Unerwarteter Fehler im Crontab-Update: {e}"
        print(error_msg)
        return False, error_msg

# --- DS18B20 Logik (Unverändert) ---
base_dir = '/sys/bus/w1/devices/'
device_folder = ''
device_file = ''

def find_ds18b20():
    """Findet den Temperatursensor beim Start."""
    global device_folder, device_file
    try:
        folders = [f for f in os.listdir(base_dir) if f.startswith('28-')]
        if folders:
            device_folder = os.path.join(base_dir, folders[0])
            device_file = os.path.join(device_folder, 'w1_slave')
            return True
        else:
            return False
    except Exception:
        return False

def read_temp_raw():
    """Liest die Rohdaten vom Sensor."""
    try:
        if not device_file: find_ds18b20()
        with open(device_file, 'r') as f: return f.readlines()
    except Exception: return None

def read_temp():
    """Konvertiert die Rohdaten in Celsius."""
    lines = read_temp_raw()
    if lines is None: return "N/A"
    while lines[0].strip()[-3:] != 'YES':
        time.sleep(0.2)
        lines = read_temp_raw()
        if lines is None: return "N/A"
    equals_pos = lines[1].find('t=')
    if equals_pos != -1:
        temp_string = lines[1][equals_pos+2:]
        return round(float(temp_string) / 1000.0, 2)
    return "N/A"


# --- Kamera Logik (Unverändert) ---
@app.route('/latest_photo')
def latest_photo():
    """Liefert das neueste Bild vom Dateisystem."""
    if os.path.exists(LATEST_PHOTO_PATH):
        return send_from_directory(PHOTO_DIR, 'latest_photo.jpg', mimetype='image/jpeg')
    else:
        return "No image available. Run update_camera_image.py.", 503


# --- API Endpunkt für Temperaturdaten (Unverändert) ---
@app.route('/api/temperature_data')
def get_temperature_data():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        hours = request.args.get('hours', type=int, default=24)
        time_ago = datetime.datetime.now() - datetime.timedelta(hours=hours)
        time_ago_iso = time_ago.isoformat()
        cursor.execute("SELECT timestamp, value FROM temperatures WHERE timestamp >= ? ORDER BY timestamp ASC", (time_ago_iso,))
        data = cursor.fetchall()

        if not data:
            # Fallback bei leeren Daten
            labels = []
            values = []
            start_time = datetime.datetime.now() - datetime.timedelta(hours=hours)
            num_points = (hours * 12)
            for i in range(num_points):
                point_time = start_time + datetime.timedelta(minutes=i * 5)
                labels.append(point_time.isoformat())
                sample_temp = 22.0 + (i % 20 - 10) * 0.2 + (i % 5 - 2.5) * 0.5
                values.append(round(sample_temp, 2))
            return jsonify({'labels': labels, 'values': values})

        labels = [row[0] for row in data]
        values = [row[1] for row in data]
        return jsonify({'labels': labels, 'values': values})

    except sqlite3.Error as e:
        # Fallback auch bei DB-Fehlern
        hours = request.args.get('hours', type=int, default=24)
        labels = []; values = []
        start_time = datetime.datetime.now() - datetime.timedelta(hours=hours)
        num_points = (hours * 12)
        for i in range(num_points):
            point_time = start_time + datetime.timedelta(minutes=i * 5)
            labels.append(point_time.isoformat())
            sample_temp = 22.0 + (i % 20 - 10) * 0.2 + (i % 5 - 2.5) * 0.5
            values.append(round(sample_temp, 2))
        return jsonify({'labels': labels, 'values': values}), 500
    finally:
        if conn: conn.close()

# --- API Endpunkt für Lüfter-Logs ---
@app.route('/api/luefter_logs')
def get_luefter_logs():
    """Liefert die letzten 20 Lüfter-Logs für die Anzeige."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Hole die letzten 20 Einträge in umgekehrter Reihenfolge (neueste zuerst)
        cursor.execute("SELECT timestamp, action, status FROM luefter_logs ORDER BY id DESC LIMIT 20")
        logs = cursor.fetchall()
        
        # Formatiere die Logs für JSON-Antwort
        log_list = []
        for ts, action, status in logs:
            log_list.append({
                'timestamp': datetime.datetime.fromisoformat(ts).strftime('%Y-%m-%d %H:%M:%S'),
                'action': action,
                'status': status
            })
        return jsonify(log_list)
    except sqlite3.Error as e:
        print(f"Datenbankfehler beim Abruf der Logs: {e}")
        return jsonify([]), 500
    finally:
        if conn: conn.close()

# --- API Endpunkt für Lüfter-Einstellungen ---
@app.route('/api/luefter_settings', methods=['POST'])
def save_luefter_settings():
    """Speichert neue Cron-Minuten in der DB und aktualisiert die Crontab."""
    data = request.get_json()
    on_minutes = data.get('on_minutes', '').strip()
    off_minutes = data.get('off_minutes', '').strip()

    # Validierung: Prüfen, ob die Minutenliste gültig ist (Zahlen und Kommas)
    minute_pattern = re.compile(r'^(\*|([0-5]?\d)(,[0-5]?\d)*)?$')
    if not (minute_pattern.match(on_minutes) and minute_pattern.match(off_minutes)):
        return jsonify({'error': 'Ungültiges Format. Nur Zahlen von 0-59 und Kommas erlaubt.'}), 400
    
    # Speichern der Einstellungen in der Datenbank
    save_setting('luefter_on_minutes', on_minutes)
    save_setting('luefter_off_minutes', off_minutes)
    
    # Crontab aktualisieren
    success, message = update_crontab(on_minutes, off_minutes)
    
    if success:
        return jsonify({'message': message})
    else:
        return jsonify({'error': message}), 500


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
    
    # 3. Lüfter Cron Einstellungen abrufen
    luefter_settings = get_settings()

    conn = None
    luefter_logs = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Hole initial die letzten 10 Logs
        cursor.execute("SELECT timestamp, action, status FROM luefter_logs ORDER BY id DESC LIMIT 10")
        logs = cursor.fetchall()
        for ts, action, status in logs:
            luefter_logs.append({
                'timestamp': datetime.datetime.fromisoformat(ts).strftime('%Y-%m-%d %H:%M:%S'),
                'action': action,
                'status': status
            })
    except sqlite3.Error:
        pass # Ignoriere Fehler, falls DB nicht initialisiert ist
    finally:
        if conn: conn.close()


    return render_template('index.html',
                           current_time=current_time,
                           current_date=current_date,
                           temperature=temperature_pi,
                           temp_zelt=temp_zelt,
                           hum_zelt=hum_zelt,
                           light_power=light_power,
                           # Lüftersteuerung Variablen
                           luefter_on_minutes=luefter_settings['on_minutes'],
                           luefter_off_minutes=luefter_settings['off_minutes'],
                           luefter_logs=luefter_logs)

@app.route('/create_timelapse', methods=['POST'])
def create_timelapse():
    """Erstellt ein Zeitraffervideo aus den archivierten Bildern."""
    # (Unveränderte Logik für Zeitraffererstellung)
    os.makedirs(PHOTO_DIR, exist_ok=True)
    os.makedirs(TIMELAPSE_DIR, exist_ok=True)
    
    for f in glob.glob(os.path.join(TIMELAPSE_DIR, 'temp_*.jpg')): os.remove(f)
    photos = sorted(glob.glob(os.path.join(PHOTO_DIR, 'archive_photo_*.jpg')))
    
    if not photos:
        return render_template('timelapse_status.html', message="Keine archivierten Fotos gefunden.", video_url=None), 404
        
    for i, photo_path in enumerate(photos):
        link_path = os.path.join(TIMELAPSE_DIR, f"temp_{i:05d}.jpg")
        try: os.symlink(photo_path, link_path)
        except FileExistsError: pass
            
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_video = os.path.join(TIMELAPSE_DIR, f"timelapse_{timestamp}.mp4")
    
    command = [
        os.environ.get('FFMPEG_PATH', 'ffmpeg'), "-y", "-framerate", "10",
        "-i", os.path.join(TIMELAPSE_DIR, "temp_%05d.jpg"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", output_video
    ]
    
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
        message = f"Zeitraffer '{os.path.basename(output_video)}' erfolgreich erstellt!"
    except subprocess.CalledProcessError as e:
        message = f"Fehler: {e.stderr}"
    except FileNotFoundError:
        message = "FFmpeg nicht gefunden."
    finally:
        for f in glob.glob(os.path.join(TIMELAPSE_DIR, 'temp_*.jpg')): os.remove(f)
            
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
    # Initialisiere die DB, falls sie noch nicht existiert
    try:
        conn = get_db_connection()
        from lueftung import initialize_db # Importiere die DB-Initialisierung aus lueftung.py
        initialize_db()
    except Exception as e:
        print(f"WARNUNG: DB konnte nicht initialisiert werden, da lueftung.py fehlt oder ein Fehler auftrat: {e}")

    app.run(host='0.0.0.0', port=8000, debug=True)
