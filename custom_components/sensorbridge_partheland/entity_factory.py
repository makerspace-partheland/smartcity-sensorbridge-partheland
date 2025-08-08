"""
Entity Factory für SmartCity SensorBridge Partheland
HA 2025 Compliant - Reine Entity-Erstellung
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.util import slugify

from .interfaces import EntityFactoryProtocol, ConfigServiceProtocol

_LOGGER = logging.getLogger(__name__)


class EntityFactory(EntityFactoryProtocol):
    """HA 2025 Entity Factory für reine Entity-Erstellung."""
    
    def __init__(self, hass: HomeAssistant, config_service: ConfigServiceProtocol) -> None:
        """Initialisiert die Entity Factory."""
        self.hass = hass
        self.config_service = config_service
        self._field_mapping: Optional[Dict[str, Any]] = None
        self._sensor_names: Optional[Dict[str, str]] = None
        self._sensor_categories: Optional[Dict[str, List[str]]] = None
    
    async def create_sensor_entity(
        self, 
        device_id: str, 
        sensor_name: str, 
        sensor_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Erstellt eine Sensor-Entity."""
        try:
            # Device-Info laden
            device_info = await self.get_device_info(device_id)
            if not device_info:
                _LOGGER.warning("Keine Device-Info für %s gefunden", device_id)
                return None
            
            # Sensor-Attribute laden
            sensor_attributes = await self.get_sensor_attributes(sensor_name)
            
            # Entity-ID generieren
            entity_id = self._generate_entity_id(device_id, sensor_name)
            
            # Entity-Konfiguration erstellen
            entity_config = {
                "entity_id": entity_id,
                "name": sensor_attributes.get("name", sensor_name),
                "device_id": device_id,
                "device_name": device_info.get("name", device_id),
                "device_class": sensor_attributes.get("device_class"),
                "unit_of_measurement": sensor_attributes.get("unit_of_measurement"),
                "icon": sensor_attributes.get("icon"),
                "value": sensor_data.get(sensor_name),
                "attributes": {
                    "device_id": device_id,
                    "device_name": device_info.get("name", device_id),
                    "sensor_type": sensor_name,
                    "last_update": sensor_data.get("timestamp"),
                }
            }
            
            _LOGGER.debug("Entity erstellt: %s", entity_id)
            return entity_config
            
        except Exception as e:
            _LOGGER.error("Fehler beim Erstellen der Entity: %s", e)
            return None
    
    async def get_device_info(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Gibt Device-Informationen zurück."""
        try:
            return await self.config_service.get_device_by_id(device_id)
        except Exception as e:
            _LOGGER.error("Fehler beim Laden der Device-Info für %s: %s", device_id, e)
            return None
    
    async def get_sensor_attributes(self, sensor_name: str) -> Dict[str, Any]:
        """Gibt Sensor-Attribute zurück."""
        try:
            # Field-Mapping laden
            if not self._field_mapping:
                self._field_mapping = await self.config_service.get_field_mapping()
            
            # Sensor-Namen laden
            if not self._sensor_names:
                self._sensor_names = await self.config_service.get_sensor_names()
            
            # Sensor-Kategorien laden
            if not self._sensor_categories:
                self._sensor_categories = await self.config_service.get_sensor_categories()
            
            # Unit und Device-Class bestimmen
            units = self._field_mapping.get("units", {})
            device_classes = self._field_mapping.get("device_classes", {})
            
            # Übersetzten Namen
            translated_name = self._sensor_names.get(sensor_name, sensor_name)
            
            # Device-Class bestimmen
            device_class = device_classes.get(sensor_name)
            
            # Unit bestimmen
            unit = units.get(sensor_name)
            
            # Icon bestimmen basierend auf Sensor-Kategorie
            icon = await self._get_sensor_icon(sensor_name, device_class)
            
            return {
                "name": translated_name,
                "device_class": device_class,
                "unit_of_measurement": unit,
                "icon": icon
            }
            
        except Exception as e:
            _LOGGER.error("Fehler beim Laden der Sensor-Attribute: %s", e)
            return {
                "name": sensor_name,
                "device_class": None,
                "unit_of_measurement": None,
                "icon": "mdi:sensor"
            }
    
    def _generate_entity_id(self, device_id: str, sensor_name: str) -> str:
        """Generiert eine Entity-ID."""
        clean_device_id = slugify(device_id)
        clean_sensor_name = slugify(sensor_name)

        return f"sensor.{clean_device_id}_{clean_sensor_name}"
    
    async def _get_sensor_icon(self, sensor_name: str, device_class: Optional[str]) -> str:
        """Bestimmt das Icon für einen Sensor basierend auf Konfiguration."""
        try:
            # Icon-Mapping aus Konfiguration laden
            icons = await self.config_service.get_icons()
            
            # Sensor-Kategorien laden
            if not self._sensor_categories:
                self._sensor_categories = await self.config_service.get_sensor_categories()
            
            # Sensor-Kategorie bestimmen
            sensor_category = self._get_sensor_category(sensor_name)
            
            # Icon basierend auf Device-Class (höchste Priorität)
            if device_class and device_class in icons:
                return icons[device_class]
            
            # Icon basierend auf Sensor-Kategorie
            if sensor_category in icons:
                return icons[sensor_category]
            
            # Default-Icon aus Konfiguration
            return icons.get("default", "mdi:sensor")
            
        except Exception as e:
            _LOGGER.error("Fehler bei der Icon-Bestimmung: %s", e)
            return "mdi:sensor"
    
    def _get_sensor_category(self, sensor_name: str) -> str:
        """Bestimmt die Sensor-Kategorie basierend auf dem Sensor-Namen."""
        if not self._sensor_categories:
            return "unknown"
        
        for category, sensors in self._sensor_categories.items():
            if sensor_name in sensors:
                return category
        
        return "unknown"
    
    async def create_entities_for_device(self, device_id: str, sensor_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Erstellt Entities für alle Sensoren eines Geräts."""
        entities = []
        
        try:
            for sensor_name, sensor_value in sensor_data.items():
                if isinstance(sensor_value, (int, float)):
                    entity_config = await self.create_sensor_entity(device_id, sensor_name, sensor_data)
                    if entity_config:
                        entities.append(entity_config)
            
            _LOGGER.debug("Erstellt %d Entities für Gerät %s", len(entities), device_id)
            return entities
            
        except Exception as e:
            _LOGGER.error("Fehler beim Erstellen der Entities für Gerät %s: %s", device_id, e)
            return []
    
    async def get_entity_unique_id(self, device_id: str, sensor_name: str) -> str:
        """Generiert eine eindeutige Entity-ID."""
        return f"{device_id}_{sensor_name}"
    
    async def validate_entity_config(self, entity_config: Dict[str, Any]) -> bool:
        """Validiert eine Entity-Konfiguration."""
        required_fields = ["entity_id", "name", "device_id"]
        
        for field in required_fields:
            if field not in entity_config:
                _LOGGER.error("Erforderliches Feld fehlt in Entity-Konfiguration: %s", field)
                return False
        
        return True 