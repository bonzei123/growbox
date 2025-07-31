from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify, Response
import datetime
import os
import glob
import subprocess
import time
import sqlite3
from picamera2 import Picamera2, MappedArray
import cv2
import numpy as np
import threading
import io

# I2C-Initialisierung direkt mit smbus
import smbus
# Wir gehen davon aus, dass wir den I2C-Bus 4 wie in der Konfiguration nutzen
I2C_BUS = smbus.SMBus(4)

# Importiere nur die benötigten ADS-Bibliotheken
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn

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
        temp_string = lines[1][equals_pos+2:]
        temp_c = float(temp_string) / 1000.0
        return round(temp_c, 2)
    return "N/A"

# --- Kamera- und Zeitraffer-Konfiguration (wie gehabt) ---
PHOTO_DIR = "/home/pi/growbox_photos"
TIMELAPSE_DIR = "/home/pi/growbox_timelapses"

os.makedirs(TIMELAPSE_DIR, exist_ok=True)
os.makedirs(PHOTO_DIR, exist_ok=True)

# --- NEU: ADS1115 direkt initialisieren ---
ads = ADS.ADS1115(I2C_BUS)
chan_ph = AnalogIn(ads, ADS.P0)
chan_ec = AnalogIn(ads, ADS.A1) # Beachte, dass wir hier auch den EC-Sensor an A1 anschließen

# --- Picamera2 Globales Objekt und Lock (wie gehabt) ---
picam2_stream = None
output_frame = None
lock = threading.Lock()

def start_camera_stream():
    global picam2_stream, output_frame
    picam2_stream = Picamera2()
    camera_config = picam2_stream.create_video_configuration(lores={"size": (640, 480)}, display="lores")
    picam2_stream.configure(camera_config)
    
    picam2_stream.start()
    print("Picamera2 Stream gestartet.")

    try:
        while True:
            buffer = picam2_stream.capture_array("lores")
            ret, jpeg = cv2.imencode('.jpg', buffer)
            if not ret:
                continue
            
            with lock:
                output_frame = jpeg.tobytes()
            
            time.sleep(0.05)
    except Exception as e:
        print(f"Fehler im Kamera-Stream-Thread: {e}")
    finally:
        if picam2_stream:
            picam2_stream.stop()
            picam2_stream.release()
            print("Picamera2 Stream beendet.")

camera_thread = threading.Thread(target=start_camera_stream)
camera_thread.daemon = True
camera_thread.start()

@app.route('/video_feed')
def video_feed():
    def generate():
        global output_frame, lock
        while True:
            with lock:
                if output_frame is not None:
                    frame = output_frame
                else:
                    frame = None
            
            if frame is not None:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(0.05)

    return Response(generate(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


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
            print(f"Keine echten Temperaturdaten für die letzten {hours} Stunden gefunden. Erzeuge Sample-Daten.")
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
        print(f"API Error: Fehler beim Lesen aus der Datenbank: {e}")
        print("Erzeuge Sample-Daten aufgrund eines Datenbankfehlers.")
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

@app.route('/')
def index():
    stream_url = url_for('video_feed')
    
    current_time = datetime.datetime.now().strftime("%H:%M:%S")
    temperature_c = read_temp()

    return render_template('index.html',
                           current_time=current_time,
                           temperature=temperature_c,
                           mjpg_stream_url=stream_url)

@app.route('/create_timelapse', methods=['POST'])
def create_timelapse():
    temp_files = glob.glob(os.path.join(TIMELAPSE_DIR, 'temp_*.jpg'))
    for f in temp_files:
        os.remove(f)

    photos = sorted(glob.glob(os.path.join(PHOTO_DIR, '*.jpg')))
    if not photos:
        return render_template('timelapse_status.html', message="Keine Fotos gefunden, um einen Zeitraffer zu erstellen.", video_url=None), 404

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
