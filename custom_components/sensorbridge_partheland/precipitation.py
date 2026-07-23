"""DWD-Niederschlagsmessungen fester Stationen im Partheland."""

from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
from io import BytesIO, TextIOWrapper
import logging
import math
from typing import Any
from zipfile import BadZipFile, ZipFile
from zoneinfo import ZoneInfo

from aiohttp import ClientError, ClientTimeout
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPrecipitationDepth
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN, DWD_PRECIPITATION_STATIONS

_LOGGER = logging.getLogger(__name__)

_BERLIN = ZoneInfo("Europe/Berlin")
_MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
_MAX_UNCOMPRESSED_BYTES = 10 * 1024 * 1024
_STALE_AFTER = timedelta(hours=2)
_INTERVAL = timedelta(minutes=5)


class PrecipitationDataError(ValueError):
    """Die DWD-Datei entspricht nicht dem erwarteten Datenvertrag."""


def parse_dwd_precipitation(
    archive: bytes,
    station_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validiere und aggregiere eine DWD-5-Minuten-Niederschlagsdatei."""
    if station_id not in DWD_PRECIPITATION_STATIONS:
        raise PrecipitationDataError("Unbekannte DWD-Station")
    if not archive or len(archive) > _MAX_DOWNLOAD_BYTES:
        raise PrecipitationDataError("DWD-Niederschlagsdatei hat eine ungültige Größe")

    try:
        with ZipFile(BytesIO(archive)) as zipped:
            files = [item for item in zipped.infolist() if not item.is_dir()]
            if len(files) != 1:
                raise PrecipitationDataError(
                    "DWD-Niederschlagsarchiv enthält nicht genau eine Datei"
                )
            member = files[0]
            if (
                member.file_size > _MAX_UNCOMPRESSED_BYTES
                or member.flag_bits & 0x1
                or "/" in member.filename
                or "\\" in member.filename
                or not member.filename.startswith("produkt_5min_now_rr_")
                or not member.filename.endswith(".txt")
            ):
                raise PrecipitationDataError(
                    "DWD-Niederschlagsarchiv enthält eine unerwartete Datei"
                )
            with zipped.open(member) as raw:
                member_data = raw.read(_MAX_UNCOMPRESSED_BYTES + 1)
                if len(member_data) > _MAX_UNCOMPRESSED_BYTES:
                    raise PrecipitationDataError(
                        "DWD-Niederschlagsdatei ist entpackt zu groß"
                    )
                rows = _read_rows(member_data, station_id)
    except (BadZipFile, OSError, UnicodeError, csv.Error) as err:
        raise PrecipitationDataError(
            "DWD-Niederschlagsarchiv konnte nicht gelesen werden"
        ) from err

    if not rows:
        raise PrecipitationDataError("DWD-Niederschlagsdatei enthält keine Messwerte")

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise PrecipitationDataError("Aktuelle Zeit benötigt eine Zeitzone")
    latest_time = rows[-1][0]
    if current.astimezone(UTC) - latest_time > _STALE_AFTER:
        raise PrecipitationDataError("DWD-Niederschlagsdaten sind veraltet")
    if latest_time > current.astimezone(UTC):
        raise PrecipitationDataError("DWD-Niederschlagsdaten liegen in der Zukunft")

    last_hour_rows = rows[-12:]
    last_hour = (
        round(sum(value for _, value in last_hour_rows), 2)
        if len(last_hour_rows) == 12 and _is_contiguous(last_hour_rows)
        else None
    )

    local_now = current.astimezone(_BERLIN)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_utc = local_midnight.astimezone(UTC)
    today_rows = [row for row in rows if midnight_utc < row[0] <= latest_time]
    today = (
        round(sum(value for _, value in today_rows), 2)
        if (
            today_rows
            and today_rows[0][0] == midnight_utc + _INTERVAL
            and _is_contiguous(today_rows)
        )
        else None
    )

    return {
        "last_hour": last_hour,
        "today": today,
        "last_measurement": latest_time,
        "last_reset": local_midnight,
    }


def _read_rows(raw: bytes, station_id: str) -> list[tuple[datetime, float]]:
    text = TextIOWrapper(BytesIO(raw), encoding="utf-8-sig", newline="")
    reader = csv.DictReader(text, delimiter=";")
    expected = {
        "STATIONS_ID",
        "MESS_DATUM",
        "QN_5min",
        "RS_COUNT_05",
        "RS_IND_05",
        "RS_05",
        "eor",
    }
    if not reader.fieldnames or set(reader.fieldnames) != expected:
        raise PrecipitationDataError("DWD-Niederschlagsdatei hat unerwartete Spalten")

    rows: list[tuple[datetime, float]] = []
    for row in reader:
        if row["STATIONS_ID"].strip().lstrip("0") != station_id.lstrip("0"):
            continue
        try:
            count = int(row["RS_COUNT_05"])
            value = float(row["RS_05"])
            timestamp = datetime.strptime(
                row["MESS_DATUM"].strip(), "%Y%m%d%H%M"
            ).replace(tzinfo=UTC)
        except (TypeError, ValueError) as err:
            raise PrecipitationDataError(
                "DWD-Niederschlagsdatei enthält ungültige Messwerte"
            ) from err
        if count != 5 or value == -999:
            continue
        if value < 0 or not math.isfinite(value):
            raise PrecipitationDataError(
                "DWD-Niederschlagsdatei enthält ungültige Niederschlagswerte"
            )
        rows.append((timestamp, value))

    rows.sort(key=lambda item: item[0])
    if len({timestamp for timestamp, _ in rows}) != len(rows):
        raise PrecipitationDataError(
            "DWD-Niederschlagsdatei enthält doppelte Zeitstempel"
        )
    return rows


def _is_contiguous(rows: list[tuple[datetime, float]]) -> bool:
    return all(
        current[0] - previous[0] == _INTERVAL
        for previous, current in zip(rows, rows[1:], strict=False)
    )


class DwdPrecipitationCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Lädt eine feste DWD-Niederschlagsstation unabhängig von MQTT."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, station_id: str
    ) -> None:
        station = DWD_PRECIPITATION_STATIONS[station_id]
        super().__init__(
            hass,
            _LOGGER,
            name=f"DWD Niederschlag {station['name']}",
            update_interval=timedelta(minutes=15),
            config_entry=entry,
            always_update=False,
        )
        self.station_id = station_id
        self._url = station["url"]
        self._etag: str | None = None
        self._last_modified: str | None = None
        self._archive: bytes | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        headers = {}
        if self._etag:
            headers["If-None-Match"] = self._etag
        if self._last_modified:
            headers["If-Modified-Since"] = self._last_modified
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                self._url,
                headers=headers,
                timeout=ClientTimeout(total=15),
            ) as response:
                if response.status == 304 and self._archive is not None:
                    return await self.hass.async_add_executor_job(
                        parse_dwd_precipitation,
                        self._archive,
                        self.station_id,
                    )
                response.raise_for_status()
                archive = await _async_read_limited(response)
                etag = response.headers.get("ETag")
                last_modified = response.headers.get("Last-Modified")
            parsed = await self.hass.async_add_executor_job(
                parse_dwd_precipitation, archive, self.station_id
            )
            self._archive = archive
            self._etag = etag
            self._last_modified = last_modified
            return parsed
        except (
            ClientError,
            TimeoutError,
            PrecipitationDataError,
            ValueError,
        ) as err:
            raise UpdateFailed(
                f"DWD-Niederschlag {self.station_id} konnte nicht geladen werden: {err}"
            ) from err


async def _async_read_limited(response: Any) -> bytes:
    content_length = response.content_length
    if content_length is not None and content_length > _MAX_DOWNLOAD_BYTES:
        raise PrecipitationDataError("DWD-Niederschlagsdatei ist zu groß")
    chunks = bytearray()
    async for chunk in response.content.iter_chunked(64 * 1024):
        chunks.extend(chunk)
        if len(chunks) > _MAX_DOWNLOAD_BYTES:
            raise PrecipitationDataError("DWD-Niederschlagsdatei ist zu groß")
    return bytes(chunks)


def create_precipitation_entities(
    coordinator: DwdPrecipitationCoordinator,
) -> list[DwdPrecipitationSensor]:
    """Erzeuge Stunden- und Tagessumme einer DWD-Station."""
    return [
        DwdPrecipitationSensor(coordinator, "last_hour"),
        DwdPrecipitationSensor(coordinator, "today"),
    ]


class DwdPrecipitationSensor(
    CoordinatorEntity[DwdPrecipitationCoordinator],
    SensorEntity,
):
    """Niederschlagssumme einer festen DWD-Station."""

    _attr_attribution = "Datenbasis: Deutscher Wetterdienst"
    _attr_device_class = SensorDeviceClass.PRECIPITATION
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        coordinator: DwdPrecipitationCoordinator,
        period: str,
    ) -> None:
        super().__init__(coordinator)
        station = DWD_PRECIPITATION_STATIONS[coordinator.station_id]
        self._period = period
        self._attr_unique_id = (
            f"dwd_precipitation:{coordinator.station_id}:{period}"
        )
        self._attr_translation_key = f"precipitation_{period}"
        self._attr_state_class = (
            SensorStateClass.TOTAL if period == "today" else None
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, station["device_id"])},
            name=f"DWD Niederschlag {station['name']}",
            manufacturer="Deutscher Wetterdienst",
            model="5-Minuten-Niederschlag",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=station["url"],
        )

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        return data.get(self._period) if data else None

    @property
    def available(self) -> bool:
        return (
            super().available
            and bool(self.coordinator.data)
            and self.coordinator.data.get(self._period) is not None
        )

    @property
    def last_reset(self) -> datetime | None:
        if self._period != "today" or not self.coordinator.data:
            return None
        return self.coordinator.data["last_reset"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if not data:
            return {}
        return {"last_measurement": data["last_measurement"]}
