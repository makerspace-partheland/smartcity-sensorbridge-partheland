from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from unittest.mock import AsyncMock
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sensorbridge_partheland import (
    async_remove_config_entry_device,
)
from custom_components.sensorbridge_partheland.const import (
    CONF_INCLUDE_DWD_PRECIPITATION_BRANDIS,
    DOMAIN,
    DWD_PRECIPITATION_STATIONS,
    SUPPLEMENTAL_COORDINATORS,
)
from custom_components.sensorbridge_partheland.precipitation import (
    DwdPrecipitationCoordinator,
    PrecipitationDataError,
    create_precipitation_entities,
    parse_dwd_precipitation,
)


def _archive(
    station_id: str = "07362",
    *,
    end: datetime = datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
    count: int = 180,
    missing_index: int | None = None,
    filename: str = "produkt_5min_now_rr_20260723_20260723_07362.txt",
) -> bytes:
    rows = [
        "STATIONS_ID;MESS_DATUM;QN_5min;RS_COUNT_05;RS_IND_05;RS_05;eor"
    ]
    start = end - timedelta(minutes=5 * (count - 1))
    for index in range(count):
        if index == missing_index:
            continue
        timestamp = start + timedelta(minutes=5 * index)
        rows.append(
            f"{station_id.lstrip('0')};{timestamp:%Y%m%d%H%M};1;5;-999;0.1;eor"
        )
    payload = "\n".join(rows).encode()
    target = BytesIO()
    with ZipFile(target, "w", ZIP_DEFLATED) as zipped:
        zipped.writestr(filename, payload)
    return target.getvalue()


def test_parse_dwd_precipitation_aggregates_hour_and_local_day():
    parsed = parse_dwd_precipitation(
        _archive(),
        "07362",
        now=datetime(2026, 7, 23, 12, 4, tzinfo=UTC),
    )

    assert parsed["last_hour"] == 1.2
    assert parsed["today"] == 16.8
    assert parsed["last_measurement"] == datetime(
        2026, 7, 23, 12, 0, tzinfo=UTC
    )
    assert parsed["last_reset"].isoformat() == "2026-07-23T00:00:00+02:00"


@pytest.mark.parametrize(
    ("missing_index", "missing_period"),
    [
        (175, "last_hour"),
        (100, "today"),
    ],
)
def test_parse_dwd_precipitation_marks_incomplete_aggregates_unavailable(
    missing_index, missing_period
):
    parsed = parse_dwd_precipitation(
        _archive(missing_index=missing_index),
        "07362",
        now=datetime(2026, 7, 23, 12, 4, tzinfo=UTC),
    )
    assert parsed[missing_period] is None


def test_parse_dwd_precipitation_does_not_publish_yesterday_as_today():
    parsed = parse_dwd_precipitation(
        _archive(end=datetime(2026, 7, 23, 21, 55, tzinfo=UTC)),
        "07362",
        now=datetime(2026, 7, 23, 22, 30, tzinfo=UTC),
    )

    assert parsed["today"] is None
    assert parsed["last_reset"].isoformat() == "2026-07-24T00:00:00+02:00"


def test_parse_dwd_precipitation_requires_first_interval_after_midnight():
    parsed = parse_dwd_precipitation(
        _archive(missing_index=12),
        "07362",
        now=datetime(2026, 7, 23, 12, 4, tzinfo=UTC),
    )

    assert parsed["today"] is None


@pytest.mark.parametrize(
    ("archive", "now", "message"),
    [
        (
            _archive(),
            datetime(2026, 7, 23, 15, 1, tzinfo=UTC),
            "veraltet",
        ),
        (
            _archive(filename="../messwerte.txt"),
            datetime(2026, 7, 23, 12, 4, tzinfo=UTC),
            "unerwartete Datei",
        ),
    ],
)
def test_parse_dwd_precipitation_rejects_stale_or_unsafe_data(
    archive, now, message
):
    with pytest.raises(PrecipitationDataError, match=message):
        parse_dwd_precipitation(archive, "07362", now=now)


async def test_precipitation_entities_have_stable_identity_and_semantics(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    coordinator = DwdPrecipitationCoordinator(hass, entry, "07362")
    coordinator.async_set_updated_data(
        parse_dwd_precipitation(
            _archive(),
            "07362",
            now=datetime(2026, 7, 23, 12, 4, tzinfo=UTC),
        )
    )

    last_hour, today = create_precipitation_entities(coordinator)

    assert last_hour.unique_id == "dwd_precipitation:07362:last_hour"
    assert today.unique_id == "dwd_precipitation:07362:today"
    assert last_hour.device_class == SensorDeviceClass.PRECIPITATION
    assert last_hour.state_class is None
    assert today.state_class == SensorStateClass.TOTAL
    assert today.last_reset.isoformat() == "2026-07-23T00:00:00+02:00"
    assert last_hour.device_info["identifiers"] == {
        (DOMAIN, "supplemental:dwd_precipitation:07362")
    }
    assert last_hour.device_info["manufacturer"] == "Deutscher Wetterdienst"


async def test_coordinator_reparses_cached_archive_after_not_modified(
    hass, mocker
):
    archive = _archive()

    class _Content:
        async def iter_chunked(self, size):
            yield archive

    class _Response:
        def __init__(self, status):
            self.status = status
            self.content_length = len(archive) if status == 200 else 0
            self.content = _Content()
            self.headers = {"ETag": '"test"'}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        def raise_for_status(self):
            return None

    class _Session:
        def __init__(self):
            self.responses = iter((_Response(200), _Response(304)))

        def get(self, *args, **kwargs):
            return next(self.responses)

    parse_mock = mocker.patch(
        "custom_components.sensorbridge_partheland.precipitation."
        "parse_dwd_precipitation",
        side_effect=(
            {"last_hour": 1.0, "today": 2.0},
            {"last_hour": 1.0, "today": None},
        ),
    )
    mocker.patch(
        "custom_components.sensorbridge_partheland.precipitation."
        "async_get_clientsession",
        return_value=_Session(),
    )
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    coordinator = DwdPrecipitationCoordinator(hass, entry, "07362")

    assert await coordinator._async_update_data() == {
        "last_hour": 1.0,
        "today": 2.0,
    }
    assert await coordinator._async_update_data() == {
        "last_hour": 1.0,
        "today": None,
    }
    assert parse_mock.call_count == 2
    assert parse_mock.call_args_list[1].args == (archive, "07362")


async def test_removing_precipitation_device_disables_and_stops_only_source(hass):
    station = DWD_PRECIPITATION_STATIONS["07362"]
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_INCLUDE_DWD_PRECIPITATION_BRANDIS: True},
    )
    entry.add_to_hass(hass)
    coordinator = AsyncMock()
    other_coordinator = AsyncMock()
    hass.data[DOMAIN] = {
        SUPPLEMENTAL_COORDINATORS: {
            entry.entry_id: {
                station["source"]: coordinator,
                "dwd_pollen": other_coordinator,
            }
        }
    }

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, station["device_id"])},
        name="DWD Niederschlag Brandis",
    )
    entity_registry = er.async_get(hass)
    entity = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "dwd_precipitation:07362:last_hour",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="dwd_niederschlag_brandis_letzte_stunde",
    )

    assert await async_remove_config_entry_device(hass, entry, device) is True

    assert entry.data[CONF_INCLUDE_DWD_PRECIPITATION_BRANDIS] is False
    coordinator.async_shutdown.assert_awaited_once_with()
    other_coordinator.async_shutdown.assert_not_awaited()
    assert station["source"] not in (
        hass.data[DOMAIN][SUPPLEMENTAL_COORDINATORS][entry.entry_id]
    )
    assert entity_registry.async_get(entity.entity_id) is None
