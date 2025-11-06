import requests
import sys
import datetime
import sqlite3
import os

# --- KONFIGURATION ---
DB_NAME = os.path.join(os.path.dirname(__file__), 'growbox_data.db')
HA_URL = "http://192.168.0.167:8123"
HA_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiIyOWE3YmRhZDJlOTY0NzEzYTI4MmU1ZDM4OTU4YTIzOCIsImlhdCI6MTc1OTI2NjI3NiwiZXhwIjoyMDc0NjI2Mjc2fQ.ozfMbYAhcEOFvy-2zRKADr8Bq0XnI22_1jGVMsY6EQw"
DEVICE_ENTITY_ID = "switch.grow_luftung_socket_1"  # ANPASSEN: ID für Ihren Lüfter


# CRON_FILE wurde entfernt, da die Verwaltung jetzt zentral über app.py läuft


# --- Datenbank-Logik ---

# initialize_db() wurde entfernt, da die App.py die zentrale DB-Initialisierung übernimmt.

def log_action(action, status):
    """Schreibt einen Eintrag in die luefter_logs Tabelle."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    timestamp = datetime.datetime.now().isoformat()
    # Loggt die Aktion (z.B. turn_on) und den Status (SUCCESS/FAILURE)
    cursor.execute("INSERT INTO luefter_logs (timestamp, action, status) VALUES (?, ?, ?)",
                   (timestamp, action, status))
    conn.commit()
    conn.close()


# --- HA API Logik ---
def toggle_device_state(target_state):
    """Sendet einen Service-Call an Home Assistant und loggt das Ergebnis."""
    # Definiere den HA Service (turn_on oder turn_off)
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
        # Fängt API-Fehler und andere Request-Probleme ab
        log_action(target_state, "FAILURE")
        print(f"Fehler beim Senden des Befehls an Home Assistant: {e}")

    return success


if __name__ == "__main__":
    # Überprüft, ob ein Befehl (on oder off) übergeben wurde
    if len(sys.argv) < 2:
        print("Nutzung: python3 lueftung.py [on | off]")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "on":
        # Ruft HA mit dem Service 'turn_on' auf
        toggle_device_state("turn_on")
    elif command == "off":
        # Ruft HA mit dem Service 'turn_off' auf
        toggle_device_state("turn_off")
    else:
        print("Ungültiger Befehl.")
        sys.exit(1)