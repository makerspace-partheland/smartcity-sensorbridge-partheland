from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sensorbridge_partheland import (
    async_remove_config_entry_device,
)
from custom_components.sensorbridge_partheland.const import (
    CONF_INCLUDE_GEOBOX_BRANDIS,
    DOMAIN,
    GEOBOX_BRANDIS_DEVICE_ID,
    GEOBOX_BRANDIS_SOURCE,
    SUPPLEMENTAL_COORDINATORS,
)
from custom_components.sensorbridge_partheland.geobox import (
    GeoBoxBrandisCoordinator,
    GeoBoxDataError,
    create_geobox_entities,
    parse_geobox_brandis,
)


def _payload(**overrides) -> dict:
    attributes = {
        "de_id": "01038",
        "de_label": "Brandis (135 m)",
        "de_lng": 12.59551255,
        "de_lat": 51.3266489,
        "de_datetime": 1784808000000,
        "de_ta200": 15.4,
        "de_prec": 0.0,
        "de_prec_sum": 0.8,
        "de_rh200": 91.0,
        "de_gr200": 208.0,
        "de_wv200": 1.6,
    }
    attributes.update(overrides)
    return {"features": [{"attributes": attributes}]}


def test_parse_geobox_brandis_maps_current_public_values():
    parsed = parse_geobox_brandis(
        _payload(),
        now=datetime(2026, 7, 23, 12, 10, tzinfo=UTC),
    )

    assert parsed["station_id"] == "01038"
    assert parsed["label"] == "Brandis (135 m)"
    assert parsed["latitude"] == 51.3266489
    assert parsed["longitude"] == 12.59551255
    assert parsed["measurement_time"] == datetime(
        2026, 7, 23, 12, 0, tzinfo=UTC
    )
    assert parsed["values"] == {
        "air_temperature": 15.4,
        "precipitation_last_hour": 0.0,
        "precipitation_today": 0.8,
        "relative_humidity": 91.0,
        "solar_radiation_last_hour": 208.0,
        "wind_speed": 1.6,
    }
    assert parsed["last_reset"].isoformat() == "2026-07-23T00:00:00+02:00"


def test_parse_geobox_brandis_preserves_null_and_hides_yesterday_total():
    parsed = parse_geobox_brandis(
        _payload(
            de_datetime=1784757300000,
            de_gr200=None,
        ),
        now=datetime(2026, 7, 22, 22, 45, tzinfo=UTC),
    )

    assert parsed["values"]["solar_radiation_last_hour"] is None
    assert parsed["values"]["precipitation_today"] is None
    assert parsed["last_reset"].isoformat() == "2026-07-23T00:00:00+02:00"


@pytest.mark.parametrize(
    ("payload", "now", "message"),
    [
        (
            {"features": []},
            datetime(2026, 7, 23, 12, 10, tzinfo=UTC),
            "fehlt",
        ),
        (
            _payload(de_id="99999"),
            datetime(2026, 7, 23, 12, 10, tzinfo=UTC),
            "Station",
        ),
        (
            _payload(de_rh200=101),
            datetime(2026, 7, 23, 12, 10, tzinfo=UTC),
            "Luftfeuchte",
        ),
        (
            _payload(),
            datetime(2026, 7, 23, 15, 1, tzinfo=UTC),
            "veraltet",
        ),
    ],
)
def test_parse_geobox_brandis_rejects_invalid_or_stale_data(
    payload, now, message
):
    with pytest.raises(GeoBoxDataError, match=message):
        parse_geobox_brandis(payload, now=now)


async def test_geobox_entities_have_stable_identity_and_semantics(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    coordinator = GeoBoxBrandisCoordinator(hass, entry)
    coordinator.async_set_updated_data(
        parse_geobox_brandis(
            _payload(),
            now=datetime(2026, 7, 23, 12, 10, tzinfo=UTC),
        )
    )

    entities = create_geobox_entities(coordinator)

    assert [entity.unique_id for entity in entities] == [
        "geobox:01038:air_temperature",
        "geobox:01038:relative_humidity",
        "geobox:01038:precipitation_last_hour",
        "geobox:01038:precipitation_today",
        "geobox:01038:solar_radiation_last_hour",
        "geobox:01038:wind_speed",
        "geobox:01038:measurement_time",
    ]
    temperature = entities[0]
    precipitation_last_hour = entities[2]
    precipitation_today = entities[3]
    solar_radiation_last_hour = entities[4]
    timestamp = entities[6]
    assert temperature.device_class == SensorDeviceClass.TEMPERATURE
    assert temperature.state_class == SensorStateClass.MEASUREMENT
    assert precipitation_last_hour.state_class == SensorStateClass.MEASUREMENT
    assert precipitation_today.state_class == SensorStateClass.TOTAL
    assert precipitation_today.last_reset.isoformat() == (
        "2026-07-23T00:00:00+02:00"
    )
    assert solar_radiation_last_hour.device_class is None
    assert solar_radiation_last_hour.state_class is None
    assert solar_radiation_last_hour.native_unit_of_measurement == "Wh/m²"
    assert timestamp.device_class == SensorDeviceClass.TIMESTAMP
    assert temperature.device_info["identifiers"] == {
        (DOMAIN, GEOBOX_BRANDIS_DEVICE_ID)
    }
    assert temperature.device_info["manufacturer"] == "LfULG Sachsen"


async def test_geobox_coordinator_reuses_etag_payload_on_not_modified(
    hass, mocker
):
    class _Response:
        def __init__(self, status):
            self.status = status
            self.headers = {"ETag": '"brandis-test"'}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        def raise_for_status(self):
            return None

        async def json(self, content_type=None):
            return _payload()

    class _Session:
        def __init__(self):
            self.responses = iter((_Response(200), _Response(304)))
            self.headers = []

        def get(self, *args, **kwargs):
            self.headers.append(kwargs["headers"])
            return next(self.responses)

    session = _Session()
    mocker.patch(
        "custom_components.sensorbridge_partheland.geobox."
        "async_get_clientsession",
        return_value=session,
    )
    parse_mock = mocker.patch(
        "custom_components.sensorbridge_partheland.geobox."
        "parse_geobox_brandis",
        side_effect=(
            {"values": {"air_temperature": 15.4}},
            {"values": {"air_temperature": 15.4}},
        ),
    )
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    coordinator = GeoBoxBrandisCoordinator(hass, entry)

    assert await coordinator._async_update_data() == {
        "values": {"air_temperature": 15.4}
    }
    assert await coordinator._async_update_data() == {
        "values": {"air_temperature": 15.4}
    }
    assert session.headers == [{}, {"If-None-Match": '"brandis-test"'}]
    assert parse_mock.call_count == 2
    assert parse_mock.call_args_list[1].args == (_payload(),)


async def test_geobox_coordinator_rejects_not_modified_without_cache(
    hass, mocker
):
    class _Response:
        status = 304
        headers = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class _Session:
        def get(self, *args, **kwargs):
            return _Response()

    mocker.patch(
        "custom_components.sensorbridge_partheland.geobox."
        "async_get_clientsession",
        return_value=_Session(),
    )
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    coordinator = GeoBoxBrandisCoordinator(hass, entry)

    with pytest.raises(UpdateFailed, match="304 ohne"):
        await coordinator._async_update_data()


async def test_removing_geobox_device_disables_and_stops_only_source(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_INCLUDE_GEOBOX_BRANDIS: True},
    )
    entry.add_to_hass(hass)
    coordinator = AsyncMock()
    other_coordinator = AsyncMock()
    hass.data[DOMAIN] = {
        SUPPLEMENTAL_COORDINATORS: {
            entry.entry_id: {
                GEOBOX_BRANDIS_SOURCE: coordinator,
                "dwd_pollen": other_coordinator,
            }
        }
    }

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, GEOBOX_BRANDIS_DEVICE_ID)},
        name="GeoBox Agrarwetter Brandis",
    )
    entity_registry = er.async_get(hass)
    entity = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "geobox:01038:air_temperature",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="geobox_brandis_lufttemperatur",
    )

    assert await async_remove_config_entry_device(hass, entry, device) is True

    assert entry.data[CONF_INCLUDE_GEOBOX_BRANDIS] is False
    coordinator.async_shutdown.assert_awaited_once_with()
    other_coordinator.async_shutdown.assert_not_awaited()
    assert (
        GEOBOX_BRANDIS_SOURCE
        not in hass.data[DOMAIN][SUPPLEMENTAL_COORDINATORS][entry.entry_id]
    )
    assert entity_registry.async_get(entity.entity_id) is None
