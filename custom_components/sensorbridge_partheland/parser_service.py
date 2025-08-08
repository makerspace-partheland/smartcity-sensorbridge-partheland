"""
Parser Service für SmartCity SensorBridge Partheland
HA 2025 Compliant - Reines Message Parsing
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant

from .interfaces import ParserServiceProtocol, ConfigServiceProtocol

_LOGGER = logging.getLogger(__name__)


class ParserService(ParserServiceProtocol):
    """HA 2025 Parser Service für reines Message Parsing."""
    
    def __init__(self, hass: HomeAssistant, config_service: ConfigServiceProtocol) -> None:
        """Initialisiert den Parser Service."""
        self.hass = hass
        self.config_service = config_service
        self._parsing_config: Optional[Dict[str, Any]] = None
        self._field_mapping: Optional[Dict[str, Any]] = None
    
    async def parse_message(self, topic: str, payload: Any) -> Optional[Dict[str, Any]]:
        """Parst eine MQTT-Nachricht."""
        try:
            # Message validieren
            if not await self.validate_message(topic, payload):
                return None
            
            # Sensordaten extrahieren
            sensor_data = await self.get_sensor_data(topic, payload)
            if not sensor_data:
                return None
            
            _LOGGER.debug("Message erfolgreich geparst: %s", topic)
            return sensor_data
            
        except Exception as e:
            _LOGGER.error("Fehler beim Parsen der Message %s: %s", topic, e)
            return None
    
    async def validate_message(self, topic: str, payload: Any) -> bool:
        """Validiert eine MQTT-Nachricht."""
        try:
            # Payload validieren
            if not payload:
                _LOGGER.debug("Leere Payload für Topic %s", topic)
                return False
            
            # Payload-Typ konvertieren
            if isinstance(payload, bytes):
                try:
                    payload_str = payload.decode('utf-8')
                except UnicodeDecodeError:
                    _LOGGER.debug("Ungültige UTF-8 Payload für Topic %s", topic)
                    return False
            elif isinstance(payload, str):
                payload_str = payload
            else:
                _LOGGER.debug("Ungültiger Payload-Typ für Topic %s: %s", topic, type(payload))
                return False
            
            # JSON validieren
            try:
                json.loads(payload_str)
            except json.JSONDecodeError:
                _LOGGER.debug("Ungültiges JSON für Topic %s", topic)
                return False
            
            # Topic-Pattern validieren
            if not self._is_valid_topic(topic):
                _LOGGER.debug("Ungültiges Topic-Pattern: %s", topic)
                return False
            
            return True
            
        except Exception as e:
            _LOGGER.error("Fehler bei der Message-Validierung: %s", e)
            return False
    
    async def get_sensor_data(self, topic: str, payload: Any) -> Optional[Dict[str, Any]]:
        """Extrahiert Sensordaten aus einer Nachricht."""
        try:
            # Payload-Typ konvertieren (wie in validate_message)
            if isinstance(payload, bytes):
                try:
                    payload_str = payload.decode('utf-8')
                except UnicodeDecodeError:
                    _LOGGER.error("Ungültige UTF-8 Payload für Topic %s", topic)
                    return None
            elif isinstance(payload, str):
                payload_str = payload
            else:
                _LOGGER.error("Ungültiger Payload-Typ für Topic %s: %s", topic, type(payload))
                return None
            
            # Payload parsen
            data = json.loads(payload_str)
            
            # Parsing-Konfiguration laden
            if not self._parsing_config:
                self._parsing_config = await self.config_service.get_parsing_config()
            
            # Topic-Typ bestimmen
            topic_type = self._get_topic_type(topic)
            
            # Je nach Topic-Typ parsen
            if topic_type == "sensebox":
                return await self._parse_sensebox_message(topic, data)
            elif topic_type == "specialized_sensors":
                return await self._parse_specialized_message(topic, data)
            else:
                _LOGGER.debug("Unbekannter Topic-Typ: %s", topic_type)
                return None
            
        except Exception as e:
            _LOGGER.error("Fehler beim Extrahieren der Sensordaten: %s", e)
            return None
    
    async def _parse_sensebox_message(self, topic: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parst senseBox-Nachrichten."""
        try:
            # Device-ID aus Topic extrahieren
            device_id = self._extract_device_id_from_topic(topic)
            if not device_id:
                return None

            # Median-Erkennung
            median_detection = self._parsing_config.get("sensebox", {}).get(
                "median_detection", {}
            )
            is_median = self._is_median_topic(topic, median_detection)

            # Bei Median-Topics wird als "device_id" der Standortname extrahiert
            # (z. B. senseBox:home/median/Naunhof -> "Naunhof"). Für die
            # interne Zuordnung und Entity-Matches mappen wir auf die
            # konfigurierte Median-ID (z. B. "median_Naunhof"), sofern vorhanden.
            if is_median:
                device_id = await self._map_median_location_to_id(device_id)

            # Fields-Pfad bestimmen - für Median-Topics direkt im Root-Level
            if is_median:
                fields = data  # Median-Topics haben keine fields-Struktur
            else:
                fields_path = self._parsing_config.get("sensebox", {}).get(
                    "data_path", "fields"
                )
                fields = data.get(fields_path, {})
            
            if not fields:
                _LOGGER.debug("Keine Fields in senseBox-Nachricht gefunden")
                return None
            
            # Konfigurierte Sensoren für dieses Gerät laden
            configured_sensors = await self._get_configured_sensors_for_device(
                device_id, is_median, device_type="sensebox"
            )
            if not configured_sensors:
                return None
            
            # Sensordaten extrahieren - nur konfigurierte Sensoren
            sensor_data = {}
            for field_name, field_value in fields.items():
                if isinstance(field_value, (int, float)) and field_name in configured_sensors:
                    # Für Median-Topics KEIN Suffix anhängen. Die Entities
                    # werden für die gleichen Feldnamen erzeugt wie bei
                    # Einzelgeräten, nur unter der Median-Geräte-ID.
                    sensor_data[field_name] = field_value
            
            if not sensor_data:
                return None
            
            return {
                "device_id": device_id,
                "device_type": "sensebox",
                "topic": topic,
                "sensor_data": sensor_data,
                "is_median": is_median
            }
            
        except Exception as e:
            _LOGGER.error("Fehler beim Parsen der senseBox-Nachricht: %s", e)
            return None
    
    async def _get_configured_sensors_for_device(self, device_id: str, is_median: bool, device_type: Optional[str] = None) -> Optional[list[str]]:
        """Lädt die konfigurierten Sensoren für ein Gerät.

        device_id: Bei normalen Topics ist das die Geräte-ID aus dem Topic.
                   Bei Median-Topics ist das der Standort-Name (z. B. "Brandis").

        device_type: Erwartete Werte "sensebox" oder "specialized"; None für auto.
        """
        try:
            # Konfiguration laden
            config = await self.config_service.load_config()

            if is_median:
                # Median-Entities über den ConfigService beziehen (HA 2025 konforme Struktur)
                median_entities = await self.config_service.get_median_entities()

                # Unterstütze sowohl Standortnamen (z. B. "Naunhof") als auch
                # Median-IDs (z. B. "median_Naunhof").
                for median_entity in median_entities:
                    if not isinstance(median_entity, dict):
                        continue
                    location = median_entity.get("location")
                    topic_pattern = median_entity.get("topic_pattern", "")
                    median_id = median_entity.get("id")

                    # Direkter ID-Match
                    if median_id == device_id:
                        return median_entity.get("sensors", [])

                    # Match nach Location (senseBox:home/median/<Location>)
                    if location == device_id:
                        return median_entity.get("sensors", [])

                    # Wenn device_id wie "median_<Location>" aussieht, Location extrahieren
                    if isinstance(device_id, str) and device_id.startswith("median_"):
                        loc_from_id = device_id[len("median_"):]
                        if location == loc_from_id:
                            return median_entity.get("sensors", [])

                    # Fallback: Ende des Topic-Patterns muss mit /<device_id> übereinstimmen
                    if topic_pattern.endswith(f"/{device_id}"):
                        return median_entity.get("sensors", [])

                return None

            # Nicht-Median: in known_devices nach der ID suchen
            known_devices: Dict[str, list] = config.get("known_devices", {})

            # Wenn Typ explizit ist, zunächst passend filtern
            if device_type == "sensebox":
                candidates = known_devices.get("senseBox", [])
                for device in candidates:
                    if device.get("id") == device_id:
                        return device.get("sensors", [])
                return None

            if device_type == "specialized":
                # In allen Nicht-senseBox-Kategorien suchen (z. B. Temperature, WaterLevel)
                for category_name, devices in known_devices.items():
                    if category_name == "senseBox":
                        continue
                    for device in devices:
                        if device.get("id") == device_id:
                            return device.get("sensors", [])
                return None

            # Auto-Detect: erst senseBox, dann alle anderen Kategorien
            for device in known_devices.get("senseBox", []):
                if device.get("id") == device_id:
                    return device.get("sensors", [])

            for category_name, devices in known_devices.items():
                if category_name == "senseBox":
                    continue
                for device in devices:
                    if device.get("id") == device_id:
                        return device.get("sensors", [])

            return None

        except Exception as e:
            _LOGGER.error("Fehler beim Laden der konfigurierten Sensoren für Gerät %s: %s", device_id, e)
            return None
    
    async def _parse_specialized_message(self, topic: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parst spezialisierte Sensor-Nachrichten."""
        try:
            # Device-ID aus Topic extrahieren
            device_id = self._extract_device_id_from_topic(topic)
            if not device_id:
                return None
            
            # Fields-Pfad bestimmen – ausschließlich "fields" (bzw. konfigurierbarer Pfad)
            fields_path = self._parsing_config.get("specialized_sensors", {}).get("data_path", "fields")
            fields = data.get(fields_path, {})
            
            if not fields:
                _LOGGER.debug("Keine Fields in spezialisierter Nachricht gefunden")
                return None
            
            # RSSI-Only-Filter
            ignore_rssi_only = self._parsing_config.get("specialized_sensors", {}).get("ignore_rssi_only", True)
            if ignore_rssi_only and self._is_rssi_only_message(fields):
                _LOGGER.debug("RSSI-Only-Nachricht ignoriert")
                return None
            
            # Konfigurierte Sensoren für dieses Gerät laden
            configured_sensors = await self._get_configured_sensors_for_device(
                device_id, False, device_type="specialized"
            )
            if not configured_sensors:
                return None
            
            # Sensordaten extrahieren – strikt nach Konfiguration
            sensor_data = {}
            for field_name, field_value in fields.items():
                if isinstance(field_value, (int, float)) and field_name in configured_sensors:
                    sensor_data[field_name] = field_value
            
            if not sensor_data:
                return None
            
            return {
                "device_id": device_id,
                "device_type": "specialized",
                "topic": topic,
                "sensor_data": sensor_data,
                "is_median": False
            }
            
        except Exception as e:
            _LOGGER.error("Fehler beim Parsen der spezialisierten Nachricht: %s", e)
            return None
    
    def _is_valid_topic(self, topic: str) -> bool:
        """Prüft ob das Topic einem gültigen Pattern entspricht."""
        valid_patterns = [
            r"^senseBox:home/[^/]+$",  # senseBox:home/DeviceID
            r"^senseBox:home/median/[^/]+$",  # senseBox:home/median/Location
            r"^sensoren/[^/]+$",  # sensoren/DeviceID
        ]
        
        for pattern in valid_patterns:
            if re.match(pattern, topic):
                return True
        
        return False
    
    def _get_topic_type(self, topic: str) -> str:
        """Bestimmt den Topic-Typ."""
        if topic.startswith("senseBox:home"):
            return "sensebox"
        elif topic.startswith("sensoren"):
            return "specialized_sensors"
        else:
            return "unknown"
    
    def _extract_device_id_from_topic(self, topic: str) -> Optional[str]:
        """Extrahiert die Device-ID aus dem Topic."""
        # senseBox:home/DeviceID bzw. senseBox:home/median/Location
        if topic.startswith("senseBox:home/"):
            return topic.split("/")[-1]
        
        # sensoren/DeviceID -> DeviceID
        elif topic.startswith("sensoren/"):
            return topic.split("/")[-1]
        
        return None
    
    def _is_median_topic(self, topic: str, median_detection: Dict[str, Any]) -> bool:
        """Prüft ob es sich um ein Median-Topic handelt."""
        topic_pattern = median_detection.get("topic_pattern", "senseBox:home/median")
        return topic.startswith(topic_pattern)

    async def _map_median_location_to_id(self, location_or_id: str) -> str:
        """Mappt einen Median-Standortnamen auf die konfigurierte Median-ID.

        Falls bereits eine Median-ID übergeben wurde oder keine Konfiguration
        gefunden wird, wird der Eingabewert zurückgegeben.
        """
        try:
            median_entities = await self.config_service.get_median_entities()

            for entity in median_entities:
                if not isinstance(entity, dict):
                    continue
                if entity.get("id") == location_or_id or entity.get("location") == location_or_id:
                    return entity.get("id", location_or_id)
        except Exception:
            pass
        return location_or_id
    
    def _is_rssi_only_message(self, fields: Dict[str, Any]) -> bool:
        """Prüft ob es sich um eine RSSI-Only-Nachricht handelt."""
        # Nur RSSI-Felder vorhanden
        rssi_fields = [k for k in fields.keys() if 'rssi' in k.lower()]
        non_rssi_fields = [k for k in fields.keys() if 'rssi' not in k.lower()]
        
        return len(rssi_fields) > 0 and len(non_rssi_fields) == 0 