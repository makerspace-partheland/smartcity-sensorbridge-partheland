from __future__ import annotations

from unittest.mock import AsyncMock, Mock

from custom_components.sensorbridge_partheland.parser_service import ParserService


def _config_service(device_type: str, sensors: list[str]):
    service = Mock()
    service.get_parsing_config = AsyncMock(
        return_value={
            "sensebox": {
                "data_path": "fields",
                "median_detection": {"topic_pattern": "senseBox:home/median"},
            },
            "specialized_sensors": {
                "data_path": "fields",
                "ignore_rssi_only": True,
            },
        }
    )
    service.get_device_by_id = AsyncMock(
        return_value={"id": "station", "type": device_type, "sensors": sensors}
    )
    aliases = {
        "Temperatur": "temperature",
        "GehaeuseTemp": "temperature_case",
        "TempC_DS": "soil_temperature",
    }
    service.get_canonical_sensor_name = AsyncMock(
        side_effect=lambda field: aliases.get(field, field)
    )
    service.load_config = AsyncMock(
        return_value={"field_mapping": {"unit_conversions": {}}}
    )
    service.get_median_entities = AsyncMock(return_value=[])
    return service


async def test_sensebox_raw_fields_are_mapped_to_api_names(hass):
    parser = ParserService(
        hass,
        _config_service("senseBox", ["temperature", "temperature_case"]),
    )

    parsed = await parser.parse_message(
        "senseBox:home/station",
        '{"fields":{"Temperatur":21.5,"GehaeuseTemp":22.0,"ignored":4}}',
    )

    assert parsed["sensor_data"] == {
        "temperature": 21.5,
        "temperature_case": 22.0,
    }


async def test_specialized_raw_fields_are_mapped_to_api_names(hass):
    parser = ParserService(
        hass,
        _config_service("Moisture", ["soil_temperature"]),
    )

    parsed = await parser.parse_message(
        "sensoren/station", '{"fields":{"TempC_DS":12.4,"rssi":-90}}'
    )

    assert parsed["sensor_data"] == {"soil_temperature": 12.4}
