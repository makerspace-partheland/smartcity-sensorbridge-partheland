"""
SmartCity SensorBridge Partheland Integration
HA 2025 Compliant - Moderne Integration für Umweltsensorik
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .config_service import ConfigService
from .const import DOMAIN, PLATFORMS, CONF_SELECTED_DEVICES, CONF_SELECTED_MEDIAN_ENTITIES
from .entity_factory import EntityFactory
from .error_handler import ErrorHandler
from .mqtt_service import MQTTService
from .parser_service import ParserService
from .translation_helper import TranslationHelper
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import device_registry as dr

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the SmartCity SensorBridge Partheland integration."""
    try:
        _LOGGER.info("Setting up SmartCity SensorBridge Partheland")

        # Domain in hass.data initialisieren
        hass.data.setdefault(DOMAIN, {})

        # Services asynchron initialisieren
        await _async_initialize_services(hass)

        # Hinweis: Geräte-Icons werden nicht separat gecacht – Gerätelisten-Icons stammen
        # aus der primären Entität (MDI), nicht aus benutzerdefinierten Mappings.

        # Debug-Services registrieren (nur wenn noch nicht registriert)
        try:
            hass.services.async_register(
                DOMAIN, "debug_translations", debug_translations_service
            )
            hass.services.async_register(
                DOMAIN, "test_translations", test_translations_service
            )
            hass.services.async_register(
                DOMAIN,
                "debug_translation_file",
                debug_translation_file_service,
            )
            _LOGGER.debug("Debug-Services erfolgreich registriert")
        except Exception as e:
            _LOGGER.warning("Fehler bei der Service-Registrierung: %s", e)

        _LOGGER.info(
            "SmartCity SensorBridge Partheland erfolgreich initialisiert"
        )
        return True

    except Exception as e:
        _LOGGER.error("Fehler beim Setup der Integration: %s", e)
        return False


async def _async_initialize_services(hass: HomeAssistant) -> None:
    """Initialisiert alle Services asynchron."""
    try:
        # Services asynchron initialisieren
        config_service = await hass.async_add_executor_job(ConfigService, hass)
        # Direkt erstellen, da async
        mqtt_service = MQTTService(hass, config_service)
        parser_service = await hass.async_add_executor_job(
            ParserService, hass, config_service
        )
        entity_factory = await hass.async_add_executor_job(
            EntityFactory, hass, config_service
        )
        error_handler = await hass.async_add_executor_job(ErrorHandler, hass)
        translation_helper = await hass.async_add_executor_job(
            TranslationHelper, hass
        )

        # Services in hass.data speichern
        hass.data[DOMAIN]["config_service"] = config_service
        hass.data[DOMAIN]["mqtt_service"] = mqtt_service
        hass.data[DOMAIN]["parser_service"] = parser_service
        hass.data[DOMAIN]["entity_factory"] = entity_factory
        hass.data[DOMAIN]["error_handler"] = error_handler
        hass.data[DOMAIN]["translation_helper"] = translation_helper

        # Konfiguration validieren
        if not await config_service.validate_config():
            _LOGGER.error("Konfigurationsvalidierung fehlgeschlagen")
            return

        _LOGGER.debug("Alle Services erfolgreich initialisiert")

    except Exception as e:
        _LOGGER.error("Fehler bei der Service-Initialisierung: %s", e)
        # Fallback: Leere Services erstellen
        hass.data[DOMAIN]["config_service"] = (
            await hass.async_add_executor_job(ConfigService, hass)
        )
        hass.data[DOMAIN]["mqtt_service"] = None
        hass.data[DOMAIN]["parser_service"] = None
        hass.data[DOMAIN]["entity_factory"] = None
        hass.data[DOMAIN]["error_handler"] = await hass.async_add_executor_job(
            ErrorHandler, hass
        )
        hass.data[DOMAIN]["translation_helper"] = None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SmartCity SensorBridge Partheland from a config entry."""
    try:
        _LOGGER.info(
            "Setting up SmartCity SensorBridge Partheland config entry: %s",
            entry.entry_id,
        )

        # Sicherstellen, dass die Services initialisiert sind
        if DOMAIN not in hass.data:
            hass.data[DOMAIN] = {}

        required_keys = {
            "config_service",
            "mqtt_service",
            "parser_service",
            "entity_factory",
            "error_handler",
            "translation_helper",
        }

        if not required_keys.issubset(hass.data[DOMAIN]):
            _LOGGER.debug(
                "Services not initialized. Initializing services now"
            )
            await _async_initialize_services(hass)

        # Services aus hass.data holen
        config_service = hass.data[DOMAIN]["config_service"]
        mqtt_service = hass.data[DOMAIN]["mqtt_service"]
        parser_service = hass.data[DOMAIN]["parser_service"]
        entity_factory = hass.data[DOMAIN]["entity_factory"]
        error_handler = hass.data[DOMAIN]["error_handler"]

        # Coordinator erstellen
        from .coordinator import SensorBridgeCoordinator

        coordinator = SensorBridgeCoordinator(
            hass=hass,
            entry=entry,
            config_service=config_service,
            mqtt_service=mqtt_service,
            parser_service=parser_service,
            entity_factory=entity_factory,
            error_handler=error_handler,
        )

        # Coordinator in hass.data speichern
        hass.data[DOMAIN][entry.entry_id] = coordinator

        # Config Entry Daten loggen
        selected_devices = entry.data.get("selected_devices", [])
        selected_median_entities = entry.data.get(
            "selected_median_entities", []
        )
        _LOGGER.debug(
            "Config: selected_devices=%s, selected_median_entities=%s",
            selected_devices,
            selected_median_entities,
        )

        # Coordinator starten
        await coordinator.async_config_entry_first_refresh()

        # Plattformen laden (idempotent): Vor erneutem Setup sicherstellen, dass nicht doppelt geladen wird
        try:
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        except ValueError as e:
            # "has already been setup" vermeiden: vorher entladen und erneut laden
            _LOGGER.warning("Platform already setup, reloading platforms: %s", e)
            await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        # Nach dem (Neu-)Setup: Nicht mehr ausgewählte Entitäten/Geräte aus den Registern entfernen
        try:
            await _async_cleanup_unselected_entities_and_devices(hass, entry)
        except Exception as cleanup_err:
            _LOGGER.warning(
                "Cleanup der nicht ausgewählten Entitäten/Geräte fehlgeschlagen: %s",
                cleanup_err,
            )

        _LOGGER.info(
            (
                "SmartCity SensorBridge Partheland successfully set up with "
                "%d devices and %d median entities"
            ),
            len(selected_devices),
            len(selected_median_entities),
        )

        return True

    except Exception as e:
        _LOGGER.error("Fehler beim Setup der Config Entry: %s", e)
        return False


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading SensorBridge integration")

    # 1) Zuerst Plattformen sauber entladen (entfernt Entities/Devices korrekt)
    try:
        platforms_unloaded = await hass.config_entries.async_unload_platforms(
            entry, PLATFORMS
        )
        if not platforms_unloaded:
            _LOGGER.warning("Nicht alle Plattformen konnten entladen werden")
    except Exception as e:
        _LOGGER.error("Fehler beim Entladen der Plattformen: %s", e)

    # 2) Laufende Tasks/Services herunterfahren
    try:
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            coordinator = hass.data[DOMAIN][entry.entry_id]
            await coordinator.async_shutdown()
            del hass.data[DOMAIN][entry.entry_id]
    except Exception as e:
        _LOGGER.debug("Coordinator Shutdown Warnung: %s", e)

    try:
        mqtt_service = hass.data[DOMAIN].get("mqtt_service")
        if mqtt_service:
            await mqtt_service.disconnect()
            del hass.data[DOMAIN]["mqtt_service"]
    except Exception as e:
        _LOGGER.debug("MQTT Disconnect Warnung: %s", e)

    # 3) Restliche Referenzen entfernen
    for key in [
        "config_service",
        "parser_service",
        "entity_factory",
        "translation_helper",
        "error_handler",
    ]:
        if key in hass.data.get(DOMAIN, {}):
            del hass.data[DOMAIN][key]

    if DOMAIN in hass.data and not hass.data[DOMAIN]:
        del hass.data[DOMAIN]

    _LOGGER.info("SensorBridge integration unloaded successfully")
    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry
) -> bool:
    """Ermöglicht das direkte Löschen eines Geräts in der Geräte-Ansicht.

    - Entfernt die Geräte-/Median-ID aus der Auswahl im Config Entry
    - Triggert ein Reload, Cleanup entfernt verbleibende Entitäten/Geräte
    - Rückgabe True erlaubt Home Assistant, das Gerät zu entfernen
    """

    try:
        # Externe ID (unsere device_id/median_id) aus den Identifiers extrahieren
        external_ids = [did for (dom, did) in device_entry.identifiers if dom == DOMAIN]
        if not external_ids:
            return False

        external_id = external_ids[0]

        data = dict(entry.data)
        changed = False

        # Aus ausgewählten Geräten entfernen
        if external_id in data.get(CONF_SELECTED_DEVICES, []):
            data[CONF_SELECTED_DEVICES] = [d for d in data.get(CONF_SELECTED_DEVICES, []) if d != external_id]
            changed = True

        # Aus ausgewählten Median-Entities entfernen
        if external_id in data.get(CONF_SELECTED_MEDIAN_ENTITIES, []):
            data[CONF_SELECTED_MEDIAN_ENTITIES] = [
                m for m in data.get(CONF_SELECTED_MEDIAN_ENTITIES, []) if m != external_id
            ]
            changed = True

        if changed:
            # 1) Config-Entry aktualisieren (damit Auswahl konsistent ist)
            hass.config_entries.async_update_entry(entry, data=data)

        # 2) Entitäten dieses Geräts direkt entfernen (korrekte Filterung: über config_entry_id & device_id)
        entity_registry = er.async_get(hass)
        for ent_id, reg_entry in list(entity_registry.entities.items()):
            if reg_entry.config_entry_id == entry.entry_id and reg_entry.device_id == device_entry.id:
                entity_registry.async_remove(ent_id)

        # 3) Verknüpfung des Geräts zur Config Entry lösen und Gerät entfernen
        device_registry = dr.async_get(hass)
        try:
            try:
                device_registry.async_update_device(
                    device_entry.id, remove_config_entry_id=entry.entry_id
                )
            except Exception as link_err:
                _LOGGER.debug("Konnte ConfigEntry-Verknüpfung nicht lösen: %s", link_err)

            # Gerät entfernen; falls noch andere Config-Entries verknüpft sind, ignoriert Core dies
            device_registry.async_remove_device(device_entry.id)
        except Exception as dev_err:
            _LOGGER.debug("Gerät konnte nicht direkt entfernt werden: %s", dev_err)

        # 4) Ausstehende Tasks verarbeiten, UI-Update beschleunigen
        try:
            await hass.async_block_till_done()
        except Exception:
            pass

        return True

    except Exception as e:
        _LOGGER.error("Fehler beim Entfernen des Geräts über UI: %s", e)
        return False


async def _async_cleanup_unselected_entities_and_devices(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Entfernt Entitäten und Geräte dieser Integration, die nicht mehr ausgewählt sind.

    Vorgehen:
    - Ermittelt `selected_devices` und `selected_median_entities` aus dem Config Entry
    - Durchläuft die Entity Registry (nur Plattform == DOMAIN)
    - Ermittelt die externe ID über die Device-Identifiers (DOMAIN, external_id)
    - Entfernt Entitäten, deren externe ID nicht mehr ausgewählt ist
    - Entfernt anschließend verwaiste Geräte ohne verbleibende Entitäten
    """

    selected_devices = set(entry.data.get("selected_devices", []))
    selected_median = set(entry.data.get("selected_median_entities", []))

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    # 1) Nicht mehr ausgewählte Entitäten entfernen (nur solche unseres Config-Entries)
    for entity_id, reg_entry in list(entity_registry.entities.items()):
        if reg_entry.config_entry_id != entry.entry_id:
            continue

        device_entry = device_registry.async_get(reg_entry.device_id)
        if not device_entry:
            continue

        external_ids = [did for (dom, did) in device_entry.identifiers if dom == DOMAIN]
        if not external_ids:
            continue

        external_id = external_ids[0]
        is_selected = (external_id in selected_devices) or (external_id in selected_median)
        if not is_selected:
            entity_registry.async_remove(entity_id)

    # 2) Geräte ohne Entitäten entfernen
    for device_id, device_entry in list(device_registry.devices.items()):
        if not any(dom == DOMAIN for dom, _ in device_entry.identifiers):
            continue

        has_entities = any(
            (reg_entry.device_id == device_id) and (reg_entry.platform == DOMAIN)
            for reg_entry in entity_registry.entities.values()
        )

        if not has_entities:
            try:
                device_registry.async_remove_device(device_id)
            except Exception as e:
                _LOGGER.debug("Konnte Gerät %s nicht entfernen: %s", device_id, e)


async def debug_translations_service(hass: HomeAssistant, call) -> None:
    """Service zum Debug der Übersetzungen."""
    try:
        _LOGGER.info("Translation Debug Service gestartet")

        if DOMAIN not in hass.data:
            _LOGGER.error("Domain %s nicht in hass.data gefunden", DOMAIN)
            return

        config_service = hass.data[DOMAIN].get("config_service")
        if config_service:
            # Translation-API direkt testen
            from homeassistant.helpers.translation import \
                async_get_translations

            translations = await async_get_translations(
                hass, hass.config.language, "entity", [DOMAIN]
            )

            _LOGGER.info("=== TRANSLATION DEBUG ===")
            _LOGGER.info("Language: %s", hass.config.language)
            _LOGGER.info("Domain: %s", DOMAIN)
            _LOGGER.info("Raw translations: %s", translations)

            # Sensor-Translations extrahieren
            sensor_translations = translations.get("sensor", {})
            _LOGGER.info("Sensor translations: %s", sensor_translations)

            # Alle Sensor-Entities finden und testen
            import homeassistant.helpers.entity_registry

            entity_registry = (
                homeassistant.helpers.entity_registry.async_get(hass)
            )

            if entity_registry:
                for entity_id, entity in entity_registry.entities.items():
                    if entity.domain == "sensor" and DOMAIN in entity_id:
                        _LOGGER.info("Entity %s:", entity_id)
                        _LOGGER.info(
                            "  - translation_key: %s",
                            getattr(entity, "translation_key", "N/A"),
                        )
                        _LOGGER.info(
                            "  - has_entity_name: %s",
                            getattr(entity, "has_entity_name", "N/A"),
                        )
                        _LOGGER.info(
                            "  - name: %s", getattr(entity, "name", "N/A")
                        )

                        # Translation für diese Entity testen
                        translation_key = getattr(
                            entity, "translation_key", None
                        )
                        if (
                            translation_key
                            and translation_key in sensor_translations
                        ):
                            _LOGGER.info(
                                "  - Translation gefunden: %s",
                                sensor_translations[translation_key],
                            )
                        else:
                            _LOGGER.warning(
                                "  - Keine Translation gefunden für key: %s",
                                translation_key,
                            )

            debug_info = await config_service.debug_translations()
            _LOGGER.info("ConfigService Debug: %s", debug_info)

        else:
            _LOGGER.error("ConfigService nicht verfügbar")

    except Exception as e:
        _LOGGER.error("Fehler im Translation Debug Service: %s", e)


async def test_translations_service(hass: HomeAssistant, call) -> None:
    """Service zum Test der Übersetzungen für alle Sensor-Entities."""
    try:
        _LOGGER.info("Translation Test Service gestartet")

        # Alle Sensor-Entities finden
        sensor_entities = []

        # Entity Registry verwenden
        entity_registry = hass.helpers.entity_registry.async_get(hass)
        if entity_registry:
            for entity_id, entity in entity_registry.entities.items():
                if entity.domain == "sensor" and DOMAIN in entity_id:
                    sensor_entities.append(entity_id)

        _LOGGER.info("Gefundene Sensor-Entities: %s", sensor_entities)

        # Translation-Tests für jede Entity ausführen
        for entity_id in sensor_entities:
            entity = hass.states.get(entity_id)
            if entity:
                friendly_name = entity.attributes.get(
                    "friendly_name", entity.name
                )
                _LOGGER.info("Entity %s: %s", entity_id, friendly_name)
            else:
                _LOGGER.warning(
                    "Entity %s nicht in States gefunden", entity_id
                )

        _LOGGER.info("Translation Test Service abgeschlossen")

    except Exception as e:
        _LOGGER.error("Fehler im Translation Test Service: %s", e)


async def debug_translation_file_service(hass: HomeAssistant, call) -> None:
    """Service zum direkten Debug der Translation-Datei."""
    try:
        _LOGGER.info("=== TRANSLATION FILE DEBUG ===")

        # Translation-Datei direkt lesen
        import json
        import os

        translation_file = os.path.join(
            hass.config.config_dir,
            "custom_components",
            "sensorbridge_partheland",
            "translations",
            "de.json",
        )

        _LOGGER.info("Translation file path: %s", translation_file)
        _LOGGER.info("File exists: %s", os.path.exists(translation_file))

        if os.path.exists(translation_file):
            with open(translation_file, "r", encoding="utf-8") as f:
                content = f.read()
                _LOGGER.info("File content length: %d", len(content))
                _LOGGER.info("File content: %s", content)

                # JSON validieren
                try:
                    data = json.loads(content)
                    _LOGGER.info("JSON is valid")
                    _LOGGER.info(
                        "Entity sensor keys: %s",
                        list(data.get("entity", {}).get("sensor", {}).keys()),
                    )
                except json.JSONDecodeError as e:
                    _LOGGER.error("JSON validation failed: %s", e)

        # HA Translation API testen
        from homeassistant.helpers.translation import async_get_translations

        translations = await async_get_translations(
            hass, hass.config.language, "entity", [DOMAIN]
        )

        _LOGGER.info("HA Translation API result: %s", translations)

    except Exception as e:
        _LOGGER.error("Fehler im Translation File Debug Service: %s", e)
