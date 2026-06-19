# SmartCity SensorBridge Partheland

## Sensorwerte aus dem Partheland in Home Assistant

Diese Custom Integration holt Umweltdaten aus dem SmartCity-Netzwerk Partheland in Home Assistant. So landen Messwerte lokaler Stationen im Dashboard und können auch für Automationen genutzt werden.

## Welche Daten die Integration einbindet

Die SensorBridge liest Daten von senseBox:home-Stationen und LoRaWAN-Sensoren aus der Region Partheland. Dazu kommen Medianwerte, die aus mehreren Stationen pro Ort oder für das gesamte Partheland berechnet werden.

## Messwerte der senseBox:home-Stationen

- **Temperatur**: Lufttemperatur
- **Luftfeuchte**: relative Luftfeuchte
- **Luftdruck**: atmosphärischer Druck
- **Feinstaub**: PM10- und PM2.5-Werte
- **Beleuchtungsstärke**: Lichtintensität
- **UV-Intensität**: Sonnenstrahlung
- **Lautstärke**: Umgebungsgeräusche

## Messwerte der LoRaWAN-Sensoren

- **Temperatursensoren**: Luft- und Wassertemperaturen
- **Wasserpegel**: Pegelstände von Gewässern

## Was vorher installiert sein muss

- Python 3.13.2 oder neuer
- Home Assistant 2026.6.3 oder neuer
- HACS (Home Assistant Community Store) für die einfache Installation
- Internetverbindung

## Installation über HACS

1. **Repository in HACS hinzufügen**
   - Öffne HACS in der Seitenleiste
   - Klicke auf **⋯** (drei Punkte oben rechts)
   - Wähle **Benutzerdefiniertes Repository**
   - Füge diese URL hinzu: `https://github.com/makerspace-partheland/smartcity-sensorbridge-partheland`
   - Wähle als Typ **Integration**
   - Klicke auf **Hinzufügen**

2. **Integration installieren**
   - Öffne in HACS den Bereich **Integrationen**
   - Wähle **SmartCity SensorBridge Partheland** und klicke auf **Installieren**
   - Starte Home Assistant neu

3. **Integration einrichten**
   - Gehe zu **Einstellungen** → **Geräte & Dienste**
   - Klicke auf **+ Integration hinzufügen**
   - Suche nach "SmartCity SensorBridge Partheland"
   - Folge der Einrichtung

## Manuelle Installation

1. Lade die Dateien herunter
2. Kopiere den Ordner `custom_components/sensorbridge_partheland/` in deine Home-Assistant-Installation
3. Starte Home Assistant neu

## Nach der Installation

Die Standardeinstellungen reichen für den Start. Home Assistant lädt die verfügbaren Sensoren und legt die passenden Geräte und Entitäten an.

## Wenn keine Daten ankommen

- Prüfe, ob die Integration korrekt installiert ist
- Schalte die Debug-Logs ein

## Wenn Werte nicht plausibel wirken

Melde das Problem über GitHub Issues oder über den Kontakt unten.

## Geräte und Entitäten entfernen

- Über die Geräte-Ansicht: **Einstellungen** → **Geräte & Dienste** → **Geräte** → Gerät öffnen → **⋯** → **Gerät löschen**. Zugehörige Entitäten werden mit entfernt.
- Über die Integrations-Optionen: Integration öffnen → **Optionen** → Gerät oder Median-Entity abwählen → **Speichern**. Beim anschließenden Reload bereinigt die Integration nicht mehr ausgewählte Entitäten und Geräte aus den Registern.

## Debug-Logs einschalten

Füge diese Einstellung zu deiner `configuration.yaml` hinzu:

```yaml
logger:
  custom_components.sensorbridge_partheland: debug
```

## Updates

HACS zeigt neue Versionen an. Zusätzlich halten GitHub Actions die Abhängigkeiten wöchentlich aktuell und erstellen PRs. Dependabot aktualisiert GitHub-Actions-Versionen zeitversetzt. Erfolgreiche Abhängigkeits-PRs werden nach bestandenem CI- und HA-Kompatibilitätscheck zusammengeführt. Größere Versionswechsel werden getrennt geprüft. Zuletzt erfolgreich getestet mit Home Assistant 2026.6.3.

Bei manueller Installation muss die aktuelle Version heruntergeladen und über die vorhandenen Dateien kopiert werden.

## Unterstützung

- **Probleme melden**: [GitHub Issues](https://github.com/makerspace-partheland/smartcity-sensorbridge-partheland/issues)
- **Kontakt**: [Makerspace Partheland](https://makerspace-partheland.de)

## Lizenz

MIT License - du kannst die Integration frei nutzen und anpassen.

---

Die Integration ist Teil des SmartCity-Projekts Partheland. Weitere Informationen stehen auf [makerspace-partheland.de](https://makerspace-partheland.de).
