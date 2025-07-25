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

- Home Assistant (Version 2025.7.0 oder neuer)
- HACS (Home Assistant Community Store) - für die einfache Installation
- Internetverbindung

## Installation

### Installation über HACS (Empfohlen)

1. **Repository in HACS hinzufügen**:
   - Öffnen Sie HACS in der Seitenleiste
   - Klicken Sie auf **...**
   - Klicken Sie auf **Benutzerdefinierte Repositories**
   - Fügen Sie diese URL hinzu: `https://github.com/makerspace-partheland/smartcity-sensorbridge-partheland`
   - Typ: Integration
   - Klicken Sie auf Hinzufügen

2. **Diese Integration hinzufügen**
   - Suchen Sie in HACS nach ***SmartCity SensorBridge Partheland***
   - Herunterladen klicken
   - Home Assistant neu starten

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

**Q: Ich sehe keine Daten**
- Prüfen Sie, ob die Integration korrekt installiert ist
- Schauen Sie in die Logs (siehe unten)

**Q: Die Werte sind falsch**
- Die Sensoren werden regelmäßig kalibriert
- Kontaktieren Sie uns bei Problemen

**Q: Wie aktualisiere ich die Integration?**
- Über HACS: Automatische Updates
- Manuell: Neue Version herunterladen

### Logs prüfen

Fügen Sie dies zu Ihrer `configuration.yaml` hinzu:

```yaml
logger:
  custom_components.sensorbridge_partheland: debug
```

## Updates

- **Automatisch**: HACS zeigt Updates an
- **Manuell**: Neue Version herunterladen

## Unterstützung

- **Probleme melden**: [GitHub Issues](https://github.com/makerspace-partheland/smartcity-sensorbridge-partheland/issues)
- **Community**: [Makerspace Partheland](https://makerspace-partheland.de)

## Lizenz

MIT License - Sie können die Software frei nutzen und anpassen.

## Danksagungen

- SmartCity Partheland Team für die Sensordaten
- Home Assistant Community für die großartige Plattform
- Makerspace Partheland e.V. für die Unterstützung

---

**Tipp**: Diese Integration ist Teil des SmartCity-Projekts Partheland. Weitere Informationen finden Sie auf [makerspace-partheland.de](https://makerspace-partheland.de).
