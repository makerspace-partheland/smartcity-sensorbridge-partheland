from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sensorbridge_partheland import (
    async_remove_config_entry_device,
)
from custom_components.sensorbridge_partheland.const import (
    CONF_INCLUDE_DWD_POLLEN,
    DOMAIN,
    DWD_POLLEN_DEVICE_ID,
    DWD_POLLEN_SOURCE,
    SUPPLEMENTAL_COORDINATORS,
)
from custom_components.sensorbridge_partheland.pollen import (
    DwdPollenCoordinator,
    PollenDataError,
    create_pollen_entities,
    parse_dwd_pollen,
)


def _payload() -> dict:
    pollen = {
        "Hasel": {"today": "0", "tomorrow": "0-1", "dayafter_to": "1"},
        "Erle": {"today": "1-2", "tomorrow": "2", "dayafter_to": "2-3"},
        "Esche": {"today": "3", "tomorrow": "-1", "dayafter_to": "0"},
        "Birke": {"today": "0", "tomorrow": "1", "dayafter_to": "2"},
        "Graeser": {"today": "1", "tomorrow": "1-2", "dayafter_to": "2"},
        "Roggen": {"today": "2", "tomorrow": "2-3", "dayafter_to": "3"},
        "Beifuss": {"today": "0-1", "tomorrow": "1", "dayafter_to": "1-2"},
        "Ambrosia": {"today": "-1", "tomorrow": "0", "dayafter_to": "0"},
    }
    return {
        "last_update": "2026-07-23 11:00 Uhr",
        "next_update": "2026-07-24 11:00 Uhr",
        "content": [
            {
                "region_id": 80,
                "partregion_id": 81,
                "region_name": "Tiefland Sachsen",
                "Pollen": pollen,
            }
        ],
    }


def test_parse_dwd_pollen_maps_all_levels_and_forecast_periods():
    parsed = parse_dwd_pollen(
        _payload(),
        now=datetime(2026, 7, 23, 12, tzinfo=UTC),
    )

    assert parsed["last_update"] == "2026-07-23T11:00:00+02:00"
    assert parsed["next_update"] == "2026-07-24T11:00:00+02:00"
    assert parsed["species"]["hazel"] == {
        "today": "none",
        "today_raw": "0",
        "tomorrow": "none_to_low",
        "tomorrow_raw": "0-1",
        "dayafter_to": "low",
        "dayafter_to_raw": "1",
    }
    assert parsed["species"]["alder"]["today"] == "low_to_medium"
    assert parsed["species"]["alder"]["tomorrow"] == "medium"
    assert parsed["species"]["alder"]["dayafter_to"] == "medium_to_high"
    assert parsed["species"]["ash"]["today"] == "high"
    assert parsed["species"]["ash"]["tomorrow"] is None
    assert parsed["species"]["ragweed"]["today"] is None
    assert len(parsed["species"]) == 8


def test_parse_dwd_pollen_rejects_missing_region_unknown_level_and_stale_data():
    missing = _payload()
    missing["content"][0]["partregion_id"] = 82
    with pytest.raises(PollenDataError, match="Teilregion"):
        parse_dwd_pollen(
            missing,
            now=datetime(2026, 7, 23, 12, tzinfo=UTC),
        )

    unknown = _payload()
    unknown["content"][0]["Pollen"]["Birke"]["today"] = "4"
    with pytest.raises(PollenDataError, match="Unbekannter"):
        parse_dwd_pollen(
            unknown,
            now=datetime(2026, 7, 23, 12, tzinfo=UTC),
        )

    with pytest.raises(PollenDataError, match="veraltet"):
        parse_dwd_pollen(
            _payload(),
            now=datetime(2026, 7, 24, 16, 1, tzinfo=UTC),
        )


async def test_pollen_entities_have_stable_identity_and_forecast_attributes(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    coordinator = DwdPollenCoordinator(hass, entry)
    coordinator.async_set_updated_data(
        parse_dwd_pollen(
            _payload(),
            now=datetime(2026, 7, 23, 12, tzinfo=UTC),
        )
    )

    entities = create_pollen_entities(coordinator)

    assert [entity.unique_id for entity in entities] == [
        "dwd_pollen:81:hazel",
        "dwd_pollen:81:alder",
        "dwd_pollen:81:ash",
        "dwd_pollen:81:birch",
        "dwd_pollen:81:grasses",
        "dwd_pollen:81:rye",
        "dwd_pollen:81:mugwort",
        "dwd_pollen:81:ragweed",
    ]
    hazel = entities[0]
    assert hazel.native_value == "none"
    assert hazel.device_info["identifiers"] == {(DOMAIN, DWD_POLLEN_DEVICE_ID)}
    assert hazel.device_info["manufacturer"] == "Deutscher Wetterdienst"
    assert hazel.extra_state_attributes == {
        "level_raw": "0",
        "tomorrow": "0-1",
        "day_after_tomorrow": "1",
        "last_update": "2026-07-23T11:00:00+02:00",
        "next_update": "2026-07-24T11:00:00+02:00",
    }


async def test_removing_pollen_device_disables_and_stops_source(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_INCLUDE_DWD_POLLEN: True},
    )
    entry.add_to_hass(hass)
    coordinator = AsyncMock()
    hass.data[DOMAIN] = {
        SUPPLEMENTAL_COORDINATORS: {entry.entry_id: {DWD_POLLEN_SOURCE: coordinator}}
    }

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, DWD_POLLEN_DEVICE_ID)},
        name="DWD Pollenflug Tiefland Sachsen",
    )
    entity_registry = er.async_get(hass)
    entity = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "dwd_pollen:81:hazel",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="dwd_pollen_hasel",
    )

    assert await async_remove_config_entry_device(hass, entry, device) is True

    assert entry.data[CONF_INCLUDE_DWD_POLLEN] is False
    coordinator.async_shutdown.assert_awaited_once_with()
    assert (
        DWD_POLLEN_SOURCE
        not in hass.data[DOMAIN][SUPPLEMENTAL_COORDINATORS][entry.entry_id]
    )
    assert entity_registry.async_get(entity.entity_id) is None
