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
            median_detection = self._parsing_config.get("sensebox", {}).get("median_detection", {})
            is_median = self._is_median_topic(topic, median_detection)
            
            # Fields-Pfad bestimmen - für Median-Topics direkt im Root-Level
            if is_median:
                fields = data  # Median-Topics haben keine fields-Struktur
            else:
                fields_path = self._parsing_config.get("sensebox", {}).get("data_path", "fields")
                fields = data.get(fields_path, {})
            
            if not fields:
                _LOGGER.debug("Keine Fields in senseBox-Nachricht gefunden")
                return None
            
            # Konfigurierte Sensoren für dieses Gerät laden
            configured_sensors = await self._get_configured_sensors_for_device(device_id, is_median)
            if not configured_sensors:
                return None
            
            # Sensordaten extrahieren - nur konfigurierte Sensoren
            sensor_data = {}
            for field_name, field_value in fields.items():
                if isinstance(field_value, (int, float)) and field_name in configured_sensors:
                    # Median-Suffix hinzufügen
                    if is_median:
                        field_name = f"{field_name}_{median_detection.get('suffix', '_median')}"
                    
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
    
    async def _get_configured_sensors_for_device(self, device_id: str, is_median: bool) -> Optional[list[str]]:
        """Lädt die konfigurierten Sensoren für ein Gerät."""
        try:
            # Konfiguration laden
            config = await self.config_service.load_config()
            
            if is_median:
                # Für Median-Entities
                median_entities = config.get("MedianEntities", [])
                for median_entity in median_entities:
                    if median_entity.get("id") == device_id:
                        return median_entity.get("sensors", [])
            else:
                # Für normale Geräte
                known_devices = config.get("known_devices", {})
                sensebox_devices = known_devices.get("senseBox", [])
                
                for device in sensebox_devices:
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
            
            # Fields-Pfad bestimmen
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
            configured_sensors = await self._get_configured_sensors_for_device(device_id, False)
            if not configured_sensors:
                return None
            
            # Sensordaten extrahieren - nur konfigurierte Sensoren
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
        # senseBox:home/DeviceID -> DeviceID
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
    
    def _is_rssi_only_message(self, fields: Dict[str, Any]) -> bool:
        """Prüft ob es sich um eine RSSI-Only-Nachricht handelt."""
        # Nur RSSI-Felder vorhanden
        rssi_fields = [k for k in fields.keys() if 'rssi' in k.lower()]
        non_rssi_fields = [k for k in fields.keys() if 'rssi' not in k.lower()]
        
        return len(rssi_fields) > 0 and len(non_rssi_fields) == 0 