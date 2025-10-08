import requests
import os
import time
import datetime
import shutil

# --- KONFIGURATION ANPASSEN ---
# ------------------------------
# 1. IP-Adresse und Port Ihrer Home Assistant-Instanz
HA_URL = "http://192.168.0.167:8123" 
# 2. Ihr langes Home Assistant-Lebensdauer-Token (siehe HA-Profil)
#    !!! BITTE HIER IHREN KOPIERTEN TOKEN EINFÜGEN !!!
HA_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiIyOWE3YmRhZDJlOTY0NzEzYTI4MmU1ZDM4OTU4YTIzOCIsImlhdCI6MTc1OTI2NjI3NiwiZXhwIjoyMDc0NjI2Mjc2fQ.ozfMbYAhcEOFvy-2zRKADr8Bq0XnI22_1jGVMsY6EQw" # Beispiel für einen eingefügten Token
# 3. Die Entitäts-ID Ihrer Kamera in Home Assistant (z.B. camera.growzelt)
CAMERA_ENTITY_ID = "camera.growzelt" 

# --- PFAD KONFIGURATION ---
# -------------------------
# Ordner, in dem alle Fotos (Archiv und Live-Bild) gespeichert werden
PHOTO_DIR = "/home/pi/growbox_monitor/growbox_photos"

# Dateiname für das aktuelle Live-Bild (wird ständig überschrieben)
LATEST_PHOTO_PATH = os.path.join(PHOTO_DIR, 'latest_photo.jpg')

# Datei, um den Zeitstempel des letzten archivierten Fotos zu speichern
LAST_ARCHIVE_FILE = os.path.join(PHOTO_DIR, 'last_archive_time.txt')

# Zeitintervall für Archiv-Fotos in Sekunden (30 Minuten = 1800 Sekunden)
ARCHIVE_INTERVAL_SECONDS = 30 * 60 


def get_current_image():
    """
    Ruft den aktuellen Image-Link von Home Assistant ab und lädt das Bild herunter.
    """
    api_url = f"{HA_URL}/api/states/{CAMERA_ENTITY_ID}"
    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "content-type": "application/json",
    }
    
    try:
        # 1. HA API abfragen, um den neuesten, token-gesicherten Bild-Link zu erhalten
        response = requests.get(api_url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Die Home Assistant-Kamera-Entität liefert unter 'entity_picture' den aktuellen Link
        image_url_suffix = data.get("attributes", {}).get("entity_picture")
        
        if not image_url_suffix:
            print("Fehler: 'entity_picture' nicht in HA-Antwort gefunden.")
            return False
            
        # 2. Den vollständigen Link erstellen und das Bild herunterladen
        # Der HA_URL muss nicht erneut vor dem Suffix stehen, da Home Assistant den vollen Pfad sendet,
        # aber wir müssen den HA-Token im Header senden, da der Link gesichert ist.
        full_image_url = f"{HA_URL}{image_url_suffix}" if image_url_suffix.startswith('/api/') else image_url_suffix 
        
        # Bild-Datenstrom abrufen
        image_response = requests.get(full_image_url, headers=headers, stream=True, timeout=15)
        image_response.raise_for_status()

        # 3. Das neueste Bild speichern (überschreibt latest_photo.jpg)
        with open(LATEST_PHOTO_PATH, 'wb') as f:
            shutil.copyfileobj(image_response.raw, f)
            
        print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Live-Bild erfolgreich aktualisiert.")
        return True

    except requests.exceptions.RequestException as e:
        print(f"Fehler bei der HA-Kommunikation oder beim Bild-Download: {e}")
        return False
    except Exception as e:
        print(f"Ein unerwarteter Fehler ist aufgetreten: {e}")
        return False

def check_and_archive_photo():
    """
    Überprüft, ob das Archivierungsintervall erreicht wurde und speichert das
    aktuelle latest_photo.jpg mit Zeitstempel, falls nötig.
    """
    current_time = time.time()
    last_archive_time = 0

    # Lese den letzten Archivierungs-Zeitstempel
    if os.path.exists(LAST_ARCHIVE_FILE):
        try:
            with open(LAST_ARCHIVE_FILE, 'r') as f:
                last_archive_time = float(f.read().strip())
        except ValueError:
            # Dateiinhalt ungültig, setze auf 0
            last_archive_time = 0 

    # Überprüfe, ob 30 Minuten vergangen sind (ARCHIVE_INTERVAL_SECONDS)
    if current_time - last_archive_time >= ARCHIVE_INTERVAL_SECONDS:
        
        if os.path.exists(LATEST_PHOTO_PATH):
            timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_path = os.path.join(PHOTO_DIR, f"archive_photo_{timestamp_str}.jpg")
            
            try:
                # Kopiert das aktuelle Live-Bild ins Archiv
                shutil.copy2(LATEST_PHOTO_PATH, archive_path)
                
                # Aktualisiert den Archivierungs-Zeitstempel
                with open(LAST_ARCHIVE_FILE, 'w') as f:
                    f.write(str(current_time))
                    
                print(f"Archiv-Foto erstellt: {os.path.basename(archive_path)}")
            except Exception as e:
                print(f"Fehler beim Archivieren des Fotos: {e}")
        else:
            print("Archivierung übersprungen: latest_photo.jpg nicht gefunden.")

def main_loop():
    """Haupt-Loop, der alle 60 Sekunden läuft."""
    os.makedirs(PHOTO_DIR, exist_ok=True)
    
    while True:
        # 1. Ruft den aktuellen Link ab und speichert das latest_photo.jpg
        get_current_image()
        
        # 2. Überprüft, ob 30 Minuten für die Archivierung vergangen sind
        check_and_archive_photo()

        # Wartet 60 Sekunden vor der nächsten Aktualisierung
        time.sleep(60)

if __name__ == '__main__':
    print(f"Starte Bildaktualisierungs-Dienst. Archivierungsintervall: {ARCHIVE_INTERVAL_SECONDS/60} Minuten.")
    main_loop()
