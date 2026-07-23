from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sensorbridge_partheland import sensor as sensor_platform
from custom_components.sensorbridge_partheland.const import (
    CONF_SELECTED_DEVICES,
    CONF_SELECTED_MEDIAN_ENTITIES,
    DOMAIN,
    DWD_POLLEN_SOURCE,
    DWD_PRECIPITATION_STATIONS,
    GEOBOX_BRANDIS_SOURCE,
)
from custom_components.sensorbridge_partheland.runtime import (
    SensorBridgeRuntimeData,
)


def _entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SELECTED_DEVICES: ["device-a"],
            CONF_SELECTED_MEDIAN_ENTITIES: ["median-a"],
        },
    )
    entry.add_to_hass(hass)
    entry.runtime_data = SensorBridgeRuntimeData(
        config_service=Mock(),
        coordinator=Mock(),
        supplemental_coordinators={
            DWD_POLLEN_SOURCE: Mock(),
            **{
                station["source"]: Mock()
                for station in DWD_PRECIPITATION_STATIONS.values()
            },
            GEOBOX_BRANDIS_SOURCE: Mock(),
        },
    )
    return entry


@pytest.mark.parametrize(
    "failing_group",
    [
        "device",
        "median",
        "pollen",
        "dwd_precipitation_07362",
        "dwd_precipitation_07323",
        "geobox",
    ],
)
async def test_one_entity_group_failure_does_not_drop_other_groups(
    hass, mocker, failing_group
):
    entry = _entry(hass)
    entities = {
        "device": object(),
        "median": object(),
        "pollen": object(),
        "dwd_precipitation_07362": object(),
        "dwd_precipitation_07323": object(),
        "geobox": object(),
    }
    device_factory = mocker.patch.object(
        sensor_platform,
        "create_device_entities",
        new_callable=AsyncMock,
        return_value=[entities["device"]],
    )
    median_factory = mocker.patch.object(
        sensor_platform,
        "create_median_entities",
        new_callable=AsyncMock,
        return_value=[entities["median"]],
    )
    pollen_factory = mocker.patch(
        "custom_components.sensorbridge_partheland.pollen."
        "create_pollen_entities",
        return_value=[entities["pollen"]],
    )
    precipitation_entities = iter(
        [
            [entities["dwd_precipitation_07362"]],
            [entities["dwd_precipitation_07323"]],
        ]
    )
    precipitation_factory = mocker.patch(
        "custom_components.sensorbridge_partheland.precipitation."
        "create_precipitation_entities",
        side_effect=lambda _coordinator: next(precipitation_entities),
    )
    geobox_factory = mocker.patch(
        "custom_components.sensorbridge_partheland.geobox."
        "create_geobox_entities",
        return_value=[entities["geobox"]],
    )

    if failing_group == "device":
        device_factory.side_effect = RuntimeError("device failed")
    elif failing_group == "median":
        median_factory.side_effect = RuntimeError("median failed")
    elif failing_group == "pollen":
        pollen_factory.side_effect = RuntimeError("pollen failed")
    elif failing_group.startswith("dwd_precipitation"):
        precipitation_entities = iter(
            [
                RuntimeError("precipitation failed")
                if failing_group == "dwd_precipitation_07362"
                else [entities["dwd_precipitation_07362"]],
                RuntimeError("precipitation failed")
                if failing_group == "dwd_precipitation_07323"
                else [entities["dwd_precipitation_07323"]],
            ]
        )

        def _precipitation_result(_coordinator):
            result = next(precipitation_entities)
            if isinstance(result, Exception):
                raise result
            return result

        precipitation_factory.side_effect = _precipitation_result
    elif failing_group == "geobox":
        geobox_factory.side_effect = RuntimeError("geobox failed")

    add_entities = Mock()
    await sensor_platform.async_setup_entry(hass, entry, add_entities)

    expected = [
        entity
        for group, entity in entities.items()
        if group != failing_group
    ]
    add_entities.assert_called_once_with(expected)


async def test_async_add_entities_failure_propagates(hass, mocker):
    entry = _entry(hass)
    mocker.patch.object(
        sensor_platform,
        "create_device_entities",
        new_callable=AsyncMock,
        return_value=[],
    )
    mocker.patch.object(
        sensor_platform,
        "create_median_entities",
        new_callable=AsyncMock,
        return_value=[],
    )
    mocker.patch(
        "custom_components.sensorbridge_partheland.pollen."
        "create_pollen_entities",
        return_value=[],
    )
    mocker.patch(
        "custom_components.sensorbridge_partheland.precipitation."
        "create_precipitation_entities",
        return_value=[],
    )
    mocker.patch(
        "custom_components.sensorbridge_partheland.geobox."
        "create_geobox_entities",
        return_value=[],
    )
    add_entities = Mock(side_effect=RuntimeError("platform failed"))

    with pytest.raises(RuntimeError, match="platform failed"):
        await sensor_platform.async_setup_entry(hass, entry, add_entities)
