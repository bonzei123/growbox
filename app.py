from flask import Flask, render_template, request, jsonify, Response, send_from_directory, url_for
import datetime
import os
import glob
import subprocess
import time
import sqlite3
import threading

app = Flask(__name__)

# --- Datenbank Konfiguration ---
DB_NAME = '/home/pi/growbox_monitor/growbox_data.db' # Absoluter Pfad

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
            return True
        else:
            print("No DS18B20 sensor found.")
            return False
    except FileNotFoundError:
        return False
    except Exception as e:
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
        temp_string = lines[1][equals_pos+2:]
        temp_c = float(temp_string) / 1000.0
        return round(temp_c, 2)
    return "N/A"

# --- ADS1115 direkt initialisieren (bleibt auskommentiert) ---
# ads = ADS.ADS1115(I2C_BUS)
# chan_ph = AnalogIn(ads, ADS.P0)
# chan_ec = AnalogIn(ads, ADS.A1)

# --- Kamera- und Zeitraffer-Konfiguration ---
PHOTO_DIR = "/home/pi/growbox_photos"
TIMELAPSE_DIR = "/home/pi/growbox_timelapses"
os.makedirs(TIMELAPSE_DIR, exist_ok=True)
os.makedirs(PHOTO_DIR, exist_ok=True)

# WICHTIG: Pfade anpassen
FFMPEG_PATH = "/usr/bin/ffmpeg"
RPICAM_STILL_PATH = "/usr/bin/rpicam-still"

# Pfad für das neueste Foto, das der Webserver anzeigt
LATEST_PHOTO_PATH = os.path.join(PHOTO_DIR, 'latest_photo.jpg')

# --- NEU: Routen für die Kamera-API (Status und Steuerung) ---
@app.route('/api/camera_status')
def camera_status():
    try:
        status_result = subprocess.run(['sudo', 'systemctl', 'is-active', 'camera-daemon.service'],
                                       capture_output=True, text=True, check=False)
        status = status_result.stdout.strip()
        if status == 'active':
            return jsonify({'status': 'active', 'message': 'Aktiv'})
        else:
            return jsonify({'status': 'inactive', 'message': 'Deaktiviert'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Fehler: {str(e)}'}), 500

@app.route('/api/camera_control/<action>', methods=['POST'])
def camera_control(action):
    if action not in ['start', 'stop']:
        return jsonify({'error': 'Invalid action'}), 400

    try:
        if action == 'start':
            subprocess.run(['sudo', 'systemctl', 'start', 'camera-daemon.service'], check=True)
            return jsonify({'status': 'success', 'message': 'Dienst gestartet'})
        elif action == 'stop':
            subprocess.run(['sudo', 'systemctl', 'stop', 'camera-daemon.service'], check=True)
            return jsonify({'status': 'success', 'message': 'Dienst gestoppt'})
    except subprocess.CalledProcessError as e:
        return jsonify({'status': 'error', 'message': f"Fehler bei der Steuerung: {e.stderr}"}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': f"Allgemeiner Fehler: {str(e)}"}), 500

# --- NEU: Route für das neueste Foto (wird vom Daemon erstellt) ---
@app.route('/latest_photo')
def latest_photo():
    if os.path.exists(LATEST_PHOTO_PATH):
        return send_from_directory(PHOTO_DIR, 'latest_photo.jpg', mimetype='image/jpeg')
    else:
        return "No image available", 503

# --- API-Endpunkt für Temperaturdaten MIT FALLBACK (wie gehabt) ---
@app.route('/api/temperature_data')
def get_temperature_data():
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        hours = request.args.get('hours', type=int, default=24)
        time_ago = datetime.datetime.now() - datetime.timedelta(hours=hours)
        time_ago_iso = time_ago.isoformat()
        cursor.execute("SELECT timestamp, value FROM temperatures WHERE timestamp >= ? ORDER BY timestamp ASC", (time_ago_iso,))
        data = cursor.fetchall()
        if not data:
            labels = []
            values = []
            start_time = datetime.datetime.now() - datetime.timedelta(hours=hours)
            num_points = (hours * 60) // 5
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
        labels = []
        values = []
        hours = request.args.get('hours', type=int, default=24)
        start_time = datetime.datetime.now() - datetime.timedelta(hours=hours)
        num_points = (hours * 60) // 5
        for i in range(num_points):
            point_time = start_time + datetime.timedelta(minutes=i * 5)
            labels.append(point_time.isoformat())
            sample_temp = 22.0 + (i % 20 - 10) * 0.2 + (i % 5 - 2.5) * 0.5
            values.append(round(sample_temp, 2))
        return jsonify({'labels': labels, 'values': values}), 500
    finally:
        if conn:
            conn.close()

# --- Webserver Routen (index, create_timelapse, list_timelapses, download_timelapse) ---
@app.route('/')
def index():
    stream_url = url_for('latest_photo')
    current_datetime = datetime.datetime.now()
    current_time = current_datetime.strftime("%H:%M:%S")
    current_date = current_datetime.strftime("%d.%m.%Y")
    temperature_c = read_temp()
    return render_template('index.html',
                           current_time=current_time,
                           current_date=current_date,
                           temperature=temperature_c,
                           mjpg_stream_url=stream_url)

@app.route('/create_timelapse', methods=['POST'])
def create_timelapse():
    os.makedirs(PHOTO_DIR, exist_ok=True)
    os.makedirs(TIMELAPSE_DIR, exist_ok=True)
    temp_files = glob.glob(os.path.join(TIMELAPSE_DIR, 'temp_*.jpg'))
    for f in temp_files:
        os.remove(f)
    photos = sorted(glob.glob(os.path.join(PHOTO_DIR, '*.jpg')))
    if not photos:
        return render_template('timelapse_status.html', message="No photos found to create a timelapse.", video_url=None), 404
    for i, photo_path in enumerate(photos):
        link_path = os.path.join(TIMELAPSE_DIR, f"temp_%05d.jpg")
        try:
            os.symlink(photo_path, link_path)
        except FileExistsError:
            pass
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_video = os.path.join(TIMELAPSE_DIR, f"timelapse_{timestamp}.mp4")
    command = [
        FFMPEG_PATH, "-y",
        "-framerate", "10",
        "-i", os.path.join(TIMELAPSE_DIR, "temp_%05d.jpg"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", "23",
        output_video
    ]
    print(f"Starting ffmpeg: {' '.join(command)}")
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        message = f"Timelapse '{os.path.basename(output_video)}' created successfully!"
    except subprocess.CalledProcessError as e:
        message = f"Error creating timelapse: {e.stderr}"
    except FileNotFoundError:
        message = "FFmpeg is not installed. Please run 'sudo apt-get install ffmpeg'."
    finally:
        for f in glob.glob(os.path.join(TIMELAPSE_DIR, 'temp_*.jpg')):
            os.remove(f)
    return render_template('timelapse_status.html', message=message, video_url=os.path.basename(output_video))

@app.route('/timelapses')
def list_timelapses():
    os.makedirs(TIMELAPSE_DIR, exist_ok=True)
    timelapses = sorted(os.listdir(TIMELAPSE_DIR), reverse=True)
    return render_template('timelapse_list.html', timelapses=timelapses)

@app.route('/timelapses/<filename>')
def download_timelapse(filename):
    os.makedirs(TIMELAPSE_DIR, exist_ok=True)
    return send_from_directory(TIMELAPSE_DIR, filename, as_attachment=True)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

if __name__ == '__main__':
    find_ds18b20()
    app.run(host='0.0.0.0', port=8000, debug=True)
