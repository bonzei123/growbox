# -*- coding: utf-8 -*-
import requests
import sys
import sqlite3
import datetime
import os

# --- KONFIGURATION ---
DB_NAME = os.path.join(os.path.dirname(__file__), 'growbox_data.db')
HA_URL = "http://192.168.0.167:8123"
HA_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiIyOWE3YmRhZDJlOTY0NzEzYTI4MmU1ZDM4OTU4YTIzOCIsImlhdCI6MTc1OTI2NjI3NiwiZXhwIjoyMDc0NjI2Mjc2fQ.ozfMbYAhcEOFvy-2zRKADr8Bq0XnI22_1jGVMsY6EQw"
DEVICE_ENTITY_ID = "switch.grow_luftung_socket_1" # ANPASSEN: ID für Ihren Lüfter
CRON_FILE = "/var/spool/cron/crontabs/pi" # ANPASSEN: Pfad zur crontab des 'pi' Users

# --- Datenbank-Logik ---

def initialize_db():
    """Stellt sicher, dass die logs-Tabelle existiert."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Log-Tabelle für die Lüfter-Schaltvorgänge
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS luefter_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL
        )
    """)
    # Tabelle für die Speicherung der Cron-Einträge
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def log_action(action, status):
    """Schreibt einen Eintrag in die luefter_logs Tabelle."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    timestamp = datetime.datetime.now().isoformat()
    cursor.execute("INSERT INTO luefter_logs (timestamp, action, status) VALUES (?, ?, ?)", 
                   (timestamp, action, status))
    conn.commit()
    conn.close()

# --- HA API Logik ---
def toggle_device_state(target_state):
    """Sendet einen Service-Call an Home Assistant und loggt das Ergebnis."""
    # Definiere den HA Service und die Log-Nachricht
    ha_service = target_state
    
    url = f"{HA_URL}/api/services/switch/{ha_service}"
    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "entity_id": DEVICE_ENTITY_ID
    }
    
    success = False
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        log_action(target_state, "SUCCESS")
        print(f"Erfolg: Gerät wurde auf '{target_state}' gesetzt und geloggt.")
        success = True
    except requests.exceptions.RequestException as e:
        log_action(target_state, "FAILURE")
        print(f"Fehler beim Senden des Befehls an Home Assistant: {e}")
    
    return success

if __name__ == "__main__":
    initialize_db()
    
    if len(sys.argv) < 2:
        print("Nutzung: python3 lueftung.py [on | off]")
        sys.exit(1)
        
    command = sys.argv[1].lower()
    if command == "on":
        toggle_device_state("turn_on")
    elif command == "off":
        toggle_device_state("turn_off")
    else:
        print("Ungültiger Befehl.")
        sys.exit(1)
