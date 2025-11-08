// Globale Variable für unsere Chart-Instanz, damit wir sie updaten können
let tempChartInstance;

// Definiert die Farben für das dunkle Theme des Charts
const chartColors = {
mainLine: "#fb923c", // Orange für die Linie (passt zur Temperaturkarte)
fillArea: "rgba(251, 146, 60, 0.15)",
gridLine: "rgba(255, 255, 255, 0.1)", // Helle, transparente Gitterlinien
fontColor: "#e5e7eb" // Helle Schrift
};

// --- HILFSFUNKTIONEN ---

function getDaysSince(dateString) {
    // Berechnet die Tage seit dem Keimdatum
    const today = new Date();
    // Achtung: Das Keimdatum muss als YYYY-MM-DD übergeben werden, um Probleme zu vermeiden
    const targetDate = new Date(dateString + 'T00:00:00');

    if (isNaN(targetDate.getTime()) || targetDate > today) return 0;

    const diffTime = Math.abs(today.getTime() - targetDate.getTime());
    // Korrektur: Nutzt Math.floor() + 1, um den Keimtag als Tag 1 zu zählen
    const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
    return diffDays + 1;
}

// --- CHART FUNKTIONALITÄT ---

// Diese Funktion wird aufgerufen, wenn ein Zeit-Button geklickt wird
async function updateChart(hours) {
    console.log(`Lade Daten für die letzten ${hours} Stunden...`);

    // Aktiven Button-Stil aktualisieren
    document.querySelectorAll(".btn-timeframe").forEach(button => {
        const buttonHours = parseInt(button.getAttribute("onclick").match(/(\d+)/)[1]);
        if (buttonHours === hours) {
            button.classList.add("active");
        } else {
            button.classList.remove("active");
        }
    });

    try {
        const response = await fetch(`/api/temperature_data?hours=${hours}`);
        if (!response.ok) {
            throw new Error(`Server-Fehler: ${response.status}`);
        }
        const data = await response.json();

        tempChartInstance.data.labels = data.labels;
        tempChartInstance.data.datasets[0].data = data.values;

        let timeUnit = "hour";
        if (hours > 72) { timeUnit = "day"; } else if (hours < 3) { timeUnit = "minute"; }

        tempChartInstance.options.scales.x.time.unit = timeUnit;
        tempChartInstance.options.scales.x.time.displayFormats.hour = (timeUnit === "hour" || timeUnit === "minute") ? "HH:mm" : "dd.MM.";
        tempChartInstance.options.scales.x.time.tooltipFormat = (timeUnit === "day") ? "dd.MM.yyyy" : "dd.MM.yyyy HH:mm";

        const hasData = data.labels.length > 0;
        tempChartInstance.options.plugins.title.display = !hasData;
        tempChartInstance.options.plugins.title.text = hasData ? "" : "Keine Daten für diesen Zeitraum verfügbar";

        tempChartInstance.update();

    } catch (error) {
        console.error("Fehler beim Aktualisieren des Charts:", error);
        tempChartInstance.options.plugins.title.text = "Daten konnten nicht geladen werden";
        tempChartInstance.options.plugins.title.display = true;
        tempChartInstance.update();
    }
}

// Diese Funktion initialisiert den Chart, wenn die Seite geladen wird
function initializeChart() {
    const ctx = document.getElementById("tempChart").getContext("2d");
    tempChartInstance = new Chart(ctx, {
        type: "line",
        data: {
            labels: [],
            datasets: [{
                label: "Temperatur",
                data: [],
                borderColor: chartColors.mainLine,
                backgroundColor: chartColors.fillArea,
                borderWidth: 2,
                tension: 0.3,
                fill: true,
                pointRadius: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    type: "time",
                    time: {
                        unit: "hour",
                        tooltipFormat: "dd.MM.yyyy HH:mm",
                        displayFormats: { hour: "HH:mm" }
                    },
                    ticks: { color: chartColors.fontColor },
                    grid: { color: chartColors.gridLine },
                    title: { display: true, text: "Uhrzeit", color: chartColors.fontColor }
                },
                y: {
                    beginAtZero: false,
                    ticks: { color: chartColors.fontColor },
                    grid: { color: chartColors.gridLine },
                    title: { display: true, text: "Temperatur (°C)", color: chartColors.fontColor }
                }
            },
            plugins: {
                title: { display: false, text: "", color: chartColors.fontColor, padding: { top: 10, bottom: 30 }, font: { size: 16 } },
                legend: { display: false }
            }
        }
    });
}


// --- LÜFTER STEUERUNG FUNKTIONALITÄT ---

// Lädt die Log-Einträge neu
async function loadLuefterLogs() {
    const logOutput = document.getElementById('luefter-log-output');
    try {
        const response = await fetch('/api/luefter_logs');
        if (!response.ok) { throw new Error(`Server-Fehler: ${response.status}`); }
        const logs = await response.json();

        let logText = '';
        if (logs.length === 0) { logText = "Keine Protokolle gefunden."; } else {
            logs.forEach(log => { logText += `${log.timestamp} [${log.status}] ${log.action}\n`; });
        }
        logOutput.textContent = logText;
    } catch (error) {
        console.error("Fehler beim Laden der Logs:", error);
        logOutput.textContent = `Fehler: Logs konnten nicht geladen werden. (${error.message})`;
    }
}

// Manuelle Steuerung des Lüfters (AN/AUS)
async function toggleLuefter(command) {
    const statusDisplay = document.getElementById('luefter-status-display');
    const oldText = statusDisplay.textContent;
    statusDisplay.textContent = `Schalte ${command.toUpperCase()}...`;
    statusDisplay.style.backgroundColor = '#fb923c';

    try {
        const response = await fetch('/api/luefter_toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: command })
        });

        const result = await response.json();

        if (response.ok) {
            const newState = command === 'on' ? 'AN' : 'AUS';
            statusDisplay.textContent = `Status: ${newState}`;
            statusDisplay.style.backgroundColor = command === 'on' ? '#10b981' : '#f87171';
            loadLuefterLogs();
        } else {
            console.error(`Fehler beim Schalten: ${result.error || 'Unbekannter Fehler'}`);
            statusDisplay.textContent = oldText;
            statusDisplay.style.backgroundColor = oldText.includes('AN') ? '#10b981' : '#f87171';
        }

    } catch (error) {
        console.error("Netzwerkfehler beim Schalten:", error);
        console.error('Netzwerkfehler: Gerät konnte nicht geschaltet werden.');
        statusDisplay.textContent = oldText;
        statusDisplay.style.backgroundColor = oldText.includes('AN') ? '#10b981' : '#f87171';
    }
}


// Behandelt das Speichern der Cron-Minuten
document.getElementById('luefter-settings-form').addEventListener('submit', async function(e) {
    e.preventDefault();

    const statusElement = document.getElementById('settings-status');
    statusElement.textContent = 'Speichere und aktualisiere Cronjobs...';
    statusElement.style.color = '#fb923c';

    const formData = new FormData(this);
    const onMinutes = formData.get('on_minutes').trim();
    const offMinutes = formData.get('off_minutes').trim();

    try {
        const response = await fetch('/api/luefter_settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ on_minutes: onMinutes, off_minutes: offMinutes })
        });

        const result = await response.json();

        if (response.ok) {
            statusElement.textContent = result.message;
            statusElement.style.color = '#4ade80';
        } else {
            statusElement.textContent = `Fehler: ${result.error}`;
            statusElement.style.color = '#f87171';
        }
    } catch (error) {
        console.error("Fehler beim Speichern der Einstellungen:", error);
        statusElement.textContent = 'Netzwerkfehler beim Speichern der Einstellungen.';
        statusElement.style.color = '#f87171';
    }
});


// --- TAGEBUCH FUNKTIONALITÄT ---

// Rendert die Chronologie-Einträge
function renderJournalEntries(entries, plantName) {
    const container = document.getElementById('journal-entries-container');
    const plantNameDisplay = document.getElementById('chronology-plant-name');
    container.innerHTML = '';
    plantNameDisplay.textContent = plantName;

    if (entries.length === 0) {
        container.innerHTML = `<p style="color: #9ca3af;">Noch keine Einträge für ${plantName} vorhanden.</p>`;
        return;
    }

    const selectedOption = document.getElementById('plant-select').options[document.getElementById('plant-select').selectedIndex];
    const keimDate = selectedOption.getAttribute('data-keimdate');

    entries.forEach(entry => {
        // Berechne das Alter der Pflanze ZUM ZEITPUNKT des Eintrags
        const entryDate = new Date(entry.timestamp);
        const keimDateTime = new Date(keimDate + 'T00:00:00');
        const diffTime = entryDate.getTime() - keimDateTime.getTime();
        const days = Math.floor(diffTime / (1000 * 60 * 60 * 24)) + 1; // Tag 1 ist der Keimtag

        const card = document.createElement('div');
        card.className = 'journal-entry-card';
        card.style.cssText = 'display: flex; gap: 1rem; margin-bottom: 1rem; background-color: #1f1f1f; padding: 1rem; border-radius: 8px; border-left: 5px solid #6ee7b7;';

        const imagePath = entry.image_path ? `/latest_photo?name=${entry.image_path}` : 'https://placehold.co/80x80/3f3f46/9ca3af?text=Kein+Bild';

        const imageHtml = `
            <img src="${imagePath}" 
                 style="width: 80px; height: 80px; object-fit: cover; border-radius: 4px; flex-shrink: 0;" 
                 onerror="this.onerror=null;this.src='https://placehold.co/80x80/3f3f46/9ca3af?text=Kein+Bild';" 
                 alt="Tagebuch Foto">`;

        card.innerHTML = `
            ${imageHtml}
            <div style="flex-grow: 1;">
                <p style="font-size: 0.8rem; color: #9ca3af; margin-bottom: 0.3rem;">
                    ${entry.timestamp.split(' ')[0]} (Tag ${days}) | Zyklus: <span style="font-weight: bold; color: #4ade80;">${entry.cycle}</span>
                </p>
                <p style="font-size: 1rem; margin-bottom: 0.5rem;">${entry.notes}</p>
            </div>
        `;
        container.appendChild(card);
    });
}

// Lädt die Chronologie, wenn eine Pflanze ausgewählt wird
document.getElementById('plant-select').addEventListener('change', async function() {
    const plantId = this.value;
    const selectedOption = this.options[this.selectedIndex];
    const plantName = selectedOption.text.split('(')[0].trim();
    const keimDate = selectedOption.getAttribute('data-keimdate');
    const lastCycle = selectedOption.getAttribute('data-lastcycle'); // NEU: Persistenter Zyklus

    const ageDisplay = document.getElementById('plant-age-display');
    const form = document.getElementById('journal-entry-form');
    const cycleDropdown = document.getElementById('journal-cycle');

    if (!plantId) {
        ageDisplay.textContent = 'Pflanzenalter: Bitte Pflanze auswählen.';
        form.style.display = 'none';
        document.getElementById('journal-entries-container').innerHTML = `<p style="color: #9ca3af;">Wählen Sie eine Pflanze, um die Chronologie anzuzeigen.</p>`;
        document.getElementById('chronology-plant-name').textContent = '...';
        return;
    }

    form.style.display = 'block';

    // NEU: Setze das Zyklus-Dropdown auf den zuletzt verwendeten Wert
    if (lastCycle) {
        cycleDropdown.value = lastCycle;
    }

    // Altersanzeige aktualisieren
    const days = getDaysSince(keimDate);
    const weeks = Math.floor((days - 1) / 7) + 1; // Woche 1 (Tag 1-7), Woche 2 (Tag 8-14)
    ageDisplay.textContent = `Pflanzenalter: ${weeks}. Woche / Tag ${days}`;

    // Chronologie laden
    try {
        const response = await fetch(`/api/journal/${plantId}`);
        const entries = await response.json();
        renderJournalEntries(entries, plantName);
    } catch (error) {
        console.error("Fehler beim Laden des Journals:", error);
        document.getElementById('journal-entries-container').innerHTML = `<p style="color: #f87171;">Fehler beim Laden der Einträge.</p>`;
    }
});

// Speichert den neuen Tagebucheintrag
document.getElementById('journal-entry-form').addEventListener('submit', async function(e) {
    e.preventDefault();

    const plantSelect = document.getElementById('plant-select');
    const plantId = plantSelect.value;
    const notes = document.getElementById('journal-notes').value.trim();
    const cycle = document.getElementById('journal-cycle').value;
    const statusElement = document.getElementById('journal-status');

    statusElement.textContent = 'Speichere Eintrag und Foto...';
    statusElement.style.color = '#fb923c';

    try {
        const response = await fetch('/api/journal', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plant_id: plantId, cycle: cycle, notes: notes })
        });

        const result = await response.json();

        if (response.ok) {
            statusElement.textContent = result.message;
            statusElement.style.color = '#4ade80';
            document.getElementById('journal-notes').value = '';
            plantSelect.dispatchEvent(new Event('change'));

        } else {
            statusElement.textContent = `Fehler: ${result.error}`;
            statusElement.style.color = '#f87171';
        }
    } catch (error) {
        console.error("Netzwerkfehler beim Speichern des Tagebuchs:", error);
        statusElement.textContent = 'Netzwerkfehler beim Speichern des Tagebuchs.';
        statusElement.style.color = '#f87171';
    }
});


// --- PFLANZEN VERWALTUNG MODAL FUNKTIONALITÄT ---

// Öffnet das Modal
function openPlantManager() {
    document.getElementById('plant-manager-modal').style.display = 'block';
    loadPlantListForManager();
}

// Schließt das Modal
function closePlantManager() {
    document.getElementById('plant-manager-modal').style.display = 'none';
    // Aktualisiere das Haupt-Dropdown nach dem Schließen (falls neue Pflanzen hinzugefügt wurden)
    // Wir verwenden einen sanften Reload statt window.location.reload()
    fetch('/api/plants').then(res => res.json()).then(plants => {
        const select = document.getElementById('plant-select');
        // Entferne alte Optionen (außer der ersten "--Pflanze auswählen--")
        while (select.options.length > 1) {
            select.remove(1);
        }
        // Füge neue Optionen hinzu
        plants.forEach(plant => {
            const days = getDaysSince(plant.keim_date);
            const option = new Option(`${plant.name} (Tag ${days})`, plant.id);
            option.setAttribute('data-keimdate', plant.keim_date);
            option.setAttribute('data-lastcycle', plant.last_cycle || 'Keimling'); // Fallback
            select.add(option);
        });
    });
}

// Lädt die Liste der vorhandenen Pflanzen im Modal
async function loadPlantListForManager() {
    const listContainer = document.getElementById('current-plants-list');
    listContainer.innerHTML = '<p style="color: #9ca3af;">Lade Pflanzen...</p>';

    try {
        const response = await fetch('/api/plants');
        if (!response.ok) { throw new Error('Fehler beim Laden der Pflanzenliste.'); }
        const plants = await response.json();

        if (plants.length === 0) {
            listContainer.innerHTML = '<p style="color: #fb923c;">Noch keine Pflanzen gespeichert.</p>';
            return;
        }

        let html = '<ul style="list-style-type: none; padding: 0;">';
        plants.forEach(p => {
            const ageInfo = `(Keimung: ${p.keim_date}, Gesetzt: ${p.seed_date})`;
            html += `
                <li style="border-bottom: 1px solid #333; padding: 8px 0; display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-weight: bold; color: #fff;">${p.name} (${p.type})</span>
                    <span style="color: #aaa; font-size: 0.9rem;">${p.strain} ${ageInfo}</span>
                </li>`;
        });
        html += '</ul>';
        listContainer.innerHTML = html;

    } catch (error) {
        listContainer.innerHTML = `<p style="color: #f87171;">Fehler: ${error.message}</p>`;
    }
}

// Behandelt das Hinzufügen einer neuen Pflanze
document.getElementById('add-plant-form').addEventListener('submit', async function(e) {
    e.preventDefault();
    const statusElement = document.getElementById('plant-add-status');
    statusElement.textContent = 'Speichere Pflanze...';
    statusElement.style.color = '#fb923c';

    const formData = {
        name: document.getElementById('new-plant-name').value,
        strain: document.getElementById('new-strain').value,
        type: document.getElementById('new-type').value,
        seed_date: document.getElementById('new-seed-date').value, // NEU
        keim_date: document.getElementById('new-keim-date').value
    };

    try {
        const response = await fetch('/api/plants', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData)
        });

        const result = await response.json();

        if (response.ok) {
            statusElement.textContent = result.message;
            statusElement.style.color = '#4ade80';
            this.reset(); // Formular leeren
            loadPlantListForManager(); // Liste im Modal aktualisieren

        } else {
            statusElement.textContent = `Fehler: ${result.error}`;
            statusElement.style.color = '#f87171';
        }

    } catch (error) {
        statusElement.textContent = 'Netzwerkfehler beim Hinzufügen der Pflanze.';
        statusElement.style.color = '#f87171';
    }
});