# Versions- und Release-Regeln

## Ziel

Das Repository soll Abhängigkeiten, Tests und Dokumentation automatisch pflegen. Ein GitHub-Release ist nur dann sinnvoll, wenn sich die an Nutzer ausgelieferte Integration ändert.

## Wann `manifest.json` `version` erhöht werden muss

`custom_components/sensorbridge_partheland/manifest.json` `version` muss erhöht werden, wenn sich ausgelieferter Integrationsinhalt ändert:

- Änderungen unter `custom_components/sensorbridge_partheland/**`
- Änderungen an `custom_components/sensorbridge_partheland/manifest.json` `homeassistant`
- Änderungen an `custom_components/sensorbridge_partheland/manifest.json` `requirements`

## Wann `manifest.json` `version` nicht erhöht wird

Keine Versionserhöhung bei reiner Pflege des Repos:

- `requirements_test.txt`
- `README.md`
- `.github/workflows/**`
- `.github/scripts/**`
- reine Test-, CI- oder Dokuänderungen

## Regel für Abhängigkeitsaktualisierung

- PHACC-/HA-Teststack steigt: kein Release, keine Versionserhöhung
- nur CI/Test/Dokumentation wird angepasst: kein Release, keine Versionserhöhung
- Runtime-Code der Integration ändert sich wegen neuer HA-Version oder Dependency-Verhalten: Versionserhöhung nötig
- minimale unterstützte HA-Version im Manifest steigt: Versionserhöhung nötig
- Runtime-Abhängigkeit im Manifest ändert sich: Versionserhöhung nötig

## Umgang mit GitHub-Releases

- Ein GitHub-Release wird nur erstellt, wenn `manifest.json` `version` zuvor erhöht wurde
- Release-Tag und `manifest.json` `version` müssen zusammenpassen
- Kein Release nur wegen Test-, CI-, README- oder PHACC-Updates
