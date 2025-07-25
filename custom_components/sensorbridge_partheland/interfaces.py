"""
Interface-Definitionen für SmartCity SensorBridge Partheland
HA 2025 Compliant mit Protocol-Klassen für Dependency Injection
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Protocol
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry


class ConfigServiceProtocol(Protocol):
    """Protocol für Config Service Interface."""
    
    async def load_config(self) -> Dict[str, Any]:
        """Lädt die Konfiguration asynchron."""
        ...
    
    async def get_devices(self) -> Dict[str, Any]:
        """Gibt alle verfügbaren Geräte zurück."""
        ...
    
    async def get_median_entities(self) -> List[Dict[str, Any]]:
        """Gibt alle Median-Entities zurück."""
        ...
    
    async def get_median_by_id(self, median_id: str) -> Optional[Dict[str, Any]]:
        """Gibt eine spezifische Median-Entity nach ID zurück."""
        ...
    
    async def validate_config(self) -> bool:
        """Validiert die Konfiguration."""
        ...
    
    async def get_sensor_names(self) -> Dict[str, str]:
        """Gibt die Sensor-Namen-Übersetzungen zurück."""
        ...
    
    async def get_device_categories(self) -> Dict[str, str]:
        """Gibt die Geräte-Kategorien-Übersetzungen zurück."""
        ...
    
    async def get_ui_text(self) -> Dict[str, str]:
        """Gibt die UI-Texte zurück."""
        ...
    
    async def get_error_messages(self) -> Dict[str, str]:
        """Gibt die Fehlermeldungen zurück."""
        ...


class MQTTServiceProtocol(Protocol):
    """Protocol für MQTT Service Interface."""
    
    async def connect(self) -> bool:
        """Verbindet zum MQTT-Broker."""
        ...
    
    async def disconnect(self) -> None:
        """Trennt die MQTT-Verbindung."""
        ...
    
    async def subscribe(self, topic: str, callback: Callable[[str, Any], None]) -> None:
        """Abonniert ein MQTT-Topic."""
        ...
    
    async def unsubscribe(self, topic: str) -> None:
        """Kündigt ein MQTT-Topic-Abonnement."""
        ...
    
    @property
    def is_connected(self) -> bool:
        """Gibt den Verbindungsstatus zurück."""
        ...


class ParserServiceProtocol(Protocol):
    """Protocol für Parser Service Interface."""
    
    async def parse_message(self, topic: str, payload: Any) -> Optional[Dict[str, Any]]:
        """Parst eine MQTT-Nachricht."""
        ...
    
    async def validate_message(self, topic: str, payload: Any) -> bool:
        """Validiert eine MQTT-Nachricht."""
        ...
    
    async def get_sensor_data(self, topic: str, payload: Any) -> Optional[Dict[str, Any]]:
        """Extrahiert Sensordaten aus einer Nachricht."""
        ...


class EntityFactoryProtocol(Protocol):
    """Protocol für Entity Factory Interface."""
    
    async def create_sensor_entity(
        self, 
        device_id: str, 
        sensor_name: str, 
        sensor_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Erstellt eine Sensor-Entity."""
        ...
    
    async def get_device_info(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Gibt Device-Informationen zurück."""
        ...
    
    async def get_sensor_attributes(self, sensor_name: str) -> Dict[str, Any]:
        """Gibt Sensor-Attribute zurück."""
        ...


class CoordinatorProtocol(Protocol):
    """Protocol für Coordinator Interface."""
    
    async def async_config_entry_first_refresh(self) -> None:
        """Erste Aktualisierung nach Config Entry."""
        ...
    
    async def async_shutdown(self) -> None:
        """Beendet den Coordinator."""
        ...
    
    async def update_sensor_data(self, device_id: str, sensor_data: Dict[str, Any]) -> None:
        """Aktualisiert Sensordaten."""
        ...
    
    @property
    def data(self) -> Dict[str, Any]:
        """Gibt die aktuellen Daten zurück."""
        ...


class ErrorHandlerProtocol(Protocol):
    """Protocol für Error Handler Interface."""
    
    async def handle_error(self, error: Exception, context: str) -> None:
        """Behandelt einen Fehler."""
        ...
    
    async def log_error(self, error: Exception, context: str) -> None:
        """Loggt einen Fehler."""
        ...
    
    async def get_user_friendly_message(self, error: Exception) -> str:
        """Gibt eine benutzerfreundliche Fehlermeldung zurück."""
        ...


# Type Aliases für bessere Lesbarkeit
DeviceConfig = Dict[str, Any]
SensorData = Dict[str, Any]
EntityConfig = Dict[str, Any]
MessagePayload = Any
Topic = str
DeviceID = str
SensorName = str 