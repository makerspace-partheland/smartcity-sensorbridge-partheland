"""DWD-Pollenflugvorhersage für das Tiefland Sachsen."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from aiohttp import ClientError, ClientTimeout
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    DOMAIN,
    DWD_POLLEN_DEVICE_ID,
    DWD_POLLEN_URL,
)

_LOGGER = logging.getLogger(__name__)

_REGION_ID = 80
_PARTREGION_ID = 81
_BERLIN = ZoneInfo("Europe/Berlin")
_STALE_GRACE = timedelta(hours=6)
_POLLEN_LEVELS = {
    "0": "none",
    "0-1": "none_to_low",
    "1": "low",
    "1-2": "low_to_medium",
    "2": "medium",
    "2-3": "medium_to_high",
    "3": "high",
}
POLLEN_OPTIONS = list(_POLLEN_LEVELS.values())
POLLEN_SPECIES = {
    "hazel": "Hasel",
    "alder": "Erle",
    "ash": "Esche",
    "birch": "Birke",
    "grasses": "Graeser",
    "rye": "Roggen",
    "mugwort": "Beifuss",
    "ragweed": "Ambrosia",
}


class PollenDataError(ValueError):
    """Die DWD-Antwort entspricht nicht dem erwarteten Datenvertrag."""


def parse_dwd_pollen(
    payload: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Normalisiere die DWD-Pollenflugvorhersage für Teilregion 81."""
    if not isinstance(payload, dict) or not isinstance(payload.get("content"), list):
        raise PollenDataError("DWD-Polleninhalt fehlt")

    region = next(
        (
            item
            for item in payload["content"]
            if isinstance(item, dict)
            and item.get("region_id") == _REGION_ID
            and item.get("partregion_id") == _PARTREGION_ID
        ),
        None,
    )
    if region is None or not isinstance(region.get("Pollen"), dict):
        raise PollenDataError("DWD-Pollen-Teilregion 81 fehlt")

    last_update = _parse_dwd_datetime(payload.get("last_update"))
    next_update = _parse_dwd_datetime(payload.get("next_update"))
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise PollenDataError("Aktuelle Zeit benötigt eine Zeitzone")
    if current.astimezone(_BERLIN) > next_update + _STALE_GRACE:
        raise PollenDataError("DWD-Pollenflugvorhersage ist veraltet")

    species: dict[str, dict[str, str | None]] = {}
    pollen = region["Pollen"]
    for species_key, dwd_key in POLLEN_SPECIES.items():
        forecast = pollen.get(dwd_key)
        if not isinstance(forecast, dict):
            raise PollenDataError(f"DWD-Pollenart fehlt: {dwd_key}")

        values: dict[str, str | None] = {}
        for period in ("today", "tomorrow", "dayafter_to"):
            raw = forecast.get(period)
            if not isinstance(raw, str):
                raise PollenDataError(
                    f"Ungültiger DWD-Pollenwert für {dwd_key}/{period}"
                )
            if raw == "-1":
                values[period] = None
            elif raw in _POLLEN_LEVELS:
                values[period] = _POLLEN_LEVELS[raw]
            else:
                raise PollenDataError(
                    f"Unbekannter DWD-Pollenwert für {dwd_key}/{period}: {raw}"
                )
            values[f"{period}_raw"] = raw
        species[species_key] = values

    return {
        "last_update": last_update.isoformat(),
        "next_update": next_update.isoformat(),
        "species": species,
    }


def _parse_dwd_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise PollenDataError("DWD-Aktualisierungszeit fehlt")
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M Uhr").replace(tzinfo=_BERLIN)
    except ValueError as err:
        raise PollenDataError("Ungültige DWD-Aktualisierungszeit") from err


class DwdPollenCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Lädt die DWD-Pollenflugvorhersage unabhängig von MQTT."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="DWD Pollenflug Tiefland Sachsen",
            update_interval=timedelta(hours=1),
            config_entry=entry,
            always_update=False,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                DWD_POLLEN_URL,
                timeout=ClientTimeout(total=10),
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
            return parse_dwd_pollen(payload)
        except (ClientError, TimeoutError, PollenDataError, ValueError) as err:
            raise UpdateFailed(
                f"DWD-Pollenflug konnte nicht geladen werden: {err}"
            ) from err


def create_pollen_entities(
    coordinator: DwdPollenCoordinator,
) -> list[DwdPollenSensor]:
    """Erzeuge die acht Pollenflug-Entitäten."""
    return [DwdPollenSensor(coordinator, species_key) for species_key in POLLEN_SPECIES]


class DwdPollenSensor(
    CoordinatorEntity[DwdPollenCoordinator],
    SensorEntity,
):
    """Pollenflugvorhersage einer Art."""

    _attr_attribution = "Datenbasis: Deutscher Wetterdienst"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_has_entity_name = True
    _attr_icon = "mdi:flower-pollen"
    _attr_options = POLLEN_OPTIONS

    def __init__(
        self,
        coordinator: DwdPollenCoordinator,
        species_key: str,
    ) -> None:
        super().__init__(coordinator)
        self._species_key = species_key
        self._attr_unique_id = f"dwd_pollen:81:{species_key}"
        self._attr_translation_key = f"pollen_{species_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, DWD_POLLEN_DEVICE_ID)},
            name="DWD Pollenflug Tiefland Sachsen",
            manufacturer="Deutscher Wetterdienst",
            model="Pollenflug-Gefahrenindex",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=DWD_POLLEN_URL,
        )

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        if not data:
            return None
        return data["species"][self._species_key]["today"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if not data:
            return {}
        forecast = data["species"][self._species_key]
        return {
            "level_raw": forecast["today_raw"],
            "tomorrow": forecast["tomorrow_raw"],
            "day_after_tomorrow": forecast["dayafter_to_raw"],
            "last_update": data["last_update"],
            "next_update": data["next_update"],
        }
