"""
Config Flow für SmartCity SensorBridge Partheland
HA 2025 Compliant - Vereinfachte UI-Logik
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN, NAME, CONF_SELECTED_DEVICES, CONF_SELECTED_MEDIAN_ENTITIES,
    ERROR_CANNOT_CONNECT, ERROR_UNKNOWN, ERROR_VALIDATION, ERROR_NO_SELECTION,
    ABORT_ALREADY_CONFIGURED, ABORT_NO_DEVICES, ABORT_SINGLE_INSTANCE
)

_LOGGER = logging.getLogger(__name__)


class CannotConnect(HomeAssistantError):
    """Fehler beim Verbinden."""
    pass


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SmartCity SensorBridge Partheland."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self.config_service = None
        self.devices: Dict[str, str] = {}
        self.median_entities: Dict[str, str] = {}

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step."""
        # Prüfe ob bereits konfiguriert
        if self._async_current_entries():
            return self.async_abort(reason=ABORT_ALREADY_CONFIGURED)

        # Config Service asynchron initialisieren
        await self._async_initialize_config_service()
        
        # Konfiguration validieren
        if not await self.config_service.validate_config():
            return self.async_abort(reason=ABORT_NO_DEVICES)

        # Geräte laden
        await self._load_devices()

        return await self.async_step_device_selection()

    async def _async_initialize_config_service(self) -> None:
        """Initialisiert den Config Service asynchron."""
        if self.config_service is None:
            try:
                # Import asynchron im Event Loop
                await self.hass.async_add_executor_job(
                    self._import_config_service
                )
                _LOGGER.debug("Config Service asynchron initialisiert")
            except Exception as e:
                _LOGGER.error("Fehler bei der Config Service Initialisierung: %s", e)
                self.config_service = None

    def _import_config_service(self) -> None:
        """Importiert den Config Service synchron."""
        from .config_service import ConfigService
        self.config_service = ConfigService(self.hass)

    async def async_step_device_selection(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle device selection step."""
        if user_input is None:
            return self._show_device_selection_form()

        # Validierung
        selected_devices = user_input.get(CONF_SELECTED_DEVICES, [])
        selected_median_entities = user_input.get(CONF_SELECTED_MEDIAN_ENTITIES, [])

        if not selected_devices and not selected_median_entities:
            return self._show_device_selection_form(
                errors={"base": ERROR_NO_SELECTION}
            )

        # Config Entry erstellen
        config_data = {
            CONF_SELECTED_DEVICES: selected_devices,
            CONF_SELECTED_MEDIAN_ENTITIES: selected_median_entities,
        }

        return self.async_create_entry(
            title=NAME,
            data=config_data
        )

    async def _load_devices(self) -> None:
        """Lädt verfügbare Geräte."""
        if not self.config_service:
            return

        try:
            # Einzelne Geräte laden
            devices = await self.config_service.get_devices()
            device_categories = await self.config_service.get_device_categories()
            ui_text = await self.config_service.get_ui_text()

            for device_type, device_list in devices.items():
                if device_type == "MedianEntities":
                    continue
                
                for device in device_list:
                    device_id = device.get("id", "")
                    device_name = device.get("name", "")
                    sensors = device.get("sensors", [])
                    
                    if device_id and device_name:
                        sensor_text = ui_text.get("sensors", "Sensoren")
                        sensor_info = f" ({len(sensors)} {sensor_text})"
                        # Verwende nur den Gerätenamen ohne Kategorie-Präfix
                        self.devices[device_id] = f"{device_name}{sensor_info}"

            # Median-Entities laden
            median_entities = await self.config_service.get_median_entities()
            for entity in median_entities:
                entity_id = entity.get("id", "")
                entity_name = entity.get("name", "")
                sensors = entity.get("sensors", [])
                
                if entity_id and entity_name:
                    sensor_text = ui_text.get("sensors", "Sensoren")
                    sensor_info = f" ({len(sensors)} {sensor_text})"
                    # Entferne "Median" aus dem Namen falls es bereits enthalten ist
                    if entity_name.startswith("Median "):
                        display_name = entity_name[7:]  # "Median " entfernen
                    else:
                        display_name = entity_name
                    self.median_entities[entity_id] = f"{display_name}{sensor_info}"

        except Exception as e:
            _LOGGER.error("Fehler beim Laden der Geräte: %s", e)

    def _show_device_selection_form(
        self, errors: Optional[Dict[str, str]] = None
    ) -> FlowResult:
        """Zeigt das Geräteauswahl-Formular."""
        schema = vol.Schema({
            vol.Optional(CONF_SELECTED_DEVICES): vol.All(
                cv.multi_select(self.devices),
                vol.Length(min=0)
            ),
            vol.Optional(CONF_SELECTED_MEDIAN_ENTITIES): vol.All(
                cv.multi_select(self.median_entities),
                vol.Length(min=0)
            ),
        })

        return self.async_show_form(
            step_id="device_selection",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "device_count": str(len(self.devices)),
                "median_count": str(len(self.median_entities))
            }
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for SmartCity SensorBridge Partheland."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        self.config_service: Optional[Any] = None
        self.devices: Dict[str, str] = {}
        self.median_entities: Dict[str, str] = {}

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle options flow initialization."""
        return await self.async_step_device_selection()

    async def async_step_device_selection(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle device selection in options flow."""
        if user_input is None:
            # Config Service asynchron initialisieren
            await self._async_initialize_config_service()
            await self._load_devices()
            
            # Aktuelle Auswahl laden
            current_devices = self.config_entry.data.get(CONF_SELECTED_DEVICES, [])
            current_median_entities = self.config_entry.data.get(CONF_SELECTED_MEDIAN_ENTITIES, [])
            
            return self._show_device_selection_form(
                current_devices=current_devices,
                current_median_entities=current_median_entities
            )

        # Validierung
        selected_devices = user_input.get(CONF_SELECTED_DEVICES, [])
        selected_median_entities = user_input.get(CONF_SELECTED_MEDIAN_ENTITIES, [])

        if not selected_devices and not selected_median_entities:
            return self._show_device_selection_form(
                current_devices=selected_devices,
                current_median_entities=selected_median_entities,
                errors={"base": ERROR_NO_SELECTION}
            )

        # Config Entry aktualisieren
        new_data = {
            **self.config_entry.data,
            CONF_SELECTED_DEVICES: selected_devices,
            CONF_SELECTED_MEDIAN_ENTITIES: selected_median_entities,
        }

        self.hass.config_entries.async_update_entry(
            self.config_entry, data=new_data
        )

        # Integration neu laden, damit die geänderte Gerätauswahl sofort
        # angewendet wird und neue Entities/Devices angelegt werden
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(self.config_entry.entry_id)
        )

        return self.async_create_entry(title="", data={})

    async def _async_initialize_config_service(self) -> None:
        """Initialisiert den Config Service asynchron."""
        if self.config_service is None:
            try:
                # Import asynchron im Event Loop
                await self.hass.async_add_executor_job(
                    self._import_config_service
                )
                _LOGGER.debug("Config Service asynchron initialisiert (Options)")
            except Exception as e:
                _LOGGER.error("Fehler bei der Config Service Initialisierung (Options): %s", e)
                self.config_service = None

    def _import_config_service(self) -> None:
        """Importiert den Config Service synchron."""
        from .config_service import ConfigService
        self.config_service = ConfigService(self.hass)

    async def _load_devices(self) -> None:
        """Lädt verfügbare Geräte."""
        if not self.config_service:
            return

        try:
            # Einzelne Geräte laden
            devices = await self.config_service.get_devices()
            device_categories = await self.config_service.get_device_categories()
            ui_text = await self.config_service.get_ui_text()

            for device_type, device_list in devices.items():
                if device_type == "MedianEntities":
                    continue
                
                for device in device_list:
                    device_id = device.get("id", "")
                    device_name = device.get("name", "")
                    sensors = device.get("sensors", [])
                    
                    if device_id and device_name:
                        sensor_text = ui_text.get("sensors", "Sensoren")
                        sensor_info = f" ({len(sensors)} {sensor_text})"
                        # Verwende nur den Gerätenamen ohne Kategorie-Präfix
                        self.devices[device_id] = f"{device_name}{sensor_info}"

            # Median-Entities laden
            median_entities = await self.config_service.get_median_entities()
            for entity in median_entities:
                entity_id = entity.get("id", "")
                entity_name = entity.get("name", "")
                sensors = entity.get("sensors", [])
                
                if entity_id and entity_name:
                    sensor_text = ui_text.get("sensors", "Sensoren")
                    sensor_info = f" ({len(sensors)} {sensor_text})"
                    # Entferne "Median" aus dem Namen falls es bereits enthalten ist
                    if entity_name.startswith("Median "):
                        display_name = entity_name[7:]  # "Median " entfernen
                    else:
                        display_name = entity_name
                    self.median_entities[entity_id] = f"{display_name}{sensor_info}"

        except Exception as e:
            _LOGGER.error("Fehler beim Laden der Geräte: %s", e)

    def _show_device_selection_form(
        self,
        current_devices: Optional[List[str]] = None,
        current_median_entities: Optional[List[str]] = None,
        errors: Optional[Dict[str, str]] = None
    ) -> FlowResult:
        """Zeigt das Geräteauswahl-Formular."""
        schema = vol.Schema({
            vol.Optional(CONF_SELECTED_DEVICES, default=current_devices or []): vol.All(
                cv.multi_select(self.devices),
                vol.Length(min=0)
            ),
            vol.Optional(CONF_SELECTED_MEDIAN_ENTITIES, default=current_median_entities or []): vol.All(
                cv.multi_select(self.median_entities),
                vol.Length(min=0)
            ),
        })

        return self.async_show_form(
            step_id="device_selection",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "device_count": str(len(self.devices)),
                "median_count": str(len(self.median_entities))
            }
        ) 