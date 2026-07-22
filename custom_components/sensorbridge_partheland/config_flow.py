"""Einrichtungs- und Optionsflow für SensorBridge Partheland."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api_client import DeviceCatalogError
from .config_service import ConfigService
from .const import (
    ABORT_ALREADY_CONFIGURED,
    ABORT_NO_DEVICES,
    CONF_DEVICE_METADATA,
    CONF_SELECTED_DEVICES,
    CONF_SELECTED_MEDIAN_ENTITIES,
    DOMAIN,
    ERROR_CANNOT_CONNECT,
    ERROR_NO_SELECTION,
    NAME,
)

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Konfiguriert SensorBridge Partheland."""

    VERSION = 2

    def __init__(self) -> None:
        self.config_service: ConfigService | None = None
        self.devices: dict[str, str] = {}
        self.median_entities: dict[str, str] = {}

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
            return self._show_device_selection_form(
                errors={"base": ERROR_CANNOT_CONNECT}
            )

        return await self.async_step_device_selection()

    async def async_step_device_selection(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is None:
            return self._show_device_selection_form()

        selected_devices = list(user_input.get(CONF_SELECTED_DEVICES, []))
        selected_medians = list(user_input.get(CONF_SELECTED_MEDIAN_ENTITIES, []))
        if not selected_devices and not selected_medians:
            return self._show_device_selection_form(
                errors={"base": ERROR_NO_SELECTION}
            )

        assert self.config_service is not None
        metadata = await self.config_service.snapshot_devices(selected_devices)
        return self.async_create_entry(
            title=NAME,
            data={
                CONF_SELECTED_DEVICES: selected_devices,
                CONF_SELECTED_MEDIAN_ENTITIES: selected_medians,
                CONF_DEVICE_METADATA: metadata,
            },
        )

    async def _async_initialize_config_service(self) -> None:
        if self.config_service is None:
            self.config_service = ConfigService(self.hass)

    async def _load_devices(self, existing_ids: list[str] | None = None) -> None:
        assert self.config_service is not None
        self.devices.clear()
        self.median_entities.clear()
        ui_text = await self.config_service.get_ui_text()
        sensor_text = ui_text.get("sensors", "Sensoren")

        for entity in await self.config_service.get_median_entities():
            entity_id = entity.get("id")
            if not entity_id:
                continue
            name = str(entity.get("name") or entity_id)
            display_name = name.removeprefix("Median ")
            sensors = entity.get("sensors", [])
            self.median_entities[entity_id] = (
                f"{display_name} ({len(sensors)} {sensor_text})"
            )

        grouped = await self.config_service.get_selection_candidates(existing_ids or [])
        for device_list in grouped.values():
            for device in device_list:
                device_id = device.get("id")
                if device_id:
                    sensors = device.get("sensors", [])
                    name = device.get("name") or device_id
                    self.devices[device_id] = f"{name} ({len(sensors)} {sensor_text})"

    def _show_device_selection_form(
        self, errors: dict[str, str] | None = None
    ) -> FlowResult:
        return self.async_show_form(
            step_id="device_selection",
            data_schema=_selection_schema(self.devices, self.median_entities),
            errors=errors,
            description_placeholders={
                "device_count": str(len(self.devices)),
                "median_count": str(len(self.median_entities)),
            },
        )

    async def async_migrate_entry(
        self, hass: HomeAssistant, config_entry: config_entries.ConfigEntry
    ) -> bool:
        if config_entry.version >= self.VERSION:
            return True

        service = ConfigService(hass)
        data = dict(config_entry.data)
        service.register_entry_data(data)
        selected_ids = list(data.get(CONF_SELECTED_DEVICES, []))

        try:
            await service.async_get_catalog()
            metadata = await service.snapshot_devices(selected_ids)
        except DeviceCatalogError:
            stored = data.get(CONF_DEVICE_METADATA, {})
            metadata = {
                device_id: dict(stored.get(device_id, {}))
                if isinstance(stored, dict) and isinstance(stored.get(device_id), dict)
                else {
                    "id": device_id,
                    "name": device_id,
                    "type": "Unknown",
                    "sensors": [],
                    "sensor_metadata": {},
                }
                for device_id in selected_ids
            }

        aliases = await service.get_field_aliases()
        registry = er.async_get(hass)
        for registry_entry in registry.entities.values():
            if registry_entry.config_entry_id != config_entry.entry_id:
                continue
            for device_id in selected_ids:
                prefix = f"{device_id}_"
                if not registry_entry.unique_id.startswith(prefix):
                    continue
                raw_name = registry_entry.unique_id[len(prefix) :]
                if raw_name == "__device_meta":
                    continue
                sensor_name = aliases.get(raw_name, raw_name)
                sensors = metadata[device_id].setdefault("sensors", [])
                if sensor_name not in sensors:
                    sensors.append(sensor_name)

        data[CONF_DEVICE_METADATA] = metadata
        hass.config_entries.async_update_entry(
            config_entry, data=data, version=self.VERSION
        )
        return True

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "OptionsFlowHandler":
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Ändert die Geräteauswahl ohne bestehende Einträge zu verlieren."""

    def __init__(self) -> None:
        self.config_service: ConfigService | None = None
        self.devices: dict[str, str] = {}
        self.median_entities: dict[str, str] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self.async_step_device_selection(user_input)

    async def async_step_device_selection(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        current_devices = list(
            self.config_entry.data.get(CONF_SELECTED_DEVICES, [])
        )
        current_medians = list(
            self.config_entry.data.get(CONF_SELECTED_MEDIAN_ENTITIES, [])
        )

        if user_input is None:
            await self._async_initialize_config_service()
            assert self.config_service is not None
            self.config_service.register_entry_data(dict(self.config_entry.data))
            errors: dict[str, str] = {}
            try:
                await self._load_devices(current_devices)
            except DeviceCatalogError:
                await self._load_existing_devices(current_devices)
                errors["base"] = ERROR_CANNOT_CONNECT
            return self._show_device_selection_form(
                current_devices, current_medians, errors
            )

        selected_devices = list(user_input.get(CONF_SELECTED_DEVICES, []))
        selected_medians = list(user_input.get(CONF_SELECTED_MEDIAN_ENTITIES, []))
        if not selected_devices and not selected_medians:
            return self._show_device_selection_form(
                selected_devices,
                selected_medians,
                {"base": ERROR_NO_SELECTION},
            )

        assert self.config_service is not None
        metadata = await self.config_service.snapshot_devices(selected_devices)
        new_data = {
            **self.config_entry.data,
            CONF_SELECTED_DEVICES: selected_devices,
            CONF_SELECTED_MEDIAN_ENTITIES: selected_medians,
            CONF_DEVICE_METADATA: metadata,
        }
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
        await self.hass.config_entries.async_reload(self.config_entry.entry_id)
        return self.async_create_entry(title="", data={})

    async def _async_initialize_config_service(self) -> None:
        if self.config_service is None:
            self.config_service = ConfigService(self.hass)

    async def _load_devices(self, existing_ids: list[str]) -> None:
        assert self.config_service is not None
        self.devices.clear()
        self.median_entities.clear()
        ui_text = await self.config_service.get_ui_text()
        sensor_text = ui_text.get("sensors", "Sensoren")
        grouped = await self.config_service.get_selection_candidates(existing_ids)
        for device_list in grouped.values():
            for device in device_list:
                device_id = device.get("id")
                if device_id:
                    sensors = device.get("sensors", [])
                    self.devices[device_id] = (
                        f"{device.get('name') or device_id} "
                        f"({len(sensors)} {sensor_text})"
                    )
        await self._load_medians(sensor_text)

    async def _load_existing_devices(self, existing_ids: list[str]) -> None:
        assert self.config_service is not None
        self.devices.clear()
        self.median_entities.clear()
        for device_id in existing_ids:
            device = await self.config_service.get_device_by_id(device_id)
            name = device.get("name", device_id) if device else device_id
            sensors = device.get("sensors", []) if device else []
            self.devices[device_id] = f"{name} ({len(sensors)} Sensoren)"
        await self._load_medians("Sensoren")

    async def _load_medians(self, sensor_text: str) -> None:
        assert self.config_service is not None
        for entity in await self.config_service.get_median_entities():
            entity_id = entity.get("id")
            if entity_id:
                name = str(entity.get("name") or entity_id).removeprefix("Median ")
                self.median_entities[entity_id] = (
                    f"{name} ({len(entity.get('sensors', []))} {sensor_text})"
                )

    def _show_device_selection_form(
        self,
        current_devices: list[str],
        current_medians: list[str],
        errors: dict[str, str] | None = None,
    ) -> FlowResult:
        return self.async_show_form(
            step_id="device_selection",
            data_schema=_selection_schema(
                self.devices,
                self.median_entities,
                current_devices,
                current_medians,
            ),
            errors=errors,
            description_placeholders={
                "device_count": str(len(self.devices)),
                "median_count": str(len(self.median_entities)),
            },
        )


def _selection_schema(
    devices: dict[str, str],
    medians: dict[str, str],
    selected_devices: list[str] | None = None,
    selected_medians: list[str] | None = None,
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(
                CONF_SELECTED_DEVICES, default=selected_devices or []
            ): _multi_select(devices),
            vol.Optional(
                CONF_SELECTED_MEDIAN_ENTITIES, default=selected_medians or []
            ): _multi_select(medians),
        }
    )


def _multi_select(options: dict[str, str]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=value, label=label)
                for value, label in options.items()
            ],
            multiple=True,
            mode=SelectSelectorMode.DROPDOWN,
            custom_value=False,
        )
    )
