from __future__ import annotations

from custom_components.sensorbridge_partheland.config_service import ConfigService


async def test_local_config_no_longer_contains_device_catalog(hass):
    service = ConfigService(hass)

    config = await service.load_config()

    assert "known_devices" not in config
    assert "median_entities" in config
    assert len(config["median_entities"]) == len(
        {entity["id"] for entity in config["median_entities"]}
    )
    assert await service.validate_config() is True


async def test_selection_candidates_filter_new_and_preserve_existing(hass):
    service = ConfigService(hass)
    service._catalog = [
        {
            "id": "recent",
            "name": "Recent",
            "type": "senseBox",
            "last_seen": "2099-07-22T00:00:00Z",
            "operationalstatus": None,
            "sensors": ["temperature"],
        },
        {
            "id": "defective",
            "name": "Defective",
            "type": "senseBox",
            "last_seen": "2099-07-22T00:00:00Z",
            "operationalstatus": "defective",
            "sensors": ["temperature"],
        },
        {
            "id": "planned",
            "name": "Planned",
            "type": "senseBox",
            "last_seen": "2099-07-22T00:00:00Z",
            "operationalstatus": "planned",
            "sensors": ["temperature"],
        },
    ]

    new_grouped = await service.get_selection_candidates()
    existing_grouped = await service.get_selection_candidates(
        ["defective", "planned", "removed"]
    )

    assert [device["id"] for device in new_grouped["senseBox"]] == ["recent"]
    existing_ids = {
        device["id"]
        for devices in existing_grouped.values()
        for device in devices
    }
    assert existing_ids == {"recent", "defective", "planned", "removed"}


async def test_entry_snapshot_supplies_sensors_when_live_measurements_are_empty(hass):
    service = ConfigService(hass)
    service.register_entry_data(
        {
            "device_metadata": {
                "station": {
                    "id": "station",
                    "name": "Station",
                    "type": "senseBox",
                    "sensors": ["temperature"],
                    "sensor_metadata": {"temperature": {"unit": "CEL"}},
                    "topic_pattern": "senseBox:home/station",
                }
            }
        }
    )
    service._catalog = [
        {
            "id": "station",
            "name": "Station",
            "type": "senseBox",
            "sensors": [],
            "sensor_metadata": {},
            "topic_pattern": "senseBox:home/station",
        }
    ]

    device = await service.get_device_by_id("station")

    assert device["sensors"] == ["temperature"]
    assert device["sensor_metadata"] == {"temperature": {"unit": "CEL"}}


async def test_mqtt_field_aliases_use_api_sensor_names(hass):
    service = ConfigService(hass)

    assert await service.get_canonical_sensor_name("Temperatur") == "temperature"
    assert await service.get_canonical_sensor_name("TempC_DS") == "soil_temperature"
    assert await service.get_canonical_sensor_name("water_level") == "water_level"
