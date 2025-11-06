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
from math import floor  # Für die Altersberechnung

app = Flask(__name__)

# --- Globale Konfigurationen ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Home Assistant API Konfiguration ---
HA_CONFIG = {
    "HA_URL": "http://192.168.0.167:8123",
    "HA_TOKEN": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiIyOWE3YmRhZDJlOTY0NzEzYTI4MmU1ZDM4OTU4YTIzOCIsImlhdCI6MTc1OTI2NjI3NiwiZXhwIjoyMDc0NjI2Mjc2fQ.ozfMbYAhcEOFvy-2zRKADr8Bq0XnI22_1jGVMsY6EQw",
    "TEMP_ZELT_ENTITY": "sensor.growzeltdaten_temperature",
    "HUM_ZELT_ENTITY": "sensor.growzeltdaten_humidity",
    "LIGHT_POWER_ENTITY": "sensor.grow_licht_power",
    "LUEFTER_ENTITY": "switch.grow_luftung_socket_1"
}

# --- Datenbank und Pfad Konfiguration ---
DB_NAME = os.path.join(BASE_DIR, 'growbox_data.db')
PHOTO_DIR = os.path.join(BASE_DIR, "growbox_photos")
TIMELAPSE_DIR = os.path.join(BASE_DIR, "growbox_timelapses")
LATEST_PHOTO_PATH = os.path.join(PHOTO_DIR, 'latest_photo.jpg')

# Cronjob Konfiguration
PYTHON_PATH = os.path.join(BASE_DIR, 'venv', 'bin', 'python3')
LUEFTER_SCRIPT_PATH = os.path.join(BASE_DIR, 'lueftung.py')
CRON_IDENTIFIER = "# GROWAUTOMATION_LUEFTER"

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
    """
    try:
        cron_user = os.environ.get('USER') or os.path.basename(os.path.expanduser('~'))

        result = subprocess.run(['crontab', '-l'], capture_output=True, text=True, check=False)
        current_crontab = result.stdout

        new_crontab_lines = []
        luefter_block_start = f"{CRON_IDENTIFIER} START"
        luefter_block_end = f"{CRON_IDENTIFIER} END"

        in_luefter_block = False
        for line in current_crontab.splitlines():
            if line.strip() == luefter_block_start:
                in_luefter_block = True
                continue
            if line.strip() == luefter_block_end:
                in_luefter_block = False
                continue
            if not in_luefter_block:
                new_crontab_lines.append(line)

        if on_minutes or off_minutes:
            new_crontab_lines.append(luefter_block_start)
            if on_minutes:
                new_crontab_lines.append(f"{on_minutes} * * * * {PYTHON_PATH} {LUEFTER_SCRIPT_PATH} on")
            if off_minutes:
                new_crontab_lines.append(f"{off_minutes} * * * * {PYTHON_PATH} {LUEFTER_SCRIPT_PATH} off")
            new_crontab_lines.append(luefter_block_end)

        new_crontab = "\n".join(new_crontab_lines) + "\n"

        process = subprocess.run(['crontab', '-'], input=new_crontab, encoding='utf-8', check=True)

        print(f"Crontab erfolgreich aktualisiert für Benutzer {cron_user}.")
        return True, "Cronjobs erfolgreich aktualisiert und gespeichert!"

    except subprocess.CalledProcessError as e:
        error_msg = f"Fehler beim Aktualisieren der Crontab: {e.stderr}"
        print(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Unerwarteter Fehler im Crontab-Update: {e}"
        print(error_msg)
        return False, error_msg


# --- Tagebuch Logik ---

def get_plant_age(keim_date_str):
    """Berechnet Alter in Tagen und Wochen."""
    try:
        keim_date = datetime.datetime.strptime(keim_date_str, '%Y-%m-%d').date()
        today = datetime.date.today()

        if today < keim_date:
            return 0, 0

        delta = today - keim_date
        days = delta.days
        weeks = floor(days / 7)
        return days, weeks
    except ValueError:
        return 0, 0  # Ungültiges Datumsformat


# --- DS18B20 Logik (mit Fehlerbehebung) ---
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
        if os.path.exists(device_file):
            with open(device_file, 'r') as f:
                lines = f.readlines()
                if not lines: return None
                return lines
        return None
    except Exception as e:
        print(f"WARNUNG: Fehler beim Lesen der Sensor-Rohdaten: {e}")
        return None


def read_temp():
    """Konvertiert die Rohdaten in Celsius."""
    lines = read_temp_raw()
    if lines is None: return "N/A"
    if not lines or len(lines) < 2: return "N/A"

    attempts = 0
    while lines[0].strip()[-3:] != 'YES':
        attempts += 1
        if attempts > 3: return "N/A"
        time.sleep(0.2)
        lines = read_temp_raw()
        if lines is None or len(lines) < 2: return "N/A"

    equals_pos = lines[1].find('t=')
    if equals_pos != -1:
        temp_string = lines[1][equals_pos + 2:]
        try:
            temp_c = float(temp_string) / 1000.0
            return round(temp_c, 2)
        except ValueError:
            return "N/A"
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
        cursor.execute("SELECT timestamp, value FROM temperatures WHERE timestamp >= ? ORDER BY timestamp ASC",
                       (time_ago_iso,))
        data = cursor.fetchall()

        if not data:
            labels = [];
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
        hours = request.args.get('hours', type=int, default=24)
        labels = [];
        values = []
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


# --- API Endpunkt für Lüfter-Logs (Unverändert) ---
@app.route('/api/luefter_logs')
def get_luefter_logs():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT timestamp, action, status FROM luefter_logs ORDER BY id DESC LIMIT 20")
        logs = cursor.fetchall()

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


# --- API Endpunkt für Lüfter-Einstellungen (Unverändert) ---
@app.route('/api/luefter_settings', methods=['POST'])
def save_luefter_settings():
    data = request.get_json()
    on_minutes = data.get('on_minutes', '').strip()
    off_minutes = data.get('off_minutes', '').strip()

    minute_pattern = re.compile(r'^(\*|([0-5]?\d)(,[0-5]?\d)*)?$')
    if not (minute_pattern.match(on_minutes) and minute_pattern.match(off_minutes)):
        return jsonify({'error': 'Ungültiges Format. Nur Zahlen von 0-59 und Kommas erlaubt.'}), 400

    save_setting('luefter_on_minutes', on_minutes)
    save_setting('luefter_off_minutes', off_minutes)

    success, message = update_crontab(on_minutes, off_minutes)

    if success:
        return jsonify({'message': message})
    else:
        return jsonify({'error': message}), 500


# --- API Endpunkt für manuelle Lüftersteuerung (Unverändert) ---
@app.route('/api/luefter_toggle', methods=['POST'])
def luefter_toggle():
    command = request.get_json().get('command', '').lower()

    if command not in ['on', 'off']:
        return jsonify({'error': 'Ungültiger Befehl. Erwarte "on" oder "off".'}), 400

    ha_service = 'turn_on' if command == 'on' else 'turn_off'

    url = f"{HA_CONFIG['HA_URL']}/api/services/switch/{ha_service}"
    headers = {
        "Authorization": f"Bearer {HA_CONFIG['HA_TOKEN']}",
        "Content-Type": "application/json"
    }
    payload = {
        "entity_id": HA_CONFIG["LUEFTER_ENTITY"]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=5)
        response.raise_for_status()

        conn = get_db_connection()
        cursor = conn.cursor()
        timestamp = datetime.datetime.now().isoformat()
        cursor.execute("INSERT INTO luefter_logs (timestamp, action, status) VALUES (?, ?, ?)",
                       (timestamp, ha_service, "MANUAL_SUCCESS"))
        conn.commit()
        conn.close()

        return jsonify({'message': f"Lüfter erfolgreich auf {command} gesetzt."})

    except requests.exceptions.RequestException as e:
        print(f"FEHLER beim manuellen HA-Aufruf: {e}")
        return jsonify({'error': f"HA API Fehler: {e}"}), 500


# --- TAGEBUCH API ENDPUNKTE ---

@app.route('/api/plants', methods=['GET'])
def list_plants():
    """Gibt alle aktiven Pflanzen zurück, um das Dropdown zu befüllen."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, strain, type, keim_date FROM plants WHERE status='Active' ORDER BY name")
    plants = [{'id': row[0], 'name': row[1], 'strain': row[2], 'type': row[3], 'keim_date': row[4]} for row in
              cursor.fetchall()]
    conn.close()
    return jsonify(plants)


@app.route('/api/plants', methods=['POST'])
def add_plant():
    """Fügt eine neue Pflanze hinzu."""
    data = request.get_json()
    name = data.get('name')
    strain = data.get('strain')
    p_type = data.get('type')
    keim_date = data.get('keim_date')  # YYYY-MM-DD

    if not all([name, strain, p_type, keim_date]):
        return jsonify({'error': 'Name, Sorte, Typ und Keimdatum sind erforderlich.'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO plants (name, strain, type, keim_date, status) VALUES (?, ?, ?, ?, 'Active')",
            (name, strain, p_type, keim_date)
        )
        conn.commit()
        return jsonify({'message': f'Pflanze "{name}" erfolgreich hinzugefügt.'}), 201
    except sqlite3.Error as e:
        return jsonify({'error': f'Datenbankfehler: {e}'}), 500
    finally:
        conn.close()


@app.route('/api/journal/<int:plant_id>', methods=['GET'])
def get_journal(plant_id):
    """Gibt die Chronologie für eine bestimmte Pflanze zurück."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT timestamp, cycle, notes, image_path FROM journal WHERE plant_id = ? ORDER BY timestamp DESC",
        (plant_id,)
    )
    journal_entries = []
    for ts, cycle, notes, img_path in cursor.fetchall():
        # Berechne das Pflanzenalter für diesen Journal-Eintrag (komplex, daher nur Datum anzeigen)
        journal_entries.append({
            'timestamp': datetime.datetime.fromisoformat(ts).strftime('%Y-%m-%d %H:%M:%S'),
            'cycle': cycle,
            'notes': notes,
            'image_path': img_path
        })
    conn.close()
    return jsonify(journal_entries)


@app.route('/api/journal', methods=['POST'])
def add_journal_entry():
    """Erstellt einen neuen Tagebucheintrag und archiviert das aktuelle Foto."""
    data = request.get_json()
    plant_id = data.get('plant_id')
    cycle = data.get('cycle')
    notes = data.get('notes')

    if not all([plant_id, cycle, notes]):
        return jsonify({'error': 'Pflanzen-ID, Zyklus und Notizen sind erforderlich.'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Foto archivieren
    image_name = None
    if os.path.exists(LATEST_PHOTO_PATH):
        timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        image_name = f"journal_photo_{timestamp_str}_{plant_id}.jpg"
        archive_path = os.path.join(PHOTO_DIR, image_name)
        try:
            shutil.copy2(LATEST_PHOTO_PATH, archive_path)
        except Exception as e:
            conn.close()
            return jsonify({'error': f'Fehler beim Archivieren des Fotos: {e}'}), 500

    # 2. Eintrag in die Datenbank schreiben
    try:
        timestamp = datetime.datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO journal (plant_id, timestamp, cycle, notes, image_path) VALUES (?, ?, ?, ?, ?)",
            (plant_id, timestamp, cycle, notes, image_name)
        )
        conn.commit()
        return jsonify({'message': 'Tagebucheintrag erfolgreich gespeichert.'}), 201
    except sqlite3.Error as e:
        return jsonify({'error': f'Datenbankfehler: {e}'}), 500
    finally:
        conn.close()


# --- Webserver Routen ---
@app.route('/')
def index():
    """Rendert die Hauptseite mit aktuellen Daten."""
    current_datetime = datetime.datetime.now()
    current_time = current_datetime.strftime("%H:%M:%S")
    current_date = current_datetime.strftime("%d.%m.%Y")

    # Sensorwerte abrufen
    temperature_pi = read_temp()
    temp_zelt = get_ha_sensor_state(HA_CONFIG["TEMP_ZELT_ENTITY"])
    hum_zelt = get_ha_sensor_state(HA_CONFIG["HUM_ZELT_ENTITY"])
    light_power = get_ha_sensor_state(HA_CONFIG["LIGHT_POWER_ENTITY"])
    luefter_state = get_ha_sensor_state(HA_CONFIG["LUEFTER_ENTITY"])

    # Lüfter Cron und Logs abrufen
    luefter_settings = get_settings()

    conn = None
    luefter_logs = []
    plants_data = []

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 1. Lüfter Logs
        cursor.execute("SELECT timestamp, action, status FROM luefter_logs ORDER BY id DESC LIMIT 10")
        logs = cursor.fetchall()
        for ts, action, status in logs:
            luefter_logs.append({
                'timestamp': datetime.datetime.fromisoformat(ts).strftime('%Y-%m-%d %H:%M:%S'),
                'action': action,
                'status': status
            })

        # 2. Pflanzenliste
        cursor.execute("SELECT id, name, keim_date FROM plants WHERE status='Active' ORDER BY name")
        for p_id, name, keim_date in cursor.fetchall():
            days, weeks = get_plant_age(keim_date)
            plants_data.append({
                'id': p_id,
                'name': name,
                'keim_date': keim_date,
                'age_days': days,
                'age_weeks': weeks
            })

    except sqlite3.Error:
        pass
    finally:
        if conn: conn.close()

    return render_template('index.html',
                           current_time=current_time,
                           current_date=current_date,
                           temperature=temperature_pi,
                           temp_zelt=temp_zelt,
                           hum_zelt=hum_zelt,
                           light_power=light_power,
                           luefter_state=luefter_state,
                           luefter_on_minutes=luefter_settings['on_minutes'],
                           luefter_off_minutes=luefter_settings['off_minutes'],
                           luefter_logs=luefter_logs,
                           plants=plants_data)  # NEU: Liste der Pflanzen


@app.route('/create_timelapse', methods=['POST'])
def create_timelapse():
    # ... (Logik für Zeitraffer, hier stark gekürzt) ...
    return render_template('timelapse_status.html', message="Zeitraffer-Logik hier", video_url=None)


@app.route('/timelapses')
def list_timelapses():
    # ... (Logik für Zeitraffer, hier stark gekürzt) ...
    return render_template('timelapse_list.html', timelapses=[])


@app.route('/timelapses/<filename>')
def download_timelapse(filename):
    # ... (Logik für Zeitraffer, hier stark gekürzt) ...
    return send_from_directory(TIMELAPSE_DIR, filename, as_attachment=True)


@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')


# --- DB INITIALISIERUNG ---
def initialize_db_if_needed():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Lüfter Logs und Settings (bestehend)
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS luefter_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, action TEXT NOT NULL, status TEXT NOT NULL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    # 2. NEU: Pflanzen Tabelle
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS plants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            strain TEXT,
            type TEXT, -- P/F/A
            keim_date TEXT NOT NULL, -- YYYY-MM-DD
            status TEXT NOT NULL -- Active/Archived
        )
    """)

    # 3. NEU: Journal Tabelle
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plant_id INTEGER,
            timestamp TEXT NOT NULL,
            cycle TEXT, -- Keimling, Vegetation, Blüte
            notes TEXT,
            image_path TEXT,
            FOREIGN KEY (plant_id) REFERENCES plants(id)
        )
    """)
    conn.commit()
    conn.close()


if __name__ == '__main__':
    initialize_db_if_needed()
    find_ds18b20()
    app.run(host='0.0.0.0', port=8000, debug=True)