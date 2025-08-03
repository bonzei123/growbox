import sqlite3
import datetime
import time
import os

# --- ADS1115 Imports (auskommentiert, da Hardware nicht angeschlossen ist) ---
# import smbus
# I2C_BUS = smbus.SMBus(4) # Wichtig: Dieser Bus wird nur mit dem ADS1115 benötigt

# Importiere nur die ADS-Bibliotheken (auskommentiert)
# import adafruit_ads1x15.ads1115 as ADS
# from adafruit_ads1x15.analog_in import AnalogIn

DB_NAME = '/home/pi/growbox_monitor/growbox_data.db' # Name deiner Datenbankdatei

# --- DS18B20 Temperatursensor Konfiguration ---
base_dir = '/sys/bus/w1/devices/'
device_folder = ''
device_file = ''

def find_ds18b20():
    try:
        # Finde alle Ordner, die mit '28-' beginnen (das sind DS18B20 Sensoren)
        folders = [f for f in os.listdir(base_dir) if f.startswith('28-')]
        if folders:
            global device_folder, device_file
            device_folder = os.path.join(base_dir, folders[0]) # Nimm den ersten gefundenen
            device_file = os.path.join(device_folder, 'w1_slave')
            return True
        else:
            print("LOG_TEMP: No DS18B20 sensor found.")
            return False
    except FileNotFoundError:
        print("LOG_TEMP: 1-Wire directory not found. Is 1-Wire enabled in config.txt?")
        return False
    except Exception as e:
        print(f"LOG_TEMP: Error finding DS18B20: {e}")
        return False

def read_temp_raw():
    try:
        if not device_file: # Wenn der Sensorpfad noch nicht gefunden wurde
            if not find_ds18b20():
                return None # Kann Sensor nicht finden
        with open(device_file, 'r') as f:
            lines = f.readlines()
        return lines
    except Exception as e:
        print(f"LOG_TEMP: Error reading raw temp: {e}")
        return None

def read_temp():
    lines = read_temp_raw()
    if lines is None:
        return None # Sensor nicht gefunden oder Fehler

    # Warte, bis der Sensor bereit ist ('YES' am Ende der ersten Zeile)
    while lines[0].strip()[-3:] != 'YES':
        time.sleep(0.2)
        lines = read_temp_raw()
        if lines is None:
            return None # Fehler beim Wiederholen

    # Extrahiere die Temperatur aus der zweiten Zeile
    equals_pos = lines[1].find('t=')
    if equals_pos != -1:
        temp_string = lines[1][equals_pos+2:]
        temp_c = float(temp_string) / 1000.0
        return round(temp_c, 2)
    return None # Fehler beim Parsen

# Funktion zum Speichern der Temperatur in der Datenbank
def log_temperature_to_db():
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        temperature = read_temp()
        # Speichere nur, wenn die Temperatur gültig ist (nicht None oder "N/A")
        if temperature is not None and temperature != "N/A":
            timestamp = datetime.datetime.now().isoformat() # ISO-Format für Zeitstempel
            cursor.execute("INSERT INTO temperatures (timestamp, value) VALUES (?, ?)", (timestamp, temperature))
            conn.commit()
            print(f"LOG_TEMP: {timestamp} - Temperatur {temperature}°C in DB gespeichert.")
        else:
            print("LOG_TEMP: Could not read temperature. Not saving to DB.")

    except sqlite3.Error as e:
        print(f"LOG_TEMP: Error saving to database: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    # Initialisiere den Sensor beim Start des Loggers
    find_ds18b20()
    # Logge die Temperatur einmal, wenn das Skript ausgeführt wird (für Cronjob)
    log_temperature_to_db()
