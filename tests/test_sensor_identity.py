from __future__ import annotations

from unittest.mock import AsyncMock, Mock

from custom_components.sensorbridge_partheland.sensor import (
    _resolve_sensor_unique_id,
)


async def test_existing_legacy_unique_id_is_preserved(hass, mocker):
    registry = Mock()
    registry.async_get_entity_id.side_effect = lambda domain, platform, unique_id: (
        "sensor.station_temperatur"
        if unique_id == "station_Temperatur"
        else None
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
