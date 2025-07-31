import sqlite3
import os

DB_NAME = 'growbox_data.db' # Name deiner Datenbankdatei

def setup_database():
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Tabelle für Temperaturdaten erstellen
        # timestamp: Speichert das Datum und die Uhrzeit der Messung (TEXT für ISO format)
        # value: Speichert den Temperaturwert (REAL für Fließkommazahl)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS temperatures (
                timestamp TEXT PRIMARY KEY,
                value REAL
            )
        ''')
        conn.commit()
        print(f"Datenbank '{DB_NAME}' und Tabelle 'temperatures' erfolgreich eingerichtet.")

    except sqlite3.Error as e:
        print(f"Fehler beim Einrichten der Datenbank: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    setup_database()