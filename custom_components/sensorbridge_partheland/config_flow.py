"""Einrichtungs- und Optionsflow für SensorBridge Partheland."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .api_client import DeviceCatalogError
from .config_service import ConfigService
from .const import (
    ABORT_ALREADY_CONFIGURED,
    ABORT_NO_DEVICES,
    CONF_DEVICE_METADATA,
    CONF_SEARCH_TERM,
    CONF_SELECTED_DEVICES,
    CONF_SELECTED_MEDIAN_ENTITIES,
    CONFIG_ENTRY_VERSION,
    DOMAIN,
    ERROR_CANNOT_CONNECT,
    ERROR_NO_MATCHES,
    ERROR_NO_SELECTION,
    NAME,
)

_CONF_STATIONS = "stations"
_CONF_WATER_LEVEL = "water_level"
_CONF_TEMPERATURE_MOISTURE = "temperature_moisture"

_DEVICE_FIELDS = {
    _CONF_STATIONS: {"senseBox", "Unknown"},
    _CONF_WATER_LEVEL: {"WaterLevel"},
    _CONF_TEMPERATURE_MOISTURE: {"Temperature", "Moisture"},
}


class _AccumulatingSelectionFlow:
    """Gemeinsamer, kumulierender Auswahlablauf."""

    config_service: ConfigService | None
    _start_step_id: str

    def _init_selection_state(
        self,
        selected_devices: list[str] | None = None,
        selected_medians: list[str] | None = None,
    ) -> None:
        self.devices: dict[str, dict[str, Any]] = {}
        self.median_entities: dict[str, dict[str, Any]] = {}
        self.selected_devices = set(selected_devices or [])
        self.selected_medians = set(selected_medians or [])
        self.visible_devices: set[str] = set()
        self.visible_medians: set[str] = set()
        self.sensor_text = "Sensoren"

    async def _load_devices(self, existing_ids: list[str] | None = None) -> None:
        assert self.config_service is not None
        ui_text = await self.config_service.get_ui_text()
        self.sensor_text = ui_text.get("sensors", "Sensoren")
        self.devices.clear()
        self.median_entities.clear()

        grouped = await self.config_service.get_selection_candidates(existing_ids or [])
        for device_list in grouped.values():
            for device in device_list:
                device_id = device.get("id")
                if isinstance(device_id, str) and device_id:
                    self.devices[device_id] = dict(device)

        await self._load_medians()

    async def _load_existing_devices(self, existing_ids: list[str]) -> None:
        assert self.config_service is not None
        self.devices.clear()
        self.median_entities.clear()
        for device_id in existing_ids:
            device = await self.config_service.get_device_by_id(device_id)
            self.devices[device_id] = dict(
                device
                or {
                    "id": device_id,
                    "name": device_id,
                    "type": "Unknown",
                    "sensors": [],
                }
            )
        await self._load_medians()

    async def _load_medians(self) -> None:
        assert self.config_service is not None
        for entity in await self.config_service.get_median_entities():
            entity_id = entity.get("id")
            if isinstance(entity_id, str) and entity_id:
                self.median_entities[entity_id] = dict(entity)
        for entity_id in self.selected_medians - set(self.median_entities):
            self.median_entities[entity_id] = {
                "id": entity_id,
                "name": entity_id,
                "type": "median",
                "sensors": [],
            }

    async def async_step_search(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is None:
            return self._show_search_form()

        query = str(user_input.get(CONF_SEARCH_TERM, "")).strip().casefold()
        matching_devices = {
            device_id
            for device_id, device in self.devices.items()
            if _matches_query(device, query)
        }
        matching_medians = {
            entity_id
            for entity_id, entity in self.median_entities.items()
            if _matches_query(entity, query)
        }
        if not matching_devices and not matching_medians:
            return self._show_search_form(errors={"base": ERROR_NO_MATCHES})

        return self._show_device_selection_form(
            matching_devices,
            matching_medians,
        )

    async def async_step_all_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self._show_device_selection_form(
            set(self.devices),
            set(self.median_entities),
        )

    async def async_step_device_selection(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is None:
            return self._show_device_selection_form(
                self.visible_devices,
                self.visible_medians,
            )

        for field, device_types in _DEVICE_FIELDS.items():
            visible = {
                device_id
                for device_id in self.visible_devices
                if str(self.devices[device_id].get("type", "Unknown")) in device_types
            }
            selected = set(user_input.get(field, [])) & visible
            self.selected_devices.difference_update(visible)
            self.selected_devices.update(selected)

        other_visible = {
            device_id
            for device_id in self.visible_devices
            if not any(
                str(self.devices[device_id].get("type", "Unknown")) in types
                for types in _DEVICE_FIELDS.values()
            )
        }
        self.selected_devices.difference_update(other_visible)
        self.selected_devices.update(
            set(user_input.get(_CONF_STATIONS, [])) & other_visible
        )

        selected_medians = (
            set(user_input.get(CONF_SELECTED_MEDIAN_ENTITIES, []))
            & self.visible_medians
        )
        self.selected_medians.difference_update(self.visible_medians)
        self.selected_medians.update(selected_medians)
        return self._show_selection_menu()

    async def async_step_selection_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self._show_selection_menu()

    def _show_start_menu(self) -> FlowResult:
        return self.async_show_menu(
            step_id=self._start_step_id,
            menu_options=["search", "all_devices"],
        )

    def _show_selection_menu(self) -> FlowResult:
        return self.async_show_menu(
            step_id="selection_menu",
            menu_options=["search", "all_devices", "finish"],
            description_placeholders={
                "device_count": str(len(self.selected_devices)),
                "median_count": str(len(self.selected_medians)),
            },
        )

    def _show_search_form(self, errors: dict[str, str] | None = None) -> FlowResult:
        return self.async_show_form(
            step_id="search",
            data_schema=vol.Schema({vol.Required(CONF_SEARCH_TERM): TextSelector()}),
            errors=errors,
        )

    def _show_device_selection_form(
        self,
        visible_devices: set[str],
        visible_medians: set[str],
        errors: dict[str, str] | None = None,
    ) -> FlowResult:
        self.visible_devices = set(visible_devices)
        self.visible_medians = set(visible_medians)
        fields: dict[Any, SelectSelector] = {}

        for field, device_types in _DEVICE_FIELDS.items():
            options = {
                device_id: self.devices[device_id]
                for device_id in self.visible_devices
                if str(self.devices[device_id].get("type", "Unknown")) in device_types
            }
            if field == _CONF_STATIONS:
                options.update(
                    {
                        device_id: self.devices[device_id]
                        for device_id in self.visible_devices
                        if not any(
                            str(self.devices[device_id].get("type", "Unknown")) in types
                            for types in _DEVICE_FIELDS.values()
                        )
                    }
                )
            if options:
                fields[
                    vol.Optional(
                        field,
                        default=sorted(self.selected_devices & set(options)),
                    )
                ] = _multi_select(options, self.sensor_text)

        if self.visible_medians:
            medians = {
                entity_id: self.median_entities[entity_id]
                for entity_id in self.visible_medians
            }
            fields[
                vol.Optional(
                    CONF_SELECTED_MEDIAN_ENTITIES,
                    default=sorted(self.selected_medians & self.visible_medians),
                )
            ] = _multi_select(medians, self.sensor_text)

        return self.async_show_form(
            step_id="device_selection",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders={
                "result_count": str(
                    len(self.visible_devices) + len(self.visible_medians)
                ),
                "selected_count": str(
                    len(self.selected_devices) + len(self.selected_medians)
                ),
            },
        )


class ConfigFlow(
    _AccumulatingSelectionFlow,
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    """Konfiguriert SensorBridge Partheland."""

    VERSION = CONFIG_ENTRY_VERSION
    _start_step_id = "user"

    def __init__(self) -> None:
        self.config_service: ConfigService | None = None
        self._init_selection_state()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if self._async_current_entries():
            return self.async_abort(reason=ABORT_ALREADY_CONFIGURED)

        await self._async_initialize_config_service()
        if not self.config_service or not await self.config_service.validate_config():
            return self.async_abort(reason=ABORT_NO_DEVICES)

        try:
            await self._load_devices()
        except DeviceCatalogError:
            await self._load_medians()
            return self._show_device_selection_form(
                set(),
                set(self.median_entities),
                errors={"base": ERROR_CANNOT_CONNECT},
            )

        return self._show_start_menu()

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if not self.selected_devices and not self.selected_medians:
            return self._show_device_selection_form(
                set(self.devices),
                set(self.median_entities),
                errors={"base": ERROR_NO_SELECTION},
            )

        assert self.config_service is not None
        selected_devices = sorted(self.selected_devices)
        try:
            metadata = await self.config_service.snapshot_devices(selected_devices)
        except DeviceCatalogError:
            return self._show_device_selection_form(
                set(self.devices),
                set(self.median_entities),
                errors={"base": ERROR_CANNOT_CONNECT},
            )
        return self.async_create_entry(
            title=NAME,
            data={
                CONF_SELECTED_DEVICES: selected_devices,
                CONF_SELECTED_MEDIAN_ENTITIES: sorted(self.selected_medians),
                CONF_DEVICE_METADATA: metadata,
            },
        )

    async def _async_initialize_config_service(self) -> None:
        if self.config_service is None:
            self.config_service = ConfigService(self.hass)

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "OptionsFlowHandler":
        return OptionsFlowHandler()


class OptionsFlowHandler(
    _AccumulatingSelectionFlow,
    config_entries.OptionsFlow,
):
    """Ändert die Geräteauswahl ohne bestehende Einträge zu verlieren."""

    _start_step_id = "init"

    def __init__(self) -> None:
        self.config_service: ConfigService | None = None
        self._init_selection_state()

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        current_devices = list(self.config_entry.data.get(CONF_SELECTED_DEVICES, []))
        current_medians = list(
            self.config_entry.data.get(CONF_SELECTED_MEDIAN_ENTITIES, [])
        )
        self._init_selection_state(current_devices, current_medians)
        await self._async_initialize_config_service()
        assert self.config_service is not None
        self.config_service.register_entry_data(dict(self.config_entry.data))

        try:
            await self._load_devices(current_devices)
        except DeviceCatalogError:
            await self._load_existing_devices(current_devices)
            return self._show_device_selection_form(
                set(self.devices),
                set(self.median_entities),
                errors={"base": ERROR_CANNOT_CONNECT},
            )

        return self._show_start_menu()

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if not self.selected_devices and not self.selected_medians:
            return self._show_device_selection_form(
                set(self.devices),
                set(self.median_entities),
                errors={"base": ERROR_NO_SELECTION},
            )

        assert self.config_service is not None
        selected_devices = sorted(self.selected_devices)
        try:
            metadata = await self.config_service.snapshot_devices(selected_devices)
        except DeviceCatalogError:
            return self._show_device_selection_form(
                set(self.devices),
                set(self.median_entities),
                errors={"base": ERROR_CANNOT_CONNECT},
            )

        new_data = {
            **self.config_entry.data,
            CONF_SELECTED_DEVICES: selected_devices,
            CONF_SELECTED_MEDIAN_ENTITIES: sorted(self.selected_medians),
            CONF_DEVICE_METADATA: metadata,
        }
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
        await self.hass.config_entries.async_reload(self.config_entry.entry_id)
        return self.async_create_entry(title="", data={})

    async def _async_initialize_config_service(self) -> None:
        if self.config_service is None:
            self.config_service = ConfigService(self.hass)


def _matches_query(item: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    searchable = (
        item.get("id"),
        item.get("name"),
        item.get("type"),
        item.get("api_type"),
        item.get("location"),
    )
    return any(query in str(value).casefold() for value in searchable if value)


def _multi_select(
    options: dict[str, dict[str, Any]], sensor_text: str
) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(
                    value=device_id,
                    label=_option_label(device, sensor_text),
                )
                for device_id, device in sorted(
                    options.items(),
                    key=lambda item: (
                        str(item[1].get("name", "")).casefold(),
                        item[0],
                    ),
                )
            ],
            multiple=True,
            mode=SelectSelectorMode.LIST,
            custom_value=False,
        )
    )


def _option_label(item: dict[str, Any], sensor_text: str) -> str:
    item_id = str(item.get("id", ""))
    name = str(item.get("name") or item_id)
    identity = name if name == item_id else f"{name} · {item_id}"
    return f"{identity} ({len(item.get('sensors', []))} {sensor_text})"
