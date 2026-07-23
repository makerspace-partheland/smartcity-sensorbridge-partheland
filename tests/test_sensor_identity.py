from __future__ import annotations

import logging
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import EntityPlatform
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sensorbridge_partheland.const import DOMAIN
from custom_components.sensorbridge_partheland.sensor import (
    SensorBridgeSensor,
    _resolve_sensor_unique_id,
)

_LOGGER = logging.getLogger(__name__)


def _sensor_dependencies(hass):
    coordinator = Mock(
        hass=hass,
        data={},
        last_update_success=True,
        mqtt_service=Mock(is_connected=True),
    )
    coordinator.async_add_listener.return_value = lambda: None
    coordinator.get_device_last_seen.return_value = None

    config_service = Mock()
    config_service.get_field_mapping = AsyncMock(return_value={})
    config_service.get_sensor_names = AsyncMock(
        return_value={"temperature": "Temperatur"}
    )
    config_service.get_icons = AsyncMock(return_value={})
    config_service.get_sensor_categories = AsyncMock(return_value={})
    return coordinator, config_service


def _temperature_sensor(coordinator, config_service):
    return SensorBridgeSensor(
        coordinator,
        {
            "device_id": "station",
            "device_name": "Station Brandis",
            "sensor_type": "temperature",
        },
        config_service,
    )


def _sensor_platform(hass, entry):
    platform = EntityPlatform(
        hass=hass,
        logger=_LOGGER,
        domain="sensor",
        platform_name=DOMAIN,
        platform=None,
        scan_interval=timedelta(seconds=30),
        entity_namespace=None,
    )
    platform.config_entry = entry
    return platform


async def test_existing_legacy_unique_id_is_preserved(hass, mocker):
    registry = Mock()
    registry.async_get_entity_id.side_effect = (
        lambda domain, platform, unique_id: (
            "sensor.station_temperatur"
            if unique_id == "station_Temperatur"
            else None
        )
    )
    mocker.patch(
        "custom_components.sensorbridge_partheland.sensor.er.async_get",
        return_value=registry,
    )
    config_service = Mock()
    config_service.get_legacy_sensor_names = AsyncMock(
        return_value=["Temperatur"]
    )

    unique_id = await _resolve_sensor_unique_id(
        hass, "station", "temperature", config_service
    )

    assert unique_id == "station_Temperatur"


async def test_new_sensor_uses_canonical_unique_id(hass, mocker):
    registry = Mock()
    registry.async_get_entity_id.return_value = None
    mocker.patch(
        "custom_components.sensorbridge_partheland.sensor.er.async_get",
        return_value=registry,
    )
    config_service = Mock()
    config_service.get_legacy_sensor_names = AsyncMock(
        return_value=["Temperatur"]
    )

    unique_id = await _resolve_sensor_unique_id(
        hass, "station", "temperature", config_service
    )

    assert unique_id == "station_temperature"


def test_sensor_leaves_entity_id_assignment_to_registry(hass):
    coordinator, config_service = _sensor_dependencies(hass)
    sensor = _temperature_sensor(coordinator, config_service)

    assert sensor.entity_id is None
    assert sensor.suggested_object_id == "temperature"


async def test_reload_preserves_registry_identity_without_suffix_drift(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    coordinator, config_service = _sensor_dependencies(hass)
    platform = _sensor_platform(hass, entry)
    reloaded_platform = None

    try:
        first_sensor = _temperature_sensor(coordinator, config_service)
        await platform.async_add_entities([first_sensor])

        entity_registry = er.async_get(hass)
        first_registry_entry = entity_registry.async_get(
            first_sensor.entity_id
        )
        assert first_sensor.entity_id == "sensor.station_brandis_temperature"
        assert first_registry_entry is not None
        assert first_registry_entry.unique_id == "station_temperature"
        assert first_registry_entry.suggested_object_id is None
        assert first_registry_entry.object_id_base == "temperature"

        reloaded_sensor = _temperature_sensor(coordinator, config_service)
        assert reloaded_sensor.entity_id is None

        await platform.async_reset()
        reloaded_platform = _sensor_platform(hass, entry)
        await reloaded_platform.async_add_entities([reloaded_sensor])

        reloaded_registry_entry = entity_registry.async_get(
            reloaded_sensor.entity_id
        )
        assert reloaded_sensor.entity_id == first_sensor.entity_id
        assert reloaded_registry_entry is not None
        assert reloaded_registry_entry.unique_id == (
            first_registry_entry.unique_id
        )
        assert reloaded_registry_entry.suggested_object_id is None
        assert reloaded_registry_entry.object_id_base == "temperature"
    finally:
        await platform.async_reset()
        if reloaded_platform is not None:
            await reloaded_platform.async_reset()
