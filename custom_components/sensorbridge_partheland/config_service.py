"""
Config Service für SmartCity SensorBridge Partheland
HA 2025 Compliant - Zentrale Konfigurationsverwaltung
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import CONFIG_FILE, TRANSLATIONS_DIR, DOMAIN
from .interfaces import ConfigServiceProtocol

_LOGGER = logging.getLogger(__name__)


class ConfigService(ConfigServiceProtocol):
    """Zentrale Konfigurationsverwaltung für SmartCity SensorBridge."""
    
    def __init__(self, hass: HomeAssistant) -> None:
        """Initialisiert den Config Service."""
        self.hass = hass
        self._config: Optional[Dict[str, Any]] = None
        self._config_path = Path(__file__).parent / CONFIG_FILE
    
    async def load_config(self) -> Dict[str, Any]:
        """Lädt die Konfiguration asynchron."""
        if self._config is None:
            try:
                _LOGGER.debug("Lade Konfiguration von %s", self._config_path)
                
                # Prüfe ob Datei existiert
                if not self._config_path.exists():
                    _LOGGER.error("Konfigurationsdatei nicht gefunden: %s", self._config_path)
                    self._config = {}
                    return self._config
                
                # Datei asynchron lesen
                config_content = await self.hass.async_add_executor_job(
                    self._read_config_file
                )
                
                # JSON asynchron parsen
                self._config = await self.hass.async_add_executor_job(
                    json.loads, config_content
                )
                
                # Prüfe ob erforderliche Schlüssel vorhanden sind
                required_keys = ["mqtt_config", "known_devices", "sensor_categories", "field_mapping"]
                missing_keys = [key for key in required_keys if key not in self._config]
                
                if missing_keys:
                    _LOGGER.error("Fehlende Konfigurationsschlüssel: %s", missing_keys)
                    self._config = {}
                else:
                    _LOGGER.debug("Konfiguration erfolgreich geladen")
                    
            except json.JSONDecodeError as e:
                _LOGGER.error("JSON-Fehler beim Laden der Konfiguration: %s", e)
                self._config = {}
            except Exception as e:
                _LOGGER.error("Fehler beim Laden der Konfiguration: %s", e)
                self._config = {}
        
        return self._config
    
    def _read_config_file(self) -> str:
        """Liest die Konfigurationsdatei synchron."""
        return self._config_path.read_text(encoding='utf-8')
    
    async def get_devices(self) -> Dict[str, Any]:
        """Gibt alle verfügbaren Geräte zurück."""
        config = await self.load_config()
        return config.get("known_devices", {})
    
    async def get_median_entities(self) -> List[Dict[str, Any]]:
        """Gibt alle Median-Entities zurück."""
        devices = await self.get_devices()
        median_entities = devices.get("MedianEntities", [])
        
        # Device-Type hinzufügen
        for entity in median_entities:
            entity["type"] = "median"
        
        return median_entities
    
    async def get_sensor_categories(self) -> Dict[str, List[str]]:
        """Gibt die Sensor-Kategorien zurück."""
        config = await self.load_config()
        return config.get("sensor_categories", {})
    
    async def get_field_mapping(self) -> Dict[str, Any]:
        """Gibt das Field-Mapping zurück."""
        config = await self.load_config()
        return config.get("field_mapping", {})
    
    async def get_mqtt_config(self) -> Dict[str, Any]:
        """Gibt die MQTT-Konfiguration zurück."""
        config = await self.load_config()
        return config.get("mqtt_config", {})
    
    async def get_parsing_config(self) -> Dict[str, Any]:
        """Gibt die Parsing-Konfiguration zurück."""
        config = await self.load_config()
        return config.get("parsing", {})
    
    async def validate_config(self) -> bool:
        """Validiert die Konfiguration."""
        try:
            config = await self.load_config()
            
            # Prüfe erforderliche Top-Level-Keys
            required_keys = ["mqtt_config", "known_devices", "sensor_categories", "field_mapping"]
            for key in required_keys:
                if key not in config:
                    _LOGGER.error("Erforderlicher Konfigurationsschlüssel fehlt: %s", key)
                    return False
            
            # Prüfe MQTT-Konfiguration
            mqtt_config = config["mqtt_config"]
            if "broker_url" not in mqtt_config or "topics" not in mqtt_config:
                _LOGGER.error("Ungültige MQTT-Konfiguration")
                return False
            
            # Prüfe bekannte Geräte
            known_devices = config["known_devices"]
            if not isinstance(known_devices, dict):
                _LOGGER.error("Ungültige Geräte-Konfiguration")
                return False
            
            _LOGGER.debug("Konfiguration erfolgreich validiert")
            return True
            
        except Exception as e:
            _LOGGER.error("Fehler bei der Konfigurationsvalidierung: %s", e)
            return False
    
    async def get_device_by_id(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Gibt ein spezifisches Gerät nach ID zurück."""
        devices = await self.get_devices()
        
        # Durch alle Gerätetypen iterieren
        for device_type, device_list in devices.items():
            if isinstance(device_list, list):
                for device in device_list:
                    if device.get("id") == device_id:
                        # Device-Type hinzufügen
                        device["type"] = device_type
                        return device
        
        return None
    
    async def get_median_by_id(self, median_id: str) -> Optional[Dict[str, Any]]:
        """Gibt eine spezifische Median-Entity nach ID zurück."""
        median_entities = await self.get_median_entities()
        
        for median in median_entities:
            if median.get("id") == median_id:
                return median
        
        return None
    
    async def get_devices_by_type(self, device_type: str) -> List[Dict[str, Any]]:
        """Gibt alle Geräte eines bestimmten Typs zurück."""
        devices = await self.get_devices()
        return devices.get(device_type, [])
    
    async def get_sensor_names(self) -> Dict[str, str]:
        """Gibt die Sensor-Namen-Übersetzungen zurück."""
        try:
            # Verwende die moderne Home Assistant 2025 API für Übersetzungen
            from homeassistant.helpers.translation import async_get_translations
            
            # Sensor-Namen aus den Übersetzungsdateien laden
            translations = await async_get_translations(
                self.hass, 
                self.hass.config.language, 
                "entity", 
                [DOMAIN]
            )
            
            # Sensor-Namen aus den Übersetzungen extrahieren
            sensor_names = translations.get("sensor_names", {})
            
            _LOGGER.debug("Sensor-Namen geladen: %s", sensor_names)
            return sensor_names
            
        except Exception as e:
            _LOGGER.warning("Fehler beim Laden der Sensor-Namen-Übersetzungen: %s", e)
            return {}
    
    async def get_device_categories(self) -> Dict[str, str]:
        """Gibt die Geräte-Kategorien-Übersetzungen zurück."""
        try:
            # Verwende den TranslationHelper für die moderne HA 2025 API
            from .translation_helper import TranslationHelper
            
            translation_helper = TranslationHelper(self.hass)
            device_categories = await translation_helper.get_device_categories()
            
            _LOGGER.debug("Geräte-Kategorien geladen: %s", device_categories)
            return device_categories
            
        except Exception as e:
            _LOGGER.warning("Fehler beim Laden der Geräte-Kategorien-Übersetzungen: %s", e)
            return {}
    
    async def get_icons(self) -> Dict[str, str]:
        """Gibt die Icon-Mappings zurück."""
        config = await self.load_config()
        field_mapping = config.get("field_mapping", {})
        return field_mapping.get("icons", {})
    
    async def get_device_class_mapping(self) -> Dict[str, Any]:
        """Gibt das Device Class Mapping zurück."""
        # Import asynchron im Event Loop
        from homeassistant.components.sensor import SensorDeviceClass
        
        # Device Class Enums aus der Konfiguration laden
        config = await self.load_config()
        field_mapping = config.get("field_mapping", {})
        device_class_enums = field_mapping.get("device_class_enums", {})
        
        # String-Mappings zu echten Enums konvertieren
        device_class_mapping = {}
        for enum_name, enum_string in device_class_enums.items():
            if enum_string == "SensorDeviceClass.TEMPERATURE":
                device_class_mapping[enum_name] = SensorDeviceClass.TEMPERATURE
            elif enum_string == "SensorDeviceClass.HUMIDITY":
                device_class_mapping[enum_name] = SensorDeviceClass.HUMIDITY
            elif enum_string == "SensorDeviceClass.PRESSURE":
                device_class_mapping[enum_name] = SensorDeviceClass.PRESSURE
            elif enum_string == "SensorDeviceClass.PM25":
                device_class_mapping[enum_name] = SensorDeviceClass.PM25
            elif enum_string == "SensorDeviceClass.PM10":
                device_class_mapping[enum_name] = SensorDeviceClass.PM10
            elif enum_string == "SensorDeviceClass.ILLUMINANCE":
                device_class_mapping[enum_name] = SensorDeviceClass.ILLUMINANCE
            elif enum_string == "SensorDeviceClass.SOUND_PRESSURE":
                device_class_mapping[enum_name] = SensorDeviceClass.SOUND_PRESSURE
            elif enum_string == "SensorDeviceClass.IRRADIANCE":
                device_class_mapping[enum_name] = SensorDeviceClass.IRRADIANCE
            elif enum_string == "None":
                # Für nicht unterstützte Device Classes (wie WATER_LEVEL)
                device_class_mapping[enum_name] = None
        
        return device_class_mapping
    
    async def get_ui_text(self) -> Dict[str, str]:
        """Gibt die UI-Texte zurück."""
        try:
            # Verwende den TranslationHelper für die moderne HA 2025 API
            from .translation_helper import TranslationHelper
            
            translation_helper = TranslationHelper(self.hass)
            ui_text = await translation_helper.get_ui_text()
            
            _LOGGER.debug("UI-Texte geladen: %s", ui_text)
            return ui_text
            
        except Exception as e:
            _LOGGER.warning("Fehler beim Laden der UI-Texte: %s", e)
            return {}
    
    async def get_error_messages(self) -> Dict[str, str]:
        """Gibt die Fehlermeldungen zurück."""
        try:
            # Verwende den TranslationHelper für die moderne HA 2025 API
            from .translation_helper import TranslationHelper
            
            translation_helper = TranslationHelper(self.hass)
            error_messages = await translation_helper.get_error_messages()
            
            _LOGGER.debug("Fehlermeldungen geladen: %s", error_messages)
            return error_messages
            
        except Exception as e:
            _LOGGER.warning("Fehler beim Laden der Fehlermeldungen: %s", e)
            return {}
    
    async def debug_translations(self) -> Dict[str, Any]:
        """Debug-Methode um die Translation-Ladung zu überprüfen."""
        try:
            from .translation_helper import TranslationHelper
            
            translation_helper = TranslationHelper(self.hass)
            debug_info = await translation_helper.debug_translations()
            
            # Zusätzliche Info: Verfügbare Sensor-Namen
            sensor_names = await self.get_sensor_names()
            debug_info["config_service_sensor_names"] = sensor_names
            
            _LOGGER.info("ConfigService Translation Debug: %s", debug_info)
            return debug_info
            
        except Exception as e:
            _LOGGER.error("Fehler beim Debug der Übersetzungen im ConfigService: %s", e)
            return {"error": str(e)} 