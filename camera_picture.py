import time
from picamera2 import Picamera2
import datetime
import os

# Verzeichnis zum Speichern der Bilder
PHOTO_DIR = "growbox_photos" # Passe den Pfad bei Bedarf an!

# Erstelle das Verzeichnis, falls es nicht existiert
os.makedirs(PHOTO_DIR, exist_ok=True)

# Kamera initialisieren
picam2 = Picamera2()
camera_config = picam2.create_still_configuration(main={"size": (1280, 720)}, lores={"size": (640, 480)}, display="lores")
picam2.configure(camera_config)
picam2.start() # Kamera starten

print(f"Kamera gestartet. Fotos werden alle 5 Minuten in {PHOTO_DIR} gespeichert.")

try:
    while True:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{PHOTO_DIR}/growbox_photo_{timestamp}.jpg"
        picam2.capture_file(filename)
        print(f"Foto gespeichert: {filename}")

        time.sleep(5 * 60) # Warte 5 Minuten (5 * 60 Sekunden)

except KeyboardInterrupt:
    print("Kameraaufnahme beendet.")
finally:
    picam2.stop()
    picam2.release_camera() # Kamera freigeben