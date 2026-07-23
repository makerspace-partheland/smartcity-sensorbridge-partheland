from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sensorbridge_partheland.const import DOMAIN
from custom_components.sensorbridge_partheland.device_tracker import (
    SensorBridgeStationTracker,
    _has_valid_coordinates,
    async_setup_entry,
)


def _device(device_id: str = "station") -> dict:
    return {
        "id": device_id,
        "name": "Station Brandis",
        "type": "senseBox",
        "api_id": "mspl-example",
        "api_type": "SenseBoxDevice",
        "status": "online",
        "last_seen": "2026-07-23T11:27:22.976Z",
        "active": "true",
        "location_type": "field",
        "operationalstatus": None,
        "latitude": 51.3268,
        "longitude": 12.5954,
        "external_urls": {
            "makerspace": "https://example.invalid/station",
            "openSenseMap": "https://example.invalid/opensensemap",
        },
    }


async def test_setup_creates_trackers_only_for_selected_valid_coordinates(hass):
    config_service = AsyncMock()
    config_service.get_device_by_id.side_effect = [
        _device("valid"),
        {"id": "missing", "name": "Ohne Koordinaten"},
        {
            "id": "invalid",
            "name": "Ungültige Koordinaten",
            "latitude": 91,
            "longitude": 12,
        },
    ]
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"selected_devices": ["valid", "missing", "invalid"]},
    )
    entry.runtime_data = SimpleNamespace(config_service=config_service)
    add_entities = Mock()

    await async_setup_entry(hass, entry, add_entities)

    trackers = add_entities.call_args.args[0]
    assert [tracker.unique_id for tracker in trackers] == ["valid_location"]
    assert config_service.get_device_by_id.await_count == 3


async def test_setup_keeps_existing_planned_or_defective_sources(hass):
    planned = _device("planned")
    planned["operationalstatus"] = "planned"
    defective = _device("defective")
    defective["operationalstatus"] = "defective"
    config_service = AsyncMock()
    config_service.get_device_by_id.side_effect = [planned, defective]
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "selected_devices": ["planned", "defective"],
            "selected_median_entities": ["median"],
        },
    )
    entry.runtime_data = SimpleNamespace(config_service=config_service)
    add_entities = Mock()

    await async_setup_entry(hass, entry, add_entities)

    trackers = add_entities.call_args.args[0]
    assert [tracker.unique_id for tracker in trackers] == [
        "planned_location",
        "defective_location",
    ]


async def test_setup_does_not_create_trackers_for_medians(hass):
    config_service = AsyncMock()
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "selected_devices": [],
            "selected_median_entities": ["median"],
        },
    )
    entry.runtime_data = SimpleNamespace(config_service=config_service)
    add_entities = Mock()

    await async_setup_entry(hass, entry, add_entities)

    assert add_entities.call_args.args[0] == []
    config_service.get_device_by_id.assert_not_awaited()


def test_tracker_exposes_static_location_and_api_metadata():
    tracker = SensorBridgeStationTracker(_device())

    assert tracker.unique_id == "station_location"
    assert tracker.latitude == 51.3268
    assert tracker.longitude == 12.5954
    assert tracker.location_accuracy == 0.0
    assert tracker.available is True
    assert tracker.device_info["identifiers"] == {(DOMAIN, "station")}
    assert tracker.device_info["name"] == "Station Brandis"
    assert tracker.device_info["configuration_url"] == (
        "https://example.invalid/station"
    )
    assert tracker.extra_state_attributes == {
        "measurement_source_id": "station",
        "api_id": "mspl-example",
        "api_type": "SenseBoxDevice",
        "device_type": "senseBox",
        "status": "online",
        "last_seen": "2026-07-23T11:27:22.976Z",
        "active": "true",
        "location_type": "field",
        "makerspace_url": "https://example.invalid/station",
        "open_sense_map_url": "https://example.invalid/opensensemap",
    }


def test_coordinate_validation_rejects_missing_invalid_and_boolean_values():
    assert _has_valid_coordinates(_device()) is True
    assert _has_valid_coordinates({"latitude": 51, "longitude": None}) is False
    assert _has_valid_coordinates({"latitude": 91, "longitude": 12}) is False
    assert _has_valid_coordinates({"latitude": True, "longitude": 12}) is False
    assert _has_valid_coordinates({"latitude": float("nan"), "longitude": 12}) is False
