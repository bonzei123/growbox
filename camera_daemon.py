import os
import time
import subprocess
import threading
import datetime
import shutil
from PIL import Image, ImageDraw, ImageFont

# --- Kamera- und Zeitraffer-Konfiguration ---
PHOTO_DIR = "/home/pi/growbox_photos"
TIMELAPSE_DIR = "/home/pi/growbox_timelapses"

# WICHTIG: Pfade anpassen (vom 'which'-Befehl)
RPICAM_STILL_PATH = "/usr/bin/rpicam-still"

# Pfad für das neueste Foto, das der Webserver anzeigt
LATEST_PHOTO_PATH = os.path.join(PHOTO_DIR, 'latest_photo.jpg')

# Funktion zum kontinuierlichen Aufnehmen von Fotos
def capture_photo_loop():
    
    print(f"Starte Fotoaufnahme-Loop mit {RPICAM_STILL_PATH}. Foto alle 60 Sekunden.")
    try:
        while True:
            current_time = time.time()
            
            # --- Mache ein einziges hochauflösendes Foto ---
            timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            temp_filename = f"{PHOTO_DIR}/growbox_photo_temp_{timestamp_str}.jpg"
            final_filename = f"{PHOTO_DIR}/growbox_photo_{timestamp_str}_1920x1080.jpg"
            
            # NEU: Zeitstempel-Text für das Overlay-Format
            overlay_text = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            
            cmd_capture = [
                RPICAM_STILL_PATH, "--nopreview", "-t", "1",
                "-o", temp_filename, "--width", "1920", "--height", "1080"
            ]
            
            try:
                # Versuche, das Foto aufzunehmen (mit 3 Retries)
                for i in range(3):
                    result = subprocess.run(cmd_capture, check=False, capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        print(f"Fotoaufnahme erfolgreich. Gespeichert als: {temp_filename}")
                        
                        # --- PILLOW SCHRITT: Fügt den Zeitstempel hinzu ---
                        try:
                            image = Image.open(temp_filename)
                            draw = ImageDraw.Draw(image)
                            font = ImageFont.truetype("DejaVuSans-Bold.ttf", 40) # Standard-Schriftart auf Raspberry Pi OS
                            
                            # NEU: Verwende textbbox anstelle von textsize
                            bbox = draw.textbbox((0, 0), overlay_text, font=font)
                            text_width = bbox[2] - bbox[0]
                            text_height = bbox[3] - bbox[1]
                            
                            # Position unten rechts mit 10 Pixeln Abstand
                            x = image.width - text_width - 10
                            y = image.height - text_height - 10
                            
                            # Schatteneffekt für bessere Lesbarkeit
                            draw.text((x+2, y+2), overlay_text, font=font, fill="black")
                            draw.text((x, y), overlay_text, font=font, fill="white")
                            
                            # Speichere die bearbeiteten Bilder
                            image.save(LATEST_PHOTO_PATH) # Speichert latest_photo.jpg
                            image.save(final_filename)    # Speichert die hochauflösende Timelapse-Version
                            
                            print(f"Zeitstempel hinzugefügt und Fotos gespeichert.")

                            # Lösche die temporäre Datei
                            os.remove(temp_filename)
                            
                        except Exception as pillow_error:
                            print(f"Fehler bei Pillow-Verarbeitung: {pillow_error}")
                            if os.path.exists(temp_filename):
                                os.remove(temp_filename)
                        
                        break
                    else:
                        print(f"Fehler bei Fotoaufnahme (Versuch {i+1}/3): {result.stderr.strip()}")
                        time.sleep(1) # Kurze Pause vor erneutem Versuch
                
                if result.returncode != 0:
                    print(f"Fotoaufnahme nach 3 Versuchen fehlgeschlagen.")
                    if os.path.exists(temp_filename):
                        os.remove(temp_filename)

            except (FileNotFoundError, subprocess.TimeoutExpired) as e:
                print(f"Unerwarteter Fehler bei Fotoaufnahme: {e}")

            # Warte 60 Sekunden, bevor das nächste Foto gemacht wird
            time.sleep(60)
            
    except Exception as e:
        print(f"Unerwarteter Fehler im Fotoaufnahme-Loop: {e}")
    finally:
        print("Fotoaufnahme-Loop beendet.")

if __name__ == '__main__':
    # Sicherstellen, dass die Ordner existieren
    os.makedirs(PHOTO_DIR, exist_ok=True)
    os.makedirs(TIMELAPSE_DIR, exist_ok=True)
    
    capture_photo_loop()
