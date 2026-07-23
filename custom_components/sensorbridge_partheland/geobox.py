"""Öffentliche Agrarwetterdaten der GeoBox-Station Brandis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
import math
from typing import Any
from zoneinfo import ZoneInfo

from aiohttp import ClientError, ClientTimeout
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfPrecipitationDepth,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    DOMAIN,
    GEOBOX_BRANDIS_DEVICE_ID,
    GEOBOX_BRANDIS_URL,
)

_LOGGER = logging.getLogger(__name__)

_BERLIN = ZoneInfo("Europe/Berlin")
_STATION_ID = "01038"
_STALE_AFTER = timedelta(hours=3)
_FUTURE_TOLERANCE = timedelta(minutes=15)
_OUT_FIELDS = (
    "de_id,de_label,de_lng,de_lat,de_datetime,de_ta200,de_prec,"
    "de_prec_sum,de_rh200,de_gr200,de_wv200"
)


class GeoBoxDataError(ValueError):
    """Die GeoBox-Antwort entspricht nicht dem erwarteten Datenvertrag."""


def parse_geobox_brandis(
    payload: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validiere und normalisiere den aktuellen Datensatz der Station 01038."""
    if not isinstance(payload, dict) or payload.get("error"):
        raise GeoBoxDataError("GeoBox-Antwort ist ungültig")
    features = payload.get("features")
    if not isinstance(features, list) or len(features) != 1:
        raise GeoBoxDataError(
            "GeoBox-Station 01038 fehlt oder ist nicht eindeutig"
        )
    feature = features[0]
    attributes = (
        feature.get("attributes") if isinstance(feature, dict) else None
    )
    if (
        not isinstance(attributes, dict)
        or attributes.get("de_id") != _STATION_ID
    ):
        raise GeoBoxDataError("GeoBox-Station 01038 fehlt")

    label = attributes.get("de_label")
    if not isinstance(label, str) or not label.strip():
        raise GeoBoxDataError("GeoBox-Stationsname fehlt")
    latitude = _required_number(attributes.get("de_lat"), "Breitengrad")
    longitude = _required_number(attributes.get("de_lng"), "Längengrad")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise GeoBoxDataError("GeoBox-Koordinaten sind ungültig")

    raw_timestamp = attributes.get("de_datetime")
    if (
        isinstance(raw_timestamp, bool)
        or not isinstance(raw_timestamp, (int, float))
        or not math.isfinite(raw_timestamp)
    ):
        raise GeoBoxDataError("GeoBox-Messzeit fehlt")
    measurement_time = datetime.fromtimestamp(raw_timestamp / 1000, tz=UTC)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise GeoBoxDataError("Aktuelle Zeit benötigt eine Zeitzone")
    current_utc = current.astimezone(UTC)
    if current_utc - measurement_time > _STALE_AFTER:
        raise GeoBoxDataError("GeoBox-Daten sind veraltet")
    if measurement_time - current_utc > _FUTURE_TOLERANCE:
        raise GeoBoxDataError("GeoBox-Messzeit liegt in der Zukunft")

    local_now = current.astimezone(_BERLIN)
    local_midnight = local_now.replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    same_local_day = (
        measurement_time.astimezone(_BERLIN).date() == local_now.date()
    )

    values = {
        "air_temperature": _optional_number(
            attributes.get("de_ta200"), "Lufttemperatur"
        ),
        "precipitation_last_hour": _optional_nonnegative(
            attributes.get("de_prec"), "Niederschlag letzte Stunde"
        ),
        "precipitation_today": (
            _optional_nonnegative(
                attributes.get("de_prec_sum"), "Tagesniederschlag"
            )
            if same_local_day
            else None
        ),
        "relative_humidity": _optional_number(
            attributes.get("de_rh200"), "Relative Luftfeuchte"
        ),
        "solar_radiation_last_hour": _optional_nonnegative(
            attributes.get("de_gr200"), "Globalstrahlung letzte Stunde"
        ),
        "wind_speed": _optional_nonnegative(
            attributes.get("de_wv200"), "Windgeschwindigkeit"
        ),
    }
    humidity = values["relative_humidity"]
    if humidity is not None and not 0 <= humidity <= 100:
        raise GeoBoxDataError("GeoBox-Luftfeuchte ist ungültig")

    return {
        "station_id": _STATION_ID,
        "label": label.strip(),
        "latitude": latitude,
        "longitude": longitude,
        "measurement_time": measurement_time,
        "last_reset": local_midnight,
        "values": values,
    }


def _required_number(value: Any, label: str) -> float:
    parsed = _optional_number(value, label)
    if parsed is None:
        raise GeoBoxDataError(f"GeoBox-{label} fehlt")
    return parsed


def _optional_number(value: Any, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GeoBoxDataError(f"GeoBox-{label} ist ungültig")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise GeoBoxDataError(f"GeoBox-{label} ist ungültig")
    return parsed


def _optional_nonnegative(value: Any, label: str) -> float | None:
    parsed = _optional_number(value, label)
    if parsed is not None and parsed < 0:
        raise GeoBoxDataError(f"GeoBox-{label} ist ungültig")
    return parsed


class GeoBoxBrandisCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Lädt die öffentliche GeoBox-Station Brandis unabhängig von MQTT."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="GeoBox Agrarwetter Brandis",
            update_interval=timedelta(minutes=15),
            config_entry=entry,
            always_update=False,
        )
        self._etag: str | None = None
        self._payload: Any = None

    async def _async_update_data(self) -> dict[str, Any]:
        headers = {"If-None-Match": self._etag} if self._etag else {}
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                GEOBOX_BRANDIS_URL,
                headers=headers,
                params={
                    "where": f"de_id='{_STATION_ID}'",
                    "outFields": _OUT_FIELDS,
                    "returnGeometry": "false",
                    "f": "json",
                },
                timeout=ClientTimeout(total=15),
            ) as response:
                if response.status == 304:
                    if self._payload is None:
                        raise GeoBoxDataError(
                            "GeoBox-Antwort 304 ohne Cache"
                        )
                    return parse_geobox_brandis(self._payload)
                response.raise_for_status()
                payload = await response.json(content_type=None)
                etag = response.headers.get("ETag")
            parsed = parse_geobox_brandis(payload)
            self._payload = payload
            self._etag = etag
            return parsed
        except (
            ClientError,
            TimeoutError,
            GeoBoxDataError,
            ValueError,
        ) as err:
            raise UpdateFailed(
                f"GeoBox-Station Brandis konnte nicht geladen werden: {err}"
            ) from err


@dataclass(frozen=True)
class GeoBoxSensorDescription:
    key: str
    device_class: SensorDeviceClass | None
    unit: str | None = None
    state_class: SensorStateClass | None = None
    diagnostic: bool = False


_SENSORS = (
    GeoBoxSensorDescription(
        "air_temperature",
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
        SensorStateClass.MEASUREMENT,
    ),
    GeoBoxSensorDescription(
        "relative_humidity",
        SensorDeviceClass.HUMIDITY,
        PERCENTAGE,
        SensorStateClass.MEASUREMENT,
    ),
    GeoBoxSensorDescription(
        "precipitation_last_hour",
        SensorDeviceClass.PRECIPITATION,
        UnitOfPrecipitationDepth.MILLIMETERS,
        SensorStateClass.MEASUREMENT,
    ),
    GeoBoxSensorDescription(
        "precipitation_today",
        SensorDeviceClass.PRECIPITATION,
        UnitOfPrecipitationDepth.MILLIMETERS,
        SensorStateClass.TOTAL,
    ),
    # de_gr200 ist die Energie der abgeschlossenen Stunde, keine Irradiance.
    GeoBoxSensorDescription(
        "solar_radiation_last_hour",
        None,
        "Wh/m²",
    ),
    GeoBoxSensorDescription(
        "wind_speed",
        SensorDeviceClass.WIND_SPEED,
        UnitOfSpeed.METERS_PER_SECOND,
        SensorStateClass.MEASUREMENT,
    ),
    GeoBoxSensorDescription(
        "measurement_time",
        SensorDeviceClass.TIMESTAMP,
        diagnostic=True,
    ),
)


def create_geobox_entities(
    coordinator: GeoBoxBrandisCoordinator,
) -> list[GeoBoxBrandisSensor]:
    """Erzeuge die sieben Entitäten der öffentlichen Wetterstation."""
    return [
        GeoBoxBrandisSensor(coordinator, description)
        for description in _SENSORS
    ]


class GeoBoxBrandisSensor(
    CoordinatorEntity[GeoBoxBrandisCoordinator],
    SensorEntity,
):
    """Messwert der öffentlichen GeoBox-Station Brandis."""

    _attr_attribution = "Datenbasis: LfULG Sachsen / GeoBox"
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GeoBoxBrandisCoordinator,
        description: GeoBoxSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._description = description
        self._attr_unique_id = f"geobox:01038:{description.key}"
        self._attr_translation_key = f"geobox_{description.key}"
        self._attr_device_class = description.device_class
        self._attr_native_unit_of_measurement = description.unit
        self._attr_state_class = description.state_class
        self._attr_suggested_display_precision = (
            1 if description.unit is not None else None
        )
        self._attr_entity_category = (
            EntityCategory.DIAGNOSTIC if description.diagnostic else None
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, GEOBOX_BRANDIS_DEVICE_ID)},
            name="GeoBox Agrarwetter Brandis",
            manufacturer="LfULG Sachsen",
            model="Agrarmeteorologische Wetterstation",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=GEOBOX_BRANDIS_URL,
        )

    @property
    def native_value(self) -> float | datetime | None:
        data = self.coordinator.data
        if not data:
            return None
        if self._description.key == "measurement_time":
            return data["measurement_time"]
        return data["values"].get(self._description.key)

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    @property
    def last_reset(self) -> datetime | None:
        if (
            self._description.key != "precipitation_today"
            or not self.coordinator.data
        ):
            return None
        return self.coordinator.data["last_reset"]
