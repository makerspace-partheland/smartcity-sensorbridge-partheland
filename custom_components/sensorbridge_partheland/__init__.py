"""
SmartCity SensorBridge Partheland Integration
HA 2025 Compliant - Moderne Integration für Umweltsensorik
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .config_service import ConfigService
from .mqtt_service import MQTTService
from .parser_service import ParserService
from .entity_factory import EntityFactory
from .error_handler import ErrorHandler
from .translation_helper import TranslationHelper

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the SmartCity SensorBridge Partheland integration."""
    try:
        _LOGGER.info("Setting up SmartCity SensorBridge Partheland")
        
        # Domain in hass.data initialisieren
        hass.data.setdefault(DOMAIN, {})
        
        # Services asynchron initialisieren
        await _async_initialize_services(hass)
        
        # Debug-Services registrieren (nur wenn noch nicht registriert)
        try:
            hass.services.async_register(DOMAIN, "debug_translations", debug_translations_service)
            hass.services.async_register(DOMAIN, "test_translations", test_translations_service)
            hass.services.async_register(DOMAIN, "debug_translation_file", debug_translation_file_service)
            _LOGGER.debug("Debug-Services erfolgreich registriert")
        except Exception as e:
            _LOGGER.warning("Fehler bei der Service-Registrierung: %s", e)
        
        _LOGGER.info("SmartCity SensorBridge Partheland erfolgreich initialisiert")
        return True
        
    except Exception as e:
        _LOGGER.error("Fehler beim Setup der Integration: %s", e)
        return False


async def _async_initialize_services(hass: HomeAssistant) -> None:
    """Initialisiert alle Services asynchron."""
    try:
        # Services asynchron initialisieren
        config_service = await hass.async_add_executor_job(ConfigService, hass)
        mqtt_service = MQTTService(hass, config_service)  # Direkt erstellen, da async
        parser_service = await hass.async_add_executor_job(ParserService, hass, config_service)
        entity_factory = await hass.async_add_executor_job(EntityFactory, hass, config_service)
        error_handler = await hass.async_add_executor_job(ErrorHandler, hass)
        translation_helper = await hass.async_add_executor_job(TranslationHelper, hass)

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
        hass.data[DOMAIN]["config_service"] = await hass.async_add_executor_job(ConfigService, hass)
        hass.data[DOMAIN]["mqtt_service"] = None
        hass.data[DOMAIN]["parser_service"] = None
        hass.data[DOMAIN]["entity_factory"] = None
        hass.data[DOMAIN]["error_handler"] = await hass.async_add_executor_job(ErrorHandler, hass)
        hass.data[DOMAIN]["translation_helper"] = None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SmartCity SensorBridge Partheland from a config entry."""
    try:
        _LOGGER.info("Setting up SmartCity SensorBridge Partheland config entry: %s", entry.entry_id)
        
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
            error_handler=error_handler
        )
        
        # Coordinator in hass.data speichern
        hass.data[DOMAIN][entry.entry_id] = coordinator
        
        # Config Entry Daten loggen
        selected_devices = entry.data.get("selected_devices", [])
        selected_median_entities = entry.data.get("selected_median_entities", [])
        _LOGGER.debug("Config: selected_devices=%s, selected_median_entities=%s", 
                     selected_devices, selected_median_entities)
        
        # Coordinator starten
        await coordinator.async_config_entry_first_refresh()
        
        # Platforms asynchron laden
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        
        _LOGGER.info("SmartCity SensorBridge Partheland successfully set up with %d devices and %d median entities",
                    len(selected_devices), len(selected_median_entities))
        
        return True
        
    except Exception as e:
        _LOGGER.error("Fehler beim Setup der Config Entry: %s", e)
        return False


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading SensorBridge integration")
    
    # Coordinator entfernen
    if entry.entry_id in hass.data[DOMAIN]:
        coordinator = hass.data[DOMAIN][entry.entry_id]
        await coordinator.async_shutdown()
        del hass.data[DOMAIN][entry.entry_id]
    
    # Config Service entfernen
    if "config_service" in hass.data[DOMAIN]:
        del hass.data[DOMAIN]["config_service"]
    
    # MQTT Service entfernen
    if "mqtt_service" in hass.data[DOMAIN]:
        mqtt_service = hass.data[DOMAIN]["mqtt_service"]
        await mqtt_service.disconnect()
        del hass.data[DOMAIN]["mqtt_service"]
    
    # Parser Service entfernen
    if "parser_service" in hass.data[DOMAIN]:
        del hass.data[DOMAIN]["parser_service"]
    
    # Entity Factory entfernen
    if "entity_factory" in hass.data[DOMAIN]:
        del hass.data[DOMAIN]["entity_factory"]
    
    # Translation Helper entfernen
    if "translation_helper" in hass.data[DOMAIN]:
        del hass.data[DOMAIN]["translation_helper"]
    
    # Error Handler entfernen
    if "error_handler" in hass.data[DOMAIN]:
        del hass.data[DOMAIN]["error_handler"]
    
    # Domain komplett entfernen wenn leer
    if not hass.data[DOMAIN]:
        del hass.data[DOMAIN]
    
    _LOGGER.info("SensorBridge integration unloaded successfully")
    return True

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
            from homeassistant.helpers.translation import async_get_translations
            
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
            entity_registry = homeassistant.helpers.entity_registry.async_get(hass)
            
            if entity_registry:
                for entity_id, entity in entity_registry.entities.items():
                    if entity.domain == "sensor" and DOMAIN in entity_id:
                        _LOGGER.info("Entity %s:", entity_id)
                        _LOGGER.info("  - translation_key: %s", getattr(entity, 'translation_key', 'N/A'))
                        _LOGGER.info("  - has_entity_name: %s", getattr(entity, 'has_entity_name', 'N/A'))
                        _LOGGER.info("  - name: %s", getattr(entity, 'name', 'N/A'))
                        
                        # Translation für diese Entity testen
                        translation_key = getattr(entity, 'translation_key', None)
                        if translation_key and translation_key in sensor_translations:
                            _LOGGER.info("  - Translation gefunden: %s", sensor_translations[translation_key])
                        else:
                            _LOGGER.warning("  - Keine Translation gefunden für key: %s", translation_key)
            
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
                friendly_name = entity.attributes.get("friendly_name", entity.name)
                _LOGGER.info("Entity %s: %s", entity_id, friendly_name)
            else:
                _LOGGER.warning("Entity %s nicht in States gefunden", entity_id)
        
        _LOGGER.info("Translation Test Service abgeschlossen")
        
    except Exception as e:
        _LOGGER.error("Fehler im Translation Test Service: %s", e)

async def debug_translation_file_service(hass: HomeAssistant, call) -> None:
    """Service zum direkten Debug der Translation-Datei."""
    try:
        _LOGGER.info("=== TRANSLATION FILE DEBUG ===")
        
        # Translation-Datei direkt lesen
        import os
        import json
        
        translation_file = os.path.join(
            hass.config.config_dir, 
            "custom_components", 
            "sensorbridge_partheland", 
            "translations", 
            "de.json"
        )
        
        _LOGGER.info("Translation file path: %s", translation_file)
        _LOGGER.info("File exists: %s", os.path.exists(translation_file))
        
        if os.path.exists(translation_file):
            with open(translation_file, 'r', encoding='utf-8') as f:
                content = f.read()
                _LOGGER.info("File content length: %d", len(content))
                _LOGGER.info("File content: %s", content)
                
                # JSON validieren
                try:
                    data = json.loads(content)
                    _LOGGER.info("JSON is valid")
                    _LOGGER.info("Entity sensor keys: %s", list(data.get("entity", {}).get("sensor", {}).keys()))
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