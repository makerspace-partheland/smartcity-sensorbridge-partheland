"""
Logbook-Unterstützung für SmartCity SensorBridge Partheland.

Zeigt MQTT-Connect/Disconnect-Ereignisse im Home Assistant Logbuch an.
"""

from __future__ import annotations

from typing import Any, Dict

from homeassistant.core import HomeAssistant
from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME

from .const import (
    DOMAIN,
    NAME,
    EVENT_MQTT_CONNECTED,
    EVENT_MQTT_DISCONNECTED,
    EVENT_SENSOR_DATA_RECEIVED,
)


def _describe_mqtt_connected(event: Any) -> Dict[str, Any]:
    return {
        LOGBOOK_ENTRY_NAME: NAME,
        LOGBOOK_ENTRY_MESSAGE: "MQTT verbunden",
    }


def _describe_mqtt_disconnected(event: Any) -> Dict[str, Any]:
    return {
        LOGBOOK_ENTRY_NAME: NAME,
        LOGBOOK_ENTRY_MESSAGE: "MQTT-Verbindung verloren",
    }


def _describe_data_received(event: Any) -> Dict[str, Any]:
    data = getattr(event, "data", {}) or {}
    device_id = data.get("device_id", "unbekanntes Gerät")
    cnt = data.get("entity_count")
    entity_id = data.get("entity_id")
    cnt_part = f" ({cnt} Entities)" if cnt is not None else ""
    result = {
        LOGBOOK_ENTRY_NAME: NAME,
        LOGBOOK_ENTRY_MESSAGE: f"Daten empfangen für {device_id}{cnt_part}",
    }
    if entity_id:
        result["entity_id"] = entity_id
    return result


def async_describe_events(hass: HomeAssistant, async_describe_event) -> None:
    """Registriert Logbuch-Beschreibungen für Domain-Events."""
    async_describe_event(DOMAIN, EVENT_MQTT_CONNECTED, _describe_mqtt_connected)
    async_describe_event(DOMAIN, EVENT_MQTT_DISCONNECTED, _describe_mqtt_disconnected)
    async_describe_event(DOMAIN, EVENT_SENSOR_DATA_RECEIVED, _describe_data_received)


