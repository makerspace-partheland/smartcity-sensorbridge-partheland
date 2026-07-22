"""
Config Service für SmartCity SensorBridge Partheland
HA 2025 Compliant - Zentrale Konfigurationsverwaltung
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api_client import DeviceCatalogClient, DeviceCatalogError, filter_selection_candidates
from .const import CONFIG_FILE
from .interfaces import ConfigServiceProtocol

_LOGGER = logging.getLogger(__name__)


class ConfigService(ConfigServiceProtocol):
    """Zentrale Konfigurationsverwaltung für SmartCity SensorBridge."""
    
    def __init__(self, hass: HomeAssistant) -> None:
        """Initialisiert den Config Service."""
        self.hass = hass
        self._config: Optional[Dict[str, Any]] = None
        self._config_path = Path(__file__).parent / CONFIG_FILE
        self._catalog: Optional[List[Dict[str, Any]]] = None
        self._catalog_error: Optional[DeviceCatalogError] = None
        self._entry_device_metadata: Dict[str, Dict[str, Any]] = {}
    
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
                required_keys = [
                    "mqtt_config",
                    "median_entities",
                    "sensor_categories",
                    "field_mapping",
                    "field_aliases",
                ]
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
    
    async def async_get_catalog(self, *, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Lädt den Gerätekatalog aus der öffentlichen API."""
        if self._catalog_error is not None and not force_refresh:
            raise self._catalog_error
        if self._catalog is None or force_refresh:
            client = DeviceCatalogClient(async_get_clientsession(self.hass))
            try:
                self._catalog = await client.async_get_devices()
                self._catalog_error = None
            except DeviceCatalogError as error:
                self._catalog_error = error
                raise
        return [dict(device) for device in self._catalog]

    async def get_devices(self) -> Dict[str, List[Dict[str, Any]]]:
        """Gibt den vollständigen API-Gerätekatalog gruppiert zurück."""
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for device in await self.async_get_catalog():
            grouped.setdefault(str(device["type"]), []).append(device)
        return grouped

    async def get_selection_candidates(
        self, existing_ids: Iterable[str] = ()
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Gibt neue Auswahlkandidaten und die bestehende Auswahl zurück."""
        existing = set(existing_ids)
        catalog = await self.async_get_catalog()
        candidates = filter_selection_candidates(catalog, existing)
        present_ids = {device["id"] for device in candidates}

        for device_id in existing - present_ids:
            fallback = self._entry_device_metadata.get(device_id)
            if fallback:
                candidates.append(dict(fallback))
            else:
                candidates.append(
                    {
                        "id": device_id,
                        "name": device_id,
                        "type": "Unknown",
                        "sensors": [],
                        "sensor_metadata": {},
                    }
                )

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for device in sorted(
            candidates, key=lambda item: (str(item.get("name", "")).casefold(), item["id"])
        ):
            grouped.setdefault(str(device.get("type", "Unknown")), []).append(device)
        return grouped

    def register_entry_data(self, entry_data: Dict[str, Any]) -> None:
        """Registriert den im Config Entry gespeicherten Gerätestand als Fallback."""
        metadata = entry_data.get("device_metadata", {})
        if not isinstance(metadata, dict):
            return
        for device_id, device in metadata.items():
            if isinstance(device_id, str) and isinstance(device, dict):
                self._entry_device_metadata[device_id] = dict(device)

    async def snapshot_devices(self, device_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        """Erstellt den im Config Entry zu speichernden Gerätestand."""
        selected_ids = list(dict.fromkeys(device_ids))
        snapshot: Dict[str, Dict[str, Any]] = {}
        for device_id in selected_ids:
            device = await self.get_device_by_id(device_id)
            if device:
                snapshot[device_id] = dict(device)
            elif device_id in self._entry_device_metadata:
                snapshot[device_id] = dict(self._entry_device_metadata[device_id])
            else:
                snapshot[device_id] = {
                    "id": device_id,
                    "name": device_id,
                    "type": "Unknown",
                    "sensors": [],
                    "sensor_metadata": {},
                }
        self._entry_device_metadata.update(snapshot)
        return snapshot
    
    async def get_median_entities(self) -> List[Dict[str, Any]]:
        """Gibt alle Median-Entities zurück."""
        config = await self.load_config()
        nested = config.get("median_entities", [])

        entities_with_type: List[Dict[str, Any]] = []
        median_ids: List[str] = []
        if isinstance(nested, list):
            for item in nested:
                if not isinstance(item, dict):
                    continue
                copy_item = dict(item)
                copy_item["type"] = "median"
                entities_with_type.append(copy_item)
                if "id" in copy_item:
                    median_ids.append(copy_item["id"])

        _LOGGER.debug("Median-Entities geladen: %s", median_ids)
        return entities_with_type
    
    async def get_sensor_categories(self) -> Dict[str, List[str]]:
        """Gibt die Sensor-Kategorien zurück."""
        config = await self.load_config()
        return config.get("sensor_categories", {})
    
    async def get_field_mapping(self) -> Dict[str, Any]:
        """Gibt das Field-Mapping zurück."""
        config = await self.load_config()
        return config.get("field_mapping", {})

    async def get_field_aliases(self) -> Dict[str, str]:
        """Gibt die lokale MQTT-zu-API-Feldzuordnung zurück."""
        config = await self.load_config()
        aliases = config.get("field_aliases", {})
        return aliases if isinstance(aliases, dict) else {}

    async def get_canonical_sensor_name(self, field_name: str) -> str:
        """Ordnet ein MQTT-Rohfeld dem kanonischen API-Feld zu."""
        return (await self.get_field_aliases()).get(field_name, field_name)

    async def get_legacy_sensor_names(self, sensor_name: str) -> List[str]:
        """Gibt bekannte frühere MQTT-Feldnamen für ein API-Feld zurück."""
        aliases = await self.get_field_aliases()
        return [raw for raw, canonical in aliases.items() if canonical == sensor_name]
    
    async def get_mqtt_config(self) -> Dict[str, Any]:
        """Gibt die MQTT-Konfiguration zurück."""
        config = await self.load_config()
        return config.get("mqtt_config", {})
    
    async def get_parsing_config(self) -> Dict[str, Any]:
        """Gibt die Parsing-Konfiguration zurück."""
        config = await self.load_config()
        return config.get("parsing", {})

    async def get_availability_config(self) -> Dict[str, Any]:
        """Gibt die Availability-Konfiguration zurück.

        Struktur (optional):
        {
          "default_stale_seconds": 3600,            # Sekunden (Kompatibilität)
          "default": "30m",                        # Menschlich (bevorzugt)
          "per_type": {"sensebox": "15m", "specialized": "1h", "median": "15m"},
          "per_device": {"<device_id>": "2h"}
        }
        """
        config = await self.load_config()
        availability = config.get("availability", {})
        if not isinstance(availability, dict):
            return {}

        def _parse_to_seconds(value: Any) -> Optional[int]:
            # Int/float: als Sekunden (Rückwärtskompatibilität)
            if isinstance(value, (int, float)):
                v = int(value)
                return v if v > 0 else None
            if isinstance(value, str):
                s = value.strip().lower()
                if not s:
                    return None
                # Unterstütze zusammengesetzte Angaben, z. B. "1h30m", "45m", "900s"
                total = 0
                for num, unit in re.findall(r"(\d+)\s*([smh])", s):
                    n = int(num)
                    if unit == "s":
                        total += n
                    elif unit == "m":
                        total += n * 60
                    elif unit == "h":
                        total += n * 3600
                # Falls keine Einheit, aber reine Zahl als String → als Minuten interpretieren
                if total == 0 and s.isdigit():
                    total = int(s) * 60
                return total or None
            return None

        normalized: Dict[str, Any] = {
            "default_stale_seconds": None,
            "per_type": {},
            "per_device": {},
        }

        # Default aus "default" (menschlich) oder "default_stale_seconds" (kompatibel)
        default_human = availability.get("default")
        default_seconds = availability.get("default_stale_seconds")
        parsed_default = _parse_to_seconds(default_human) if default_human is not None else _parse_to_seconds(default_seconds)
        if parsed_default:
            normalized["default_stale_seconds"] = max(60, parsed_default)

        # per_type
        per_type = availability.get("per_type", {}) or {}
        if isinstance(per_type, dict):
            for key, val in per_type.items():
                p = _parse_to_seconds(val)
                if p:
                    normalized["per_type"][str(key)] = max(60, p)

        # per_device
        per_device = availability.get("per_device", {}) or {}
        if isinstance(per_device, dict):
            for key, val in per_device.items():
                p = _parse_to_seconds(val)
                if p:
                    normalized["per_device"][str(key)] = max(60, p)

        return normalized
    
    async def validate_config(self) -> bool:
        """Validiert die Konfiguration."""
        try:
            config = await self.load_config()
            
            # Prüfe erforderliche Top-Level-Keys
            required_keys = [
                "mqtt_config",
                "median_entities",
                "sensor_categories",
                "field_mapping",
                "field_aliases",
            ]
            for key in required_keys:
                if key not in config:
                    _LOGGER.error("Erforderlicher Konfigurationsschlüssel fehlt: %s", key)
                    return False
            
            # Prüfe MQTT-Konfiguration
            mqtt_config = config["mqtt_config"]
            if "broker_url" not in mqtt_config or "topics" not in mqtt_config:
                _LOGGER.error("Ungültige MQTT-Konfiguration")
                return False
            
            if not isinstance(config["median_entities"], list):
                _LOGGER.error("Ungültige Median-Konfiguration")
                return False
            
            _LOGGER.debug("Konfiguration erfolgreich validiert")
            return True
            
        except Exception as e:
            _LOGGER.error("Fehler bei der Konfigurationsvalidierung: %s", e)
            return False
    
    async def get_device_by_id(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Gibt ein spezifisches Gerät nach ID zurück."""
        try:
            catalog = await self.async_get_catalog()
        except DeviceCatalogError:
            catalog = []

        for live_device in catalog:
            if live_device.get("id") != device_id:
                continue
            device = dict(live_device)
            stored = self._entry_device_metadata.get(device_id, {})
            live_sensors = device.get("sensors", [])
            stored_sensors = stored.get("sensors", [])
            if not live_sensors and isinstance(stored_sensors, list):
                device["sensors"] = list(stored_sensors)
                device["sensor_metadata"] = dict(stored.get("sensor_metadata", {}))
            return device

        stored = self._entry_device_metadata.get(device_id)
        if stored:
            return dict(stored)

        # 2) Median-Entities: device_id entspricht Location oder ID (Top-Level Only)
        for median in await self.get_median_entities():
            if median.get("id") == device_id or median.get("location") == device_id:
                return {
                    "id": device_id,
                    "name": median.get("name", device_id),
                    "type": "median",
                }

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
            # Nutze den TranslationHelper, um Übersetzungen zu laden
            from .translation_helper import TranslationHelper

            translation_helper = TranslationHelper(self.hass)
            sensor_names = await translation_helper.get_sensor_names()

            _LOGGER.debug("Sensor-Namen geladen: %s", sensor_names)
            return sensor_names

        except Exception as e:
            _LOGGER.warning(
                "Fehler beim Laden der Sensor-Namen-Übersetzungen: %s", e
            )
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
