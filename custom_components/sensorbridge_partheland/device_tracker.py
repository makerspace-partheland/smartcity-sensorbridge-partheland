"""Standort-Entitäten für die ausgewählten Messquellen."""

from __future__ import annotations

import math
from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .const import CONF_SELECTED_DEVICES, DOMAIN, MANUFACTURER
from .runtime import SensorBridgeConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SensorBridgeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Richte einen ortsfesten Standort je ausgewählter Messquelle ein."""
    config_service = entry.runtime_data.config_service
    trackers: list[SensorBridgeStationTracker] = []

    for device_id in entry.data.get(CONF_SELECTED_DEVICES, []):
        device = await config_service.get_device_by_id(device_id)
        if not device or not _has_valid_coordinates(device):
            continue
        trackers.append(SensorBridgeStationTracker(device))

    async_add_entities(trackers)


def _has_valid_coordinates(device: dict[str, Any]) -> bool:
    """Prüfe, ob die API-Metadaten nutzbare Punktkoordinaten enthalten."""
    latitude = device.get("latitude")
    longitude = device.get("longitude")
    return (
        isinstance(latitude, (int, float))
        and not isinstance(latitude, bool)
        and math.isfinite(latitude)
        and -90 <= latitude <= 90
        and isinstance(longitude, (int, float))
        and not isinstance(longitude, bool)
        and math.isfinite(longitude)
        and -180 <= longitude <= 180
    )


class SensorBridgeStationTracker(TrackerEntity):
    """Ortsfester Standort einer Messquelle."""

    _attr_available = True
    _attr_has_entity_name = True
    _attr_icon = "mdi:map-marker"
    _attr_location_accuracy = 0.0
    _attr_should_poll = False
    _attr_source_type = SourceType.GPS
    _attr_translation_key = "location"

    def __init__(self, device: dict[str, Any]) -> None:
        """Initialisiere den Standort aus dem gespeicherten API-Katalogeintrag."""
        device_id = str(device["id"])
        device_name = str(device.get("name") or device_id)
        self._attr_unique_id = f"{device_id}_location"
        self._attr_suggested_object_id = f"{slugify(device_name)}_standort"
        self._attr_latitude = float(device["latitude"])
        self._attr_longitude = float(device["longitude"])

        external_urls = device.get("external_urls", {})
        configuration_url = None
        if isinstance(external_urls, dict):
            configuration_url = external_urls.get("makerspace") or external_urls.get(
                "openSenseMap"
            )

        device_info: dict[str, Any] = {
            "identifiers": {(DOMAIN, device_id)},
            "name": device_name,
            "manufacturer": MANUFACTURER,
            "model": device_id,
        }
        if isinstance(configuration_url, str) and configuration_url:
            device_info["configuration_url"] = configuration_url
        self._attr_device_info = DeviceInfo(**device_info)

        metadata = {
            "measurement_source_id": device_id,
            "api_id": device.get("api_id"),
            "api_type": device.get("api_type"),
            "device_type": device.get("type"),
            "status": device.get("status"),
            "last_seen": device.get("last_seen"),
            "operational_status": device.get("operationalstatus"),
            "active": device.get("active"),
            "location_type": device.get("location_type"),
        }
        if isinstance(external_urls, dict):
            metadata["makerspace_url"] = external_urls.get("makerspace")
            metadata["open_sense_map_url"] = external_urls.get("openSenseMap")
        self._attr_extra_state_attributes = {
            key: value
            for key, value in metadata.items()
            if value is not None and value != ""
        }
