from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.sensorbridge_partheland.api_client import (
    DeviceCatalogClient,
    DeviceCatalogError,
    filter_selection_candidates,
)
from custom_components.sensorbridge_partheland.const import DEVICE_API_URL


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def json(self, content_type=None):
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


@pytest.mark.asyncio
async def test_catalog_normalizes_device_and_sensor_metadata():
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "mspl-example",
                "geometry": {
                    "type": "Point",
                    "coordinates": [12.5866, 51.2831],
                },
                "properties": {
                    "name": "sensebox-naunhof",
                    "type": "SenseBoxDevice",
                    "status": "online",
                    "last_seen": "2026-07-22T14:49:53.993Z",
                    "attributes": {
                        "measurement": "Naunhof_Nr1",
                        "displayname": "Naunhof Nr 1",
                        "active": "true",
                        "locationtype": "field",
                        "operationalstatus": "defective",
                        "osm": "https://opensensemap.org/example",
                        "mspl": "https://sensoren.makerspace-partheland.de/example",
                    },
                    "measurements": {
                        "temperature": {
                            "value": 20.8,
                            "unit": "CEL",
                        }
                    },
                },
            }
        ],
    }
    session = FakeSession(FakeResponse(payload))

    devices = await DeviceCatalogClient(session).async_get_devices()

    assert session.calls[0][0] == DEVICE_API_URL
    assert devices == [
        {
            "id": "Naunhof_Nr1",
            "name": "Naunhof Nr 1",
            "type": "senseBox",
            "api_type": "SenseBoxDevice",
            "api_id": "mspl-example",
            "status": "online",
            "last_seen": "2026-07-22T14:49:53.993Z",
            "active": "true",
            "location_type": "field",
            "operationalstatus": "defective",
            "external_urls": {
                "openSenseMap": "https://opensensemap.org/example",
                "makerspace": "https://sensoren.makerspace-partheland.de/example",
            },
            "sensors": ["temperature"],
            "sensor_metadata": {"temperature": {"unit": "CEL"}},
            "topic_pattern": "senseBox:home/Naunhof_Nr1",
            "longitude": 12.5866,
            "latitude": 51.2831,
        }
    ]
    assert "measurements" not in devices[0]
    assert "value" not in devices[0]["sensor_metadata"]["temperature"]


@pytest.mark.asyncio
async def test_catalog_rejects_duplicate_measurement_ids():
    feature = {
        "type": "Feature",
        "properties": {
            "type": "SenseBoxDevice",
            "attributes": {
                "measurement": "Naunhof_Nr1",
                "displayname": "Naunhof Nr 1",
            },
        },
    }
    session = FakeSession(
        FakeResponse(
            {
                "type": "FeatureCollection",
                "features": [feature, feature],
            }
        )
    )

    with pytest.raises(DeviceCatalogError, match="Geräte-ID mehrfach"):
        await DeviceCatalogClient(session).async_get_devices()


@pytest.mark.asyncio
async def test_catalog_rejects_http_errors():
    session = FakeSession(FakeResponse({}, status=503))

    with pytest.raises(DeviceCatalogError, match="HTTP 503"):
        await DeviceCatalogClient(session).async_get_devices()


def test_selection_filter_uses_raw_operationalstatus_and_recent_last_seen():
    now = datetime(2026, 7, 22, 15, 0, tzinfo=UTC)
    devices = [
        {
            "id": "recent",
            "last_seen": "2026-07-01T00:00:00Z",
            "operationalstatus": None,
        },
        {
            "id": "recent_defective",
            "last_seen": "2026-07-20T00:00:00Z",
            "operationalstatus": "defective",
        },
        {
            "id": "planned",
            "last_seen": "2026-07-20T00:00:00Z",
            "operationalstatus": "planned",
        },
        {
            "id": "old",
            "last_seen": "2026-06-01T00:00:00Z",
            "operationalstatus": None,
        },
        {
            "id": "invalid",
            "last_seen": "kein-zeitstempel",
            "operationalstatus": None,
        },
        {
            "id": "missing",
            "last_seen": None,
            "operationalstatus": None,
        },
    ]

    candidates = filter_selection_candidates(devices, now_utc=now)

    assert [device["id"] for device in candidates] == [
        "recent",
    ]


def test_selection_filter_excludes_new_offline_device():
    now = datetime(2026, 7, 22, 15, 0, tzinfo=UTC)
    devices = [
        {
            "id": "online",
            "status": "online",
            "last_seen": "2026-07-20T00:00:00Z",
            "operationalstatus": None,
        },
        {
            "id": "offline",
            "status": "offline",
            "last_seen": "2026-07-20T00:00:00Z",
            "operationalstatus": None,
        },
    ]

    candidates = filter_selection_candidates(devices, now_utc=now)

    assert [device["id"] for device in candidates] == ["online"]


def test_selection_filter_preserves_existing_ids_without_exposing_them_as_new():
    now = datetime(2026, 7, 22, 15, 0, tzinfo=UTC)
    devices = [
        {
            "id": "planned",
            "last_seen": "2024-11-15T16:53:45.592Z",
            "operationalstatus": "planned",
        },
        {
            "id": "missing_last_seen",
            "last_seen": None,
            "operationalstatus": None,
        },
        {
            "id": "defective",
            "last_seen": "2026-07-20T00:00:00Z",
            "operationalstatus": "defective",
        },
        {
            "id": "offline",
            "status": "offline",
            "last_seen": "2026-07-20T00:00:00Z",
            "operationalstatus": None,
        },
    ]

    candidates = filter_selection_candidates(
        devices,
        existing_ids={"planned", "missing_last_seen", "defective", "offline"},
        now_utc=now,
    )

    assert [device["id"] for device in candidates] == [
        "planned",
        "missing_last_seen",
        "defective",
        "offline",
    ]
