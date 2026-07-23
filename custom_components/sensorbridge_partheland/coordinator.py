"""
Coordinator für SmartCity SensorBridge Partheland
HA 2025 Compliant - Reine Orchestrierung
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any, Dict, List, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_SCAN_INTERVAL,
    EVENT_MQTT_CONNECTED,
    EVENT_MQTT_DISCONNECTED,
    EVENT_SENSOR_DATA_RECEIVED,
)
from .interfaces import (
    ConfigServiceProtocol,
    CoordinatorProtocol,
    EntityFactoryProtocol,
    ErrorHandlerProtocol,
    MQTTServiceProtocol,
    ParserServiceProtocol,
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
        self._device_last_seen: Dict[str, float] = {}
        self._stale_after_seconds: int = 300
        self._default_stale_seconds: int = 300
        self._per_type_stale: Dict[str, int] = {}
        self._per_device_stale: Dict[str, int] = {}
        self._mqtt_unsubs: List[Any] = []
        self._ha_entity_ids_by_device: Dict[str, set[str]] = {}
        self._base_shutdown_complete = False
        self._mqtt_disconnect_complete = False
        
        _LOGGER.debug("Coordinator initialisiert für %d Geräte", len(self.selected_devices))
    
    async def async_start(self) -> None:
        """Startet den Coordinator, auch wenn MQTT zunächst nicht erreichbar ist."""
        try:
            _LOGGER.debug("Starte Coordinator")
            
            # MQTT-Topics bestimmen
            await self._setup_mqtt_topics()

            # Gewünschte Topics vor dem Verbindungsversuch registrieren, damit
            # ein späterer Connect sie ohne Config-Entry-Reload abonnieren kann.
            await self._subscribe_to_topics()
            
            # Stale-Threshold anhand Keepalive konfigurieren (mind. 300s)
            try:
                mqtt_conf = await self.config_service.get_mqtt_config()
                keepalive = int(mqtt_conf.get("keepalive", 60))
                base_keepalive = max(keepalive * 4, 300)
                self._default_stale_seconds = base_keepalive
                self._stale_after_seconds = base_keepalive
            except Exception:
                self._stale_after_seconds = 300
                self._default_stale_seconds = 300

            # Availability-Konfiguration laden (überschreibt Defaults)
            try:
                avail = await self.config_service.get_availability_config()
                if isinstance(avail.get("default_stale_seconds"), int):
                    self._default_stale_seconds = max(60, avail["default_stale_seconds"])
                # per_type: Keys auf lowercase normalisieren, damit "senseBox"/"Temperature" etc. matchen
                raw_per_type = avail.get("per_type", {}) or {}
                self._per_type_stale = {str(k).lower(): int(v) for k, v in raw_per_type.items()}
                # per_device bleibt 1:1
                self._per_device_stale = avail.get("per_device", {}) or {}
            except Exception:
                self._per_type_stale = {}
                self._per_device_stale = {}

            # Auf MQTT Connect/Disconnect Events reagieren, um UI-Update zu triggern
            if not self._mqtt_unsubs:
                self._mqtt_unsubs.append(
                    self.hass.bus.async_listen(
                        EVENT_MQTT_CONNECTED, self._on_mqtt_connected_event
                    )
                )
                self._mqtt_unsubs.append(
                    self.hass.bus.async_listen(
                        EVENT_MQTT_DISCONNECTED,
                        self._on_mqtt_disconnected_event,
                    )
                )

            try:
                data = await self._async_update_data()
            except UpdateFailed as err:
                self.async_set_update_error(err)
            else:
                self.async_set_updated_data(data)
            
            _LOGGER.info("Coordinator gestartet")
        except Exception as err:
            await self.error_handler.handle_error(
                err, "Coordinator Start"
            )
            raise
    
    async def async_shutdown(self) -> None:
        """Beendet den Coordinator."""
        _LOGGER.debug("Beende Coordinator")
        errors: list[Exception] = []

        if not self._base_shutdown_complete:
            try:
                # DataUpdateCoordinator-Shutdown räumt den Debouncer-Timer und
                # geplante Refreshes auf.
                await super().async_shutdown()
            except Exception as err:
                errors.append(err)
            else:
                self._base_shutdown_complete = True

        try:
            await self._unsubscribe_from_topics()
        except Exception as err:
            errors.append(err)

        if not self._mqtt_disconnect_complete:
            try:
                await self.mqtt_service.disconnect()
            except Exception as err:
                errors.append(err)
            else:
                self._mqtt_disconnect_complete = True

        remaining_unsubs = []
        for unsub in self._mqtt_unsubs:
            try:
                unsub()
            except Exception as err:
                errors.append(err)
                remaining_unsubs.append(unsub)
        self._mqtt_unsubs = remaining_unsubs

        if errors:
            shutdown_error = RuntimeError(
                f"Coordinator-Shutdown unvollständig ({len(errors)} Fehler)"
            )
            try:
                await self.error_handler.handle_error(
                    shutdown_error, "Coordinator Shutdown"
                )
            except Exception:
                pass
            raise shutdown_error from errors[0]

        _LOGGER.info("Coordinator erfolgreich beendet")
    
    async def update_sensor_data(self, device_id: str, sensor_data: Dict[str, Any]) -> None:
        """Aktualisiert Sensordaten."""
        try:
            _LOGGER.debug("Aktualisiere Sensordaten für Gerät %s", device_id)
            
            # Daten speichern
            self._sensor_data[device_id] = sensor_data

            # Last seen aktualisieren (monotonic, robust gegen Zeitänderungen)
            self._device_last_seen[device_id] = time.monotonic()
            
            # Entities erstellen/aktualisieren
            entities = await self.entity_factory.create_entities_for_device(device_id, sensor_data)
            for entity in entities:
                entity_id = entity["entity_id"]
                self._entities[entity_id] = entity
            
            # Event auslösen – KEINE Home Assistant internen Objekte anhängen
            representative_entity_id = entities[0]["entity_id"] if entities else None
            self.hass.bus.async_fire(
                EVENT_SENSOR_DATA_RECEIVED,
                {
                    "device_id": device_id,
                    "entity_count": len(entities),
                    "entity_id": representative_entity_id,
                },
            )
            
            # Coordinator-Daten aktualisieren
            self.async_set_updated_data(self._sensor_data)
            
        except Exception as e:
            await self.error_handler.handle_error(e, f"Update Sensor Data for {device_id}")
    
    
    
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
        _LOGGER.debug("Führe Health Check durch")

        if not self._mqtt_topics:
            return self._sensor_data.copy()

        if not self.mqtt_service.is_connected:
            _LOGGER.warning("MQTT-Verbindung nicht verfügbar")
            if not await self.mqtt_service.connect():
                raise UpdateFailed("MQTT nicht verbunden")

        if not self.mqtt_service.is_connected:
            raise UpdateFailed("MQTT-Verbindung wird hergestellt")

        if not self.mqtt_service.subscriptions_ready:
            if not await self.mqtt_service.restore_subscriptions():
                raise UpdateFailed("MQTT-Topics nicht abonniert")

        return self._sensor_data.copy()

    async def _on_mqtt_connected_event(self, event: Any) -> None:
        """Reagiere auf MQTT-Connect: UI-Update triggern."""
        if event.data.get("entry_id") != self.entry.entry_id:
            return
        try:
            self.async_set_updated_data(self._sensor_data)
        except Exception as e:
            _LOGGER.debug("Fehler beim Verarbeiten des MQTT-Connect-Events: %s", e)

    async def _on_mqtt_disconnected_event(self, event: Any) -> None:
        """Reagiere auf MQTT-Disconnect: UI-Update triggern (Entities können unavailable werden)."""
        if event.data.get("entry_id") != self.entry.entry_id:
            return
        try:
            self.async_set_update_error(UpdateFailed("MQTT nicht verbunden"))
        except Exception as e:
            _LOGGER.debug("Fehler beim Verarbeiten des MQTT-Disconnect-Events: %s", e)

    def get_device_last_seen(self, device_id: str) -> Optional[float]:
        """Gibt den Last-Seen Zeitstempel (monotonic seconds) für ein Gerät zurück."""
        return self._device_last_seen.get(device_id)

    def get_stale_after_seconds(self) -> int:
        """Gibt den Stale-Threshold in Sekunden zurück."""
        return self._stale_after_seconds

    def get_effective_stale_seconds(self, device_id: str, device_type: Optional[str] = None) -> int:
        """Berechnet den effektiven Stale-Threshold für ein Gerät.

        Reihenfolge: per_device > per_type > default
        """
        # Per-Device
        if device_id in self._per_device_stale:
            return self._per_device_stale[device_id]
        # Per-Type
        if device_type and device_type.lower() in self._per_type_stale:
            return self._per_type_stale[device_type.lower()]
        # Default
        return self._default_stale_seconds

    def _find_representative_entity_id(self, device_id: str) -> Optional[str]:
        """Findet eine beliebige Entity-ID, die zu einem Gerät gehört."""
        try:
            # Bevorzugt echte HA-Entity-IDs, die sich registriert haben
            ids = self._ha_entity_ids_by_device.get(device_id)
            if ids:
                for ent_id in ids:
                    return ent_id
            for ent_id, ent in self._entities.items():
                if ent.get("device_id") == device_id:
                    return ent_id
        except Exception:
            pass
        return None

    def register_ha_entity_for_device(self, device_id: str, entity_id: str) -> None:
        """Registriert die echte HA-Entity-ID für ein Gerät (für Logbuch-Zuordnung)."""
        try:
            if device_id not in self._ha_entity_ids_by_device:
                self._ha_entity_ids_by_device[device_id] = set()
            self._ha_entity_ids_by_device[device_id].add(entity_id)
        except Exception:
            pass
    
    async def _setup_mqtt_topics(self) -> None:
        """Richtet MQTT-Topics ein."""
        try:
            _LOGGER.debug("Richte MQTT-Topics ein")
            topics: list[str] = []

            # Topics für ausgewählte Geräte
            for device_id in self.selected_devices:
                device_info = await self.config_service.get_device_by_id(device_id)
                if device_info:
                    # Topic-Pattern aus der Geräte-Konfiguration verwenden
                    topic_pattern = device_info.get("topic_pattern")
                    if topic_pattern:
                        # Topic-Pattern enthält bereits die Device-ID
                        topic = topic_pattern
                        topics.append(topic)
                        _LOGGER.debug("Topic für %s: %s", device_id, topic)
                    else:
                        _LOGGER.warning("Kein topic_pattern für Gerät %s gefunden", device_id)
            
            # Topics für Median-Entities
            for entity_id in self.selected_median_entities:
                # Median-Entity Info laden (inkl. Fallback-Suchorte)
                median_entities = await self.config_service.get_median_entities()
                median_info = next(
                    (entity for entity in median_entities if entity.get("id") == entity_id),
                    None,
                )

                if median_info:
                    topic_pattern = median_info.get("topic_pattern")
                    if topic_pattern:
                        topic = topic_pattern
                        topics.append(topic)
                        _LOGGER.debug("Median Topic für %s: %s", entity_id, topic)
                    else:
                        _LOGGER.warning(
                            "Kein topic_pattern für Median-Entity %s gefunden", entity_id
                        )
                else:
                    _LOGGER.warning(
                        "Median-Entity %s nicht in der Konfiguration gefunden", entity_id
                    )
            
            self._mqtt_topics = list(dict.fromkeys(topics))
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
        _LOGGER.debug("Kündige MQTT-Topics")
        remaining_topics = []
        errors: list[Exception] = []

        for topic in self._mqtt_topics:
            try:
                await self.mqtt_service.unsubscribe(topic)
            except Exception as err:
                remaining_topics.append(topic)
                errors.append(err)

        self._mqtt_topics = remaining_topics
        if errors:
            raise RuntimeError(
                f"{len(errors)} MQTT-Topics konnten nicht gekündigt werden"
            ) from errors[0]
        _LOGGER.debug("MQTT-Topics gekündigt")
    
    async def _handle_mqtt_message(self, topic: str, payload: Any) -> None:
        """Behandelt MQTT-Nachrichten."""
        try:
            _LOGGER.debug("Behandle MQTT-Nachricht: %s", topic)
            
            # Message parsen
            parsed_data = await self.parser_service.parse_message(topic, payload)
            if not parsed_data:
                # Keine relevanten Daten zurückgeliefert (z. B. RSSI-Only/Meta oder nicht konfigurierte Felder)
                _LOGGER.debug(
                    "Parser lieferte keine verarbeitbaren Daten für Topic %s (Nachricht ggf. ignoriert)",
                    topic,
                )
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
