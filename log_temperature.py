import sqlite3
import datetime
import time
import os

DB_NAME = 'growbox_data.db' # Muss mit dem Namen in setup_database.py übereinstimmen

# --- DS18B20 Temperatursensor Konfiguration (vom app.py übernommen) ---
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
            print("LOG_TEMP: No DS18B20 sensor found.")
            return False
    except FileNotFoundError:
        print("LOG_TEMP: 1-Wire directory not found. Is 1-Wire enabled?")
        return False
    except Exception as e:
        print(f"LOG_TEMP: Error finding DS18B20: {e}")
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
        print(f"LOG_TEMP: Error reading raw temp: {e}")
        return None

def read_temp():
    lines = read_temp_raw()
    if lines is None:
        return None

    while lines[0].strip()[-3:] != 'YES':
        time.sleep(0.2)
        lines = read_temp_raw()
        if lines is None:
            return None

    equals_pos = lines[1].find('t=')
    if equals_pos != -1:
        temp_string = lines[1][equals_pos+2:]
        temp_c = float(temp_string) / 1000.0
        return round(temp_c, 2)
    return None

# --- Daten in Datenbank speichern ---
def log_temperature_to_db():
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        temperature = read_temp()
        if temperature is not None and temperature != "N/A":
            timestamp = datetime.datetime.now().isoformat() # ISO-Format für Zeitstempel
            cursor.execute("INSERT INTO temperatures (timestamp, value) VALUES (?, ?)", (timestamp, temperature))
            conn.commit()
            print(f"LOG_TEMP: {timestamp} - Temperatur {temperature}°C in DB gespeichert.")
        else:
            print("LOG_TEMP: Konnte Temperatur nicht lesen. Nicht in DB gespeichert.")

    except sqlite3.Error as e:
        print(f"LOG_TEMP: Fehler beim Speichern in Datenbank: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    # Initialisiere den Sensor beim Start des Loggers
    find_ds18b20()
    # Logge die Temperatur einmal, wenn das Skript ausgeführt wird (für Cronjob)
    log_temperature_to_db()