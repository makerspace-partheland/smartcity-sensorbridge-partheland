[![HACS Validation](https://github.com/makerspace-partheland/smartcity-sensorbridge-partheland/actions/workflows/hacs-validate.yml/badge.svg)](https://github.com/makerspace-partheland/smartcity-sensorbridge-partheland/actions/workflows/hacs-validate.yml) [![Home Assistant Release Monitoring](https://github.com/makerspace-partheland/smartcity-sensorbridge-partheland/actions/workflows/ha-monitoring.yml/badge.svg?branch=main)](https://github.com/makerspace-partheland/smartcity-sensorbridge-partheland/actions/workflows/ha-monitoring.yml)
# SmartCity SensorBridge Partheland

Eine einfache Home Assistant Custom Integration für das SmartCity-Netzwerk Partheland, die Umweltdaten von lokalen Sensoren in Ihr Smart Home bringt.

## Was ist das?

Diese Custom Integration verbindet Ihr Home Assistant mit dem SmartCity-Netzwerk Partheland und zeigt Ihnen Umweltdaten von lokalen Sensoren direkt in Ihrem Smart Home an. Die Daten kommen von Sensoren in Ihrer Region und werden in Echtzeit aktualisiert.

## Was können Sie damit machen?

- **Umweltdaten anzeigen**: Temperatur, Luftfeuchte, Luftqualität und mehr
- **Lokale Sensordaten**: Umweltinformationen von Sensoren in Ihrer Nähe
- **Automatisierungen**: Reagieren Sie auf Umweltveränderungen
- **Dashboard**: Schöne Übersichten in der Home Assistant Oberfläche

## Welche Daten sehen Sie?

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

## Was brauchen Sie?

- Python 3.13.2 oder neuer
- Home Assistant (Version 2025.7.0 oder neuer)
- HACS (Home Assistant Community Store) - für die einfache Installation
- Internetverbindung

## Installation

### Installation über HACS (Empfohlen)

1. **Repository in HACS hinzufügen (Custom Repository)**:
   - Öffnen Sie HACS in der Seitenleiste
   - Klicken Sie auf **⋯** (drei Punkte oben rechts)
   - Wählen Sie **Benutzerdefiniertes Repository**
   - Fügen Sie diese URL hinzu: `https://github.com/makerspace-partheland/smartcity-sensorbridge-partheland`
   - Typ: Integration
   - Klicken Sie auf Hinzufügen

2. **Integration installieren**
   - Öffnen Sie in HACS den Bereich **Integrationen**
   - Klicken Sie auf ***SmartCity SensorBridge Partheland*** → **Installieren**
   - Starten Sie Home Assistant neu

3. **Integration einrichten**:
   - Gehen Sie zu **Einstellungen** → **Geräte & Dienste**
   - Klicken Sie auf **+ Integration hinzufügen**
   - Suchen Sie nach "SmartCity SensorBridge Partheland"
   - Folgen Sie der Einrichtung

### Manuelle Installation (für Fortgeschrittene)

1. Laden Sie die Dateien herunter
2. Kopieren Sie den Ordner `custom_components/sensorbridge_partheland/` in Ihr Home Assistant
3. Starten Sie Home Assistant neu

## Einrichtung

Die Integration ist sehr einfach zu konfigurieren:

1. **Integration hinzufügen** (siehe Installation oben)
2. **Konfiguration bestätigen** - die Standardeinstellungen funktionieren sofort
3. **Fertig!**

Die Integration lädt automatisch alle verfügbaren Sensoren und zeigt sie in Home Assistant an.

## Hilfe bei Problemen

### Häufige Fragen

#### Ich sehe keine Daten

- Prüfen Sie, ob die Integration korrekt installiert ist
- Schauen Sie in die Logs (siehe unten)

#### Die Werte sind falsch

- Die Sensoren werden regelmäßig kalibriert
- Kontaktieren Sie uns bei Problemen

#### Wie aktualisiere ich die Integration?

- Über HACS: Automatische Updates
- Manuell: Neue Version herunterladen

#### Wie entferne ich ein Gerät/Entitäten?

- Über die Geräte-Ansicht: Einstellungen → Geräte & Dienste → Geräte → Gerät öffnen → 3-Punkte → Gerät löschen. Die Integration unterstützt das direkte Entfernen; dabei werden zugehörige Entitäten mit entfernt.
- Über die Integrations-Optionen: Integration öffnen → Optionen → das Gerät (oder Median-Entity) abwählen → Speichern. Beim anschließenden Reload werden nicht mehr ausgewählte Entitäten/Geräte automatisch aus den Registern bereinigt.

### Logs prüfen

Fügen Sie dies zu Ihrer `configuration.yaml` hinzu:

```yaml
logger:
  custom_components.sensorbridge_partheland: debug
```

## Updates

- **Automatisch**: HACS zeigt Updates an. Zusätzlich halten GitHub Actions die Abhängigkeiten wöchentlich aktuell (Patch/Minor) und erstellen PRs. Dependabot aktualisiert GitHub Actions-Versionen automatisch.
- **Manuell**: Neue Version herunterladen.

## Unterstützung

- **Probleme melden**: [GitHub Issues](https://github.com/makerspace-partheland/smartcity-sensorbridge-partheland/issues)
- **Community**: [Makerspace Partheland](https://makerspace-partheland.de)

## Lizenz

MIT License - Sie können die Software frei nutzen und anpassen.

---

**Tipp**: Diese Integration ist Teil des SmartCity-Projekts Partheland. Weitere Informationen finden Sie auf [makerspace-partheland.de](https://makerspace-partheland.de).
