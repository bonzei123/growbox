from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
import datetime
import os
import glob
import subprocess
import time
import sqlite3

app = Flask(__name__)

# --- Datenbank Konfiguration ---
DB_NAME = 'growbox_data.db'

# --- DS18B20 Temperatursensor Konfiguration (wie gehabt) ---
base_dir = '/sys/bus/w1/devices/'
device_folder = ''
device_file = ''


def find_ds18b20():
    try:
        folders = [f for f in os.listdir(base_dir) if f.startswith('28-')]
        if folders:
            global device_folder, device_file
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
    lines = read_temp_raw()
    if lines is None:
        return "N/A"

    while lines[0].strip()[-3:] != 'YES':
        time.sleep(0.2)
        lines = read_temp_raw()
        if lines is None:
            return "N/A"

    equals_pos = lines[1].find('t=')
    if equals_pos != -1:
        temp_string = lines[1][equals_pos + 2:]
        temp_c = float(temp_string) / 1000.0
        return round(temp_c, 2)
    return "N/A"


# --- Kamera- und Zeitraffer-Konfiguration (wie gehabt) ---
PHOTO_DIR = "/home/pi/growbox_photos"
TIMELAPSE_DIR = "/home/pi/growbox_timelapses"
MJPG_STREAM_URL = "http://"
MJPG_STREAM_PORT = 8080

os.makedirs(TIMELAPSE_DIR, exist_ok=True)
os.makedirs(PHOTO_DIR, exist_ok=True)


# --- API-Endpunkt für Temperaturdaten MIT FALLBACK ---
@app.route('/api/temperature_data')
def get_temperature_data():
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        hours = request.args.get('hours', type=int, default=24)

        time_ago = datetime.datetime.now() - datetime.timedelta(hours=hours)
        time_ago_iso = time_ago.isoformat()

        cursor.execute("SELECT timestamp, value FROM temperatures WHERE timestamp >= ? ORDER BY timestamp ASC",
                       (time_ago_iso,))
        data = cursor.fetchall()

        # --- FALLBACK-LOGIK HIER ---
        if not data:  # Wenn keine echten Daten gefunden wurden
            print(f"Keine echten Temperaturdaten für die letzten {hours} Stunden gefunden. Erzeuge Sample-Daten.")
            labels = []
            values = []
            start_time = datetime.datetime.now() - datetime.timedelta(hours=hours)

            # Erzeuge Sample-Datenpunkte (z.B. alle 5 Minuten)
            num_points = (hours * 60) // 5  # Anzahl der Punkte

            for i in range(num_points):
                point_time = start_time + datetime.timedelta(minutes=i * 5)
                labels.append(point_time.isoformat())

                # Beispiel für eine "realistische" Sample-Temperatur (z.B. 20-25 Grad mit leichter Schwankung)
                # Hier kannst du komplexere Muster einbauen, wenn du möchtest
                sample_temp = 22.0 + (i % 20 - 10) * 0.2 + (i % 5 - 2.5) * 0.5  # Leichte Schwankung
                values.append(round(sample_temp, 2))

            return jsonify({'labels': labels, 'values': values})

        # --- Echte Daten verarbeiten (wenn vorhanden) ---
        labels = [row[0] for row in data]
        values = [row[1] for row in data]

        return jsonify({'labels': labels, 'values': values})

    except sqlite3.Error as e:
        print(f"API Error: Fehler beim Lesen aus der Datenbank: {e}")
        # Auch hier einen Fallback anbieten, wenn die DB-Verbindung/Abfrage fehlschlägt
        # Dies ist hilfreich, wenn die DB-Datei beschädigt ist oder nicht gefunden wird
        print("Erzeuge Sample-Daten aufgrund eines Datenbankfehlers.")
        labels = []
        values = []
        hours = request.args.get('hours', type=int,
                                 default=24)  # Fallback für Stunden, falls der erste Fehler schon bei hours auftrat
        start_time = datetime.datetime.now() - datetime.timedelta(hours=hours)
        num_points = (hours * 60) // 5
        for i in range(num_points):
            point_time = start_time + datetime.timedelta(minutes=i * 5)
            labels.append(point_time.isoformat())
            sample_temp = 22.0 + (i % 20 - 10) * 0.2 + (i % 5 - 2.5) * 0.5
            values.append(round(sample_temp, 2))
        return jsonify({'labels': labels, 'values': values}), 500  # Status 500 für internen Serverfehler

    finally:
        if conn:
            conn.close()


# --- Webserver Routen (index, create_timelapse, list_timelapses, download_timelapse) wie gehabt ---
@app.route('/')
def index():
    global MJPG_STREAM_URL
    if not MJPG_STREAM_URL or MJPG_STREAM_URL == "http://":
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            pi_ip = s.getsockname()[0]
            s.close()
            MJPG_STREAM_URL = f"http://{pi_ip}:{MJPG_STREAM_PORT}/?action=stream"
        except Exception as e:
            print(f"Konnte Pi IP nicht ermitteln: {e}. Verwende Platzhalter.")
            MJPG_STREAM_URL = f"http://YOUR_PI_IP:{MJPG_STREAM_PORT}/?action=stream"

    current_time = datetime.datetime.now().strftime("%H:%M:%S")
    temperature_c = read_temp()

    return render_template('index.html',
                           current_time=current_time,
                           temperature=temperature_c,
                           mjpg_stream_url=MJPG_STREAM_URL)


@app.route('/create_timelapse', methods=['POST'])
def create_timelapse():
    temp_files = glob.glob(os.path.join(TIMELAPSE_DIR, 'temp_*.jpg'))
    for f in temp_files:
        os.remove(f)

    photos = sorted(glob.glob(os.path.join(PHOTO_DIR, '*.jpg')))
    if not photos:
        return render_template('timelapse_status.html',
                               message="Keine Fotos gefunden, um einen Zeitraffer zu erstellen.", video_url=None), 404

    for i, photo_path in enumerate(photos):
        link_path = os.path.join(TIMELAPSE_DIR, f"temp_{i:05d}.jpg")
        try:
            os.symlink(photo_path, link_path)
        except FileExistsError:
            pass

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_video = os.path.join(TIMELAPSE_DIR, f"timelapse_{timestamp}.mp4")

    command = [
        "ffmpeg", "-y",
        "-framerate", "10",
        "-i", os.path.join(TIMELAPSE_DIR, "temp_%05d.jpg"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", "23",
        output_video
    ]
    print(f"Starte ffmpeg: {' '.join(command)}")

    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        print(f"ffmpeg stdout: {result.stdout}")
        print(f"ffmpeg stderr: {result.stderr}")
        message = f"Zeitraffer '{os.path.basename(output_video)}' erfolgreich erstellt!"
    except subprocess.CalledProcessError as e:
        print(f"Fehler beim Erstellen des Zeitraffers: {e}")
        print(f"ffmpeg stdout: {e.stdout}")
        print(f"ffmpeg stderr: {e.stderr}")
        message = f"Fehler beim Erstellen des Zeitraffers: {e.stderr}"
    except FileNotFoundError:
        message = "FFmpeg ist nicht installiert. Bitte 'sudo apt-get install ffmpeg' ausführen."
    finally:
        for f in glob.glob(os.path.join(TIMELAPSE_DIR, 'temp_*.jpg')):
            os.remove(f)

    return render_template('timelapse_status.html', message=message, video_url=os.path.basename(output_video))


@app.route('/timelapses')
def list_timelapses():
    timelapses = sorted(os.listdir(TIMELAPSE_DIR), reverse=True)
    return render_template('timelapse_list.html', timelapses=timelapses)


@app.route('/timelapses/<filename>')
def download_timelapse(filename):
    return send_from_directory(TIMELAPSE_DIR, filename, as_attachment=True)


if __name__ == '__main__':
    find_ds18b20()
    app.run(host='0.0.0.0', port=8000, debug=True)