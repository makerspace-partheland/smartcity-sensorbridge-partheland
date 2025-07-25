"""
Coordinator für SmartCity SensorBridge Partheland
HA 2025 Compliant - Reine Orchestrierung
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.debounce import Debouncer

from .const import DEFAULT_SCAN_INTERVAL, EVENT_SENSOR_DATA_RECEIVED
from .interfaces import (
    CoordinatorProtocol, ConfigServiceProtocol, MQTTServiceProtocol,
    ParserServiceProtocol, EntityFactoryProtocol, ErrorHandlerProtocol
)

_LOGGER = logging.getLogger(__name__)


class SensorBridgeCoordinator(DataUpdateCoordinator, CoordinatorProtocol):
    """HA 2025 DataUpdateCoordinator für MQTT Push-basierte Datenverarbeitung."""
    
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        config_service: ConfigServiceProtocol,
        mqtt_service: MQTTServiceProtocol,
        parser_service: ParserServiceProtocol,
        entity_factory: EntityFactoryProtocol,
        error_handler: ErrorHandlerProtocol
    ) -> None:
        """Initialisiert den Coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="SensorBridge Coordinator",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),  # Health Check Intervall
            request_refresh_debouncer=Debouncer(
                hass, _LOGGER, cooldown=1, immediate=True
            ),
            config_entry=entry  # HA 2025+ Compliance: Config Entry explizit übergeben
        )
        
        self.entry = entry
        self.config_service = config_service
        self.mqtt_service = mqtt_service
        self.parser_service = parser_service
        self.entity_factory = entity_factory
        self.error_handler = error_handler
        
        # Konfiguration
        self.selected_devices: List[str] = entry.data.get("selected_devices", [])
        self.selected_median_entities: List[str] = entry.data.get("selected_median_entities", [])
        
        # Daten-Storage
        self._sensor_data: Dict[str, Dict[str, Any]] = {}
        self._entities: Dict[str, Dict[str, Any]] = {}
        self._mqtt_topics: List[str] = []
        
        _LOGGER.debug("Coordinator initialisiert für %d Geräte", len(self.selected_devices))
    
    async def async_config_entry_first_refresh(self) -> None:
        """Erste Aktualisierung nach Config Entry."""
        try:
            _LOGGER.debug("Starte erste Coordinator-Aktualisierung")
            
            # MQTT-Topics bestimmen
            await self._setup_mqtt_topics()
            
            # MQTT-Verbindung herstellen
            if not await self.mqtt_service.connect():
                raise UpdateFailed("MQTT-Verbindung fehlgeschlagen")
            
            # MQTT-Topics abonnieren
            await self._subscribe_to_topics()
            
            # Erste Daten-Aktualisierung
            await self.async_request_refresh()
            
            _LOGGER.info("Coordinator erfolgreich gestartet")
            
        except Exception as e:
            await self.error_handler.handle_error(e, "Coordinator First Refresh")
            raise UpdateFailed(f"Coordinator-Start fehlgeschlagen: {e}")
    
    async def async_shutdown(self) -> None:
        """Beendet den Coordinator."""
        try:
            _LOGGER.debug("Beende Coordinator")
            
            # MQTT-Topics kündigen
            await self._unsubscribe_from_topics()
            
            # MQTT-Verbindung trennen
            await self.mqtt_service.disconnect()
            
            _LOGGER.info("Coordinator erfolgreich beendet")
            
        except Exception as e:
            await self.error_handler.handle_error(e, "Coordinator Shutdown")
    
    async def update_sensor_data(self, device_id: str, sensor_data: Dict[str, Any]) -> None:
        """Aktualisiert Sensordaten."""
        try:
            _LOGGER.debug("Aktualisiere Sensordaten für Gerät %s", device_id)
            
            # Daten speichern
            self._sensor_data[device_id] = sensor_data
            
            # Entities erstellen/aktualisieren
            entities = await self.entity_factory.create_entities_for_device(device_id, sensor_data)
            for entity in entities:
                entity_id = entity["entity_id"]
                self._entities[entity_id] = entity
            
            # Event auslösen (ohne DeviceEntry-Objekte)
            event_data = {
                "device_id": device_id,
                "sensor_data": sensor_data,
                "entity_count": len(entities)
            }
            
            # DeviceEntry-Objekte aus Event-Daten entfernen
            sanitized_event_data = self._sanitize_event_data(event_data)
            
            self.hass.bus.async_fire(
                EVENT_SENSOR_DATA_RECEIVED,
                sanitized_event_data
            )
            
            # Coordinator-Daten aktualisieren
            self.async_set_updated_data(self._sensor_data)
            
        except Exception as e:
            await self.error_handler.handle_error(e, f"Update Sensor Data for {device_id}")
    
    def _sanitize_event_data(self, data: Any) -> Any:
        """Entfernt nicht-serialisierbare Objekte aus Event-Daten."""
        if isinstance(data, dict):
            sanitized = {}
            for key, value in data.items():
                # DeviceEntry-Objekte überspringen
                if hasattr(value, '__class__') and 'DeviceEntry' in str(value.__class__):
                    sanitized[key] = f"DeviceEntry({key})"
                else:
                    sanitized[key] = self._sanitize_event_data(value)
            return sanitized
        elif isinstance(data, list):
            return [self._sanitize_event_data(item) for item in data]
        else:
            return data
    
    @property
    def data(self) -> Dict[str, Any]:
        """Gibt die aktuellen Daten zurück."""
        return self._sensor_data
    
    @data.setter
    def data(self, value: Dict[str, Any]) -> None:
        """Setter für die Daten (wird von DataUpdateCoordinator verwendet)."""
        self._sensor_data = value
    
    async def _async_update_data(self) -> Dict[str, Any]:
        """Health Check und Fallback-Mechanismus (MQTT-Daten kommen Push-basiert)."""
        try:
            _LOGGER.debug("Führe Health Check durch")
            
            # Prüfe MQTT-Verbindungsstatus
            if not self.mqtt_service.is_connected:
                _LOGGER.warning("MQTT-Verbindung verloren, versuche Reconnect")
                await self.mqtt_service.connect()
            
            # Aktuelle Sensordaten zurückgeben (werden über MQTT-Callbacks aktualisiert)
            return self._sensor_data.copy()
            
        except Exception as e:
            await self.error_handler.handle_error(e, "Health Check")
            return self._sensor_data.copy()
    
    async def _setup_mqtt_topics(self) -> None:
        """Richtet MQTT-Topics ein."""
        try:
            _LOGGER.debug("Richte MQTT-Topics ein")
            
            # MQTT-Konfiguration laden
            mqtt_config = await self.config_service.get_mqtt_config()
            topics_config = mqtt_config.get("topics", {})
            
            # Topics für ausgewählte Geräte
            for device_id in self.selected_devices:
                device_info = await self.config_service.get_device_by_id(device_id)
                if device_info:
                    device_type = device_info.get("type", "unknown")
                    
                    # Topic-Pattern aus der Geräte-Konfiguration verwenden
                    topic_pattern = device_info.get("topic_pattern")
                    if topic_pattern:
                        # Topic-Pattern enthält bereits die Device-ID
                        topic = topic_pattern
                        self._mqtt_topics.append(topic)
                        _LOGGER.debug("Topic für %s: %s", device_id, topic)
                    else:
                        _LOGGER.warning("Kein topic_pattern für Gerät %s gefunden", device_id)
            
            # Topics für Median-Entities
            for entity_id in self.selected_median_entities:
                # Median-Entity Info laden
                median_entities = await self.config_service.get_median_entities()
                median_info = next((entity for entity in median_entities if entity["id"] == entity_id), None)
                
                if median_info:
                    topic_pattern = median_info.get("topic_pattern")
                    if topic_pattern:
                        # Topic-Pattern enthält bereits die Entity-ID
                        topic = topic_pattern
                        self._mqtt_topics.append(topic)
                        _LOGGER.debug("Median Topic für %s: %s", entity_id, topic)
                    else:
                        _LOGGER.warning("Kein topic_pattern für Median-Entity %s gefunden", entity_id)
                else:
                    _LOGGER.warning("Median-Entity %s nicht in der Konfiguration gefunden", entity_id)
            
            _LOGGER.debug("MQTT-Topics eingerichtet: %s", self._mqtt_topics)
            
        except Exception as e:
            await self.error_handler.handle_error(e, "Setup MQTT Topics")
            raise
    
    async def _subscribe_to_topics(self) -> None:
        """Abonniert MQTT-Topics."""
        try:
            _LOGGER.debug("Abonniere MQTT-Topics")
            
            for topic in self._mqtt_topics:
                _LOGGER.debug("Abonniere Topic: %s", topic)
                # Synchrone Wrapper-Funktion für asynchronen Handler
                await self.mqtt_service.subscribe(topic, self._mqtt_message_wrapper)
            
            _LOGGER.info("MQTT-Topics abonniert: %d Topics", len(self._mqtt_topics))
            
        except Exception as e:
            await self.error_handler.handle_error(e, "Subscribe to Topics")
            raise
    
    def _mqtt_message_wrapper(self, topic: str, payload: Any) -> None:
        """Synchrone Wrapper-Funktion für MQTT-Nachrichten."""
        try:
            # Asynchronen Handler über Event Loop aufrufen
            self.hass.async_create_task(self._handle_mqtt_message(topic, payload))
        except Exception as e:
            _LOGGER.error("Fehler beim Aufrufen des MQTT-Handlers für Topic %s: %s", topic, e)
    
    async def _unsubscribe_from_topics(self) -> None:
        """Kündigt MQTT-Topics."""
        try:
            _LOGGER.debug("Kündige MQTT-Topics")
            
            for topic in self._mqtt_topics:
                await self.mqtt_service.unsubscribe(topic)
            
            self._mqtt_topics.clear()
            _LOGGER.debug("MQTT-Topics gekündigt")
            
        except Exception as e:
            await self.error_handler.handle_error(e, "Unsubscribe from Topics")
    
    async def _handle_mqtt_message(self, topic: str, payload: Any) -> None:
        """Behandelt MQTT-Nachrichten."""
        try:
            _LOGGER.debug("Behandle MQTT-Nachricht: %s", topic)
            
            # Message parsen
            parsed_data = await self.parser_service.parse_message(topic, payload)
            if not parsed_data:
                _LOGGER.warning("Konnte MQTT-Nachricht nicht parsen: %s", topic)
                return
            
            _LOGGER.debug("MQTT-Nachricht erfolgreich geparst: %s", parsed_data)
            
            # Sensordaten aktualisieren
            device_id = parsed_data["device_id"]
            sensor_data = parsed_data["sensor_data"]
            
            await self.update_sensor_data(device_id, sensor_data)
            
        except Exception as e:
            await self.error_handler.handle_error(e, f"Handle MQTT Message: {topic}")
    
    async def get_entities(self) -> Dict[str, Dict[str, Any]]:
        """Gibt alle Entities zurück."""
        return self._entities
    
    async def get_device_entities(self, device_id: str) -> List[Dict[str, Any]]:
        """Gibt Entities für ein spezifisches Gerät zurück."""
        device_entities = []
        
        for entity_id, entity_data in self._entities.items():
            if entity_data.get("device_id") == device_id:
                device_entities.append(entity_data)
        
        return device_entities 