import sys
import requests
import json

HA_URL = "http://192.168.0.167:8123"
HA_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiIyOWE3YmRhZDJlOTY0NzEzYTI4MmU1ZDM4OTU4YTIzOCIsImlhdCI6MTc1OTI2NjI3NiwiZXhwIjoyMDc0NjI2Mjc2fQ.ozfMbYAhcEOFvy-2zRKADr8Bq0XnI22_1jGVMsY6EQw"

# Entitäts-ID der Steckdose
ENTITY_ID = "switch.grow_luftung_socket_1"
# ---------------------

def set_steckdose_state(state):
    """Steuert die Steckdose basierend auf dem Status 'on' oder 'off'."""
    if state not in ["on", "off"]:
        print("Ungültiger Status. Bitte verwende 'on' oder 'off'.")
        sys.exit(1)

    service = "turn_" + state
    url = f"{HA_URL}/api/services/switch/{service}"
    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "entity_id": ENTITY_ID
    }

    print(f"Sende Anfrage an {url}...")

    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        print(f"Aktion erfolgreich ausgeführt. Statuscode: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Ein Fehler ist aufgetreten: {e}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Verwendung: python <script_name>.py <state>")
        print("Beispiel: python grow_control.py on")
        sys.exit(1)
    
    state = sys.argv[1].lower()
    set_steckdose_state(state)
