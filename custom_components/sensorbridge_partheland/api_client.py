from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import Any, Iterable

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import DEFAULT_TIMEOUT, DEVICE_API_URL

DEVICE_TYPE_MAP = {
    "SenseBoxDevice": "senseBox",
    "TemperatureDevice": "Temperature",
    "WaterLevelDevice": "WaterLevel",
    "MoistureDevice": "Moisture",
}
UNSELECTABLE_OPERATIONAL_STATUSES = {"planned", "defective"}


class DeviceCatalogError(RuntimeError):
    pass


class DeviceCatalogClient:
    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def async_get_devices(self) -> list[dict[str, Any]]:
        try:
            async with self._session.get(
                DEVICE_API_URL,
                timeout=ClientTimeout(total=DEFAULT_TIMEOUT),
            ) as response:
                if response.status != HTTPStatus.OK:
                    raise DeviceCatalogError(
                        f"Gerätekatalog antwortet mit HTTP {response.status}"
                    )
                payload = await response.json(content_type=None)
        except DeviceCatalogError:
            raise
        except (ClientError, asyncio.TimeoutError, ValueError, TypeError) as error:
            raise DeviceCatalogError(
                "Gerätekatalog konnte nicht geladen werden"
            ) from error

        return self._normalize_catalog(payload)

    @staticmethod
    def _normalize_catalog(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
            raise DeviceCatalogError("Gerätekatalog ist kein gültiges GeoJSON")

        features = payload.get("features")
        if not isinstance(features, list):
            raise DeviceCatalogError("Gerätekatalog enthält keine Feature-Liste")

        devices: list[dict[str, Any]] = []
        device_ids: set[str] = set()

        for feature in features:
            if not isinstance(feature, dict):
                continue

            properties = feature.get("properties")
            if not isinstance(properties, dict):
                continue

            attributes = properties.get("attributes")
            if not isinstance(attributes, dict):
                continue

            device_id = attributes.get("measurement")
            if not isinstance(device_id, str) or not device_id:
                continue
            if device_id in device_ids:
                raise DeviceCatalogError(
                    f"Gerätekatalog enthält die Geräte-ID mehrfach: {device_id}"
                )

            api_type = properties.get("type")
            if not isinstance(api_type, str) or api_type not in DEVICE_TYPE_MAP:
                continue

            device_type = DEVICE_TYPE_MAP[api_type]

            name = attributes.get("displayname") or properties.get("name") or device_id
            external_urls = {
                key: value
                for key, value in {
                    "openSenseMap": attributes.get("osm"),
                    "makerspace": attributes.get("mspl"),
                }.items()
                if isinstance(value, str) and value
            }

            measurements = properties.get("measurements")
            sensor_metadata: dict[str, dict[str, Any]] = {}
            if isinstance(measurements, dict):
                for sensor_name, sensor_data in measurements.items():
                    if not isinstance(sensor_name, str) or not sensor_name:
                        continue
                    metadata: dict[str, Any] = {}
                    if isinstance(sensor_data, dict) and isinstance(
                        sensor_data.get("unit"), str
                    ):
                        metadata["unit"] = sensor_data["unit"]
                    sensor_metadata[sensor_name] = metadata

            device: dict[str, Any] = {
                "id": device_id,
                "name": str(name),
                "type": device_type,
                "api_type": api_type,
                "api_id": feature.get("id"),
                "status": properties.get("status"),
                "last_seen": properties.get("last_seen"),
                "active": attributes.get("active"),
                "location_type": attributes.get("locationtype"),
                "operationalstatus": attributes.get("operationalstatus"),
                "external_urls": external_urls,
                "sensors": sorted(sensor_metadata),
                "sensor_metadata": sensor_metadata,
                "topic_pattern": (
                    f"senseBox:home/{device_id}"
                    if device_type == "senseBox"
                    else f"sensoren/{device_id}"
                ),
            }

            geometry = feature.get("geometry")
            if isinstance(geometry, dict) and geometry.get("type") == "Point":
                coordinates = geometry.get("coordinates")
                if (
                    isinstance(coordinates, list)
                    and len(coordinates) >= 2
                    and all(
                        isinstance(value, (int, float)) for value in coordinates[:2]
                    )
                ):
                    device["longitude"] = coordinates[0]
                    device["latitude"] = coordinates[1]

            devices.append(device)
            device_ids.add(device_id)

        if not devices:
            raise DeviceCatalogError("Gerätekatalog enthält keine nutzbaren Geräte")

        return sorted(devices, key=lambda item: (item["name"].casefold(), item["id"]))


def filter_selection_candidates(
    devices: Iterable[dict[str, Any]],
    existing_ids: Iterable[str] = (),
    now_utc: datetime | None = None,
) -> list[dict[str, Any]]:
    selected_ids = set(existing_ids)
    now = now_utc or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("now_utc muss eine Zeitzone enthalten")
    cutoff = now.astimezone(UTC) - timedelta(days=30)

    candidates: list[dict[str, Any]] = []
    for device in devices:
        device_id = device.get("id")
        if device_id in selected_ids:
            candidates.append(device)
            continue

        if device.get("operationalstatus") in UNSELECTABLE_OPERATIONAL_STATUSES:
            continue

        last_seen = _parse_last_seen(device.get("last_seen"))
        if last_seen is None or last_seen < cutoff:
            continue

        candidates.append(device)

    return candidates


def _parse_last_seen(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)
