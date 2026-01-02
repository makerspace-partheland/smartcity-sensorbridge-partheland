# SmartCity SensorBridge Partheland

## Was ist das?

Diese Custom Integration verbindet Dein Home Assistant mit dem SmartCity-Netzwerk Partheland und zeigt Umweltdaten von lokalen Sensoren im Partheland direkt in Deinem Smart Home an. Die Daten kommen von Sensoren in Deiner Region und werden in Echtzeit aktualisiert.

## Was können wir damit machen?

- **Umweltdaten anzeigen**: Temperatur, Luftfeuchte, Luftqualität und mehr
- **Lokale Sensordaten**: Umweltinformationen von Sensoren in Ihrer Nähe
- **Automatisierungen**: Reagieren Sie auf Umweltveränderungen
- **Dashboard**: Schöne Übersichten in der Home Assistant Oberfläche

## Welche Daten sehen wir?

### senseBox:home Stationen

Die Integration unterstützt senseBox:home Umweltstationen in verschiedenen Orten der Region Partheland:

- **Temperatur**: Lufttemperatur
- **Luftfeuchte**: Relative Luftfeuchte
- **Luftdruck**: Atmosphärischer Druck
- **Feinstaub**: PM10 und PM2.5 Werte
- **Beleuchtungsstärke**: Lichtintensität
- **UV-Intensität**: Sonnenstrahlung
- **Lautstärke**: Umgebungsgeräusche

### LoRaWAN Sensoren

- **Temperatursensoren**: Luft- und Wassertemperaturen
- **Wasserpegel**: Pegelstände von Gewässern

### Median-Entities

Ausfallsichere Median-Werte für verschiedene Orte, berechnet aus mehreren Stationen je Ort oder dem gesamten Partheland.

## Was brauchen wir?

- Python 3.13.2 oder neuer
- Home Assistant (Version 2025.12.4 oder neuer)
- HACS (Home Assistant Community Store) - für die einfache Installation
- Internetverbindung

## Installation

### Installation über HACS (Empfohlen)

1. **Repository in HACS hinzufügen (Custom Repository)**:
   - Öffne  HACS in der Seitenleiste
   - Klicken auf **⋯** (drei Punkte oben rechts)
   - Wähle  **Benutzerdefiniertes Repository**
   - Füge diese URL hinzu: `https://github.com/makerspace-partheland/smartcity-sensorbridge-partheland`
   - Typ: Integration
   - Klicke  auf Hinzufügen

2. **Integration installieren**
   - Öffne in HACS den Bereich **Integrationen**
   - Klicke  auf ***SmartCity SensorBridge Partheland*** → **Installieren**
   - Starte Home Assistant neu

3. **Integration einrichten**:
   - Gehe zu **Einstellungen** → **Geräte & Dienste**
   - Klicke auf **+ Integration hinzufügen**
   - Suche nach "SmartCity SensorBridge Partheland"
   - Folge der Einrichtung

### Manuelle Installation (für Fortgeschrittene)

1. Lade die Dateien herunter
2. Kopiere den Ordner `custom_components/sensorbridge_partheland/` in Dein Home Assistant
3. Starte Home Assistant neu

## Einrichtung

Die Integration ist sehr einfach zu konfigurieren:

1. **Integration hinzufügen** (siehe Installation oben)
2. **Konfiguration bestätigen** - die Standardeinstellungen funktionieren sofort
3. **Fertig!**

Die Integration lädt automatisch alle verfügbaren Sensoren und zeigt sie in Home Assistant an.

## Hilfe bei Problemen

### Häufige Fragen

#### Ich sehe keine Daten

- Prüfe, ob die Integration korrekt installiert ist
- Schaue in die Logs (siehe unten)

#### Die Werte sind falsch

- Kontaktiere uns bei Problemen

#### Wie aktualisiere ich die Integration?

- Über HACS: Automatische Updates
- Manuell: Neue Version herunterladen

#### Wie entferne ich ein Gerät/Entitäten?

- Über die Geräte-Ansicht: Einstellungen → Geräte & Dienste → Geräte → Gerät öffnen → 3-Punkte → Gerät löschen. Die Integration unterstützt das direkte Entfernen; dabei werden zugehörige Entitäten mit entfernt.
- Über die Integrations-Optionen: Integration öffnen → Optionen → das Gerät (oder Median-Entity) abwählen → Speichern. Beim anschließenden Reload werden nicht mehr ausgewählte Entitäten/Geräte automatisch aus den Registern bereinigt.

### Logs prüfen

Fügen dies zu Deiner `configuration.yaml` hinzu:

```yaml
logger:
  custom_components.sensorbridge_partheland: debug
```

## Updates

- **Automatisch**: HACS zeigt Updates an. Zusätzlich halten GitHub Actions die Abhängigkeiten wöchentlich aktuell (Patch/Minor) und erstellen PRs. Dependabot aktualisiert GitHub Actions-Versionen automatisch. Die Integration wird durch die Automatisierung eigenständig gepflegt und führt erfolgreiche Abhängigkeits-PRs nach bestandenem CI- und HA-Kompatibilitätscheck automatisch zusammen. Zuletzt erfolgreich getestet mit Home Assistant 2025.12.4.4
- **Manuell**: Neue Version herunterladen.

## Unterstützung

- **Probleme melden**: [GitHub Issues](https://github.com/makerspace-partheland/smartcity-sensorbridge-partheland/issues)
- **Kontakt**: [Makerspace Partheland](https://makerspace-partheland.de)

## Lizenz

MIT License - Du kannst die Integration frei nutzen und anpassen.

---

**Tipp**: Diese Integration ist Teil des SmartCity-Projekts Partheland. Weitere Informationen findest Du auf [makerspace-partheland.de](https://makerspace-partheland.de).
