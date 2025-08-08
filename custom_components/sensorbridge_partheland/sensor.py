"""
Sensor-Entities für SmartCity SensorBridge Partheland
HA 2025 Compliant - Sensor-Entity-Implementierung
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import slugify
from homeassistant.helpers.entity import async_generate_entity_id

from .const import DOMAIN, MANUFACTURER
from .coordinator import SensorBridgeCoordinator
from .interfaces import ConfigServiceProtocol

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SensorBridge sensors from a config entry."""
    _LOGGER.debug("Setting up SensorBridge sensors")

    # Coordinator holen
    coordinator: SensorBridgeCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Config Service holen
    config_service: ConfigServiceProtocol = hass.data[DOMAIN]["config_service"]

    # Entities erstellen
    entities = []

    try:
        # Einzelne Geräte
        selected_devices = entry.data.get("selected_devices", [])
        for device_id in selected_devices:
            device_entities = await create_device_entities(
                coordinator, device_id, config_service
            )
            entities.extend(device_entities)

        # Median-Entities
        selected_median_entities = entry.data.get(
            "selected_median_entities", []
        )
        for median_id in selected_median_entities:
            median_entities = await create_median_entities(
                coordinator, median_id, config_service
            )
            entities.extend(median_entities)

        _LOGGER.info("Created %d sensor entities", len(entities))
        async_add_entities(entities)

    except Exception as e:
        _LOGGER.error("Error setting up sensor entities: %s", e)


async def create_device_entities(
    coordinator: SensorBridgeCoordinator,
    device_id: str,
    config_service: ConfigServiceProtocol,
) -> list[SensorBridgeSensor]:
    """Erstellt Entities für ein einzelnes Gerät."""
    entities = []

    try:
        # Device-Info laden
        device_info = await config_service.get_device_by_id(device_id)
        if not device_info:
            _LOGGER.warning("Device info not found for %s", device_id)
            return entities

        # Sensoren des Geräts
        sensors = device_info.get("sensors", [])

        for sensor_name in sensors:
            entity_data = {
                "device_id": device_id,
                "sensor_type": sensor_name,
                "device_name": device_info.get("name", device_id),
                "external_urls": device_info.get("external_urls", {}),
                "attributes": {
                    "device_id": device_id,
                    "device_name": device_info.get("name", device_id),
                    "sensor_type": sensor_name,
                    "device_type": device_info.get("type", "unknown"),
                },
            }

            entity = SensorBridgeSensor(
                coordinator, entity_data, config_service
            )
            entities.append(entity)

        return entities

    except Exception as e:
        _LOGGER.error(
            "Error creating device entities for %s: %s", device_id, e
        )
        return entities


async def create_median_entities(
    coordinator: SensorBridgeCoordinator,
    median_id: str,
    config_service: ConfigServiceProtocol,
) -> list[SensorBridgeSensor]:
    """Erstellt Entities für Median-Daten."""
    entities = []

    try:
        # Median-Info laden
        median_info = await config_service.get_median_by_id(median_id)
        if not median_info:
            _LOGGER.warning("Median info not found for %s", median_id)
            return entities

        # Sensoren des Medians
        sensors = median_info.get("sensors", [])

        for sensor_name in sensors:
            entity_data = {
                "device_id": median_id,
                "sensor_type": sensor_name,
                "device_name": median_info.get("name", median_id),
                "attributes": {
                    "device_id": median_id,
                    "device_name": median_info.get("name", median_id),
                    "sensor_type": sensor_name,
                    "device_type": "median",
                    "location": median_info.get("location", ""),
                },
            }

            entity = SensorBridgeSensor(
                coordinator, entity_data, config_service
            )
            entities.append(entity)

        return entities

    except Exception as e:
        _LOGGER.error(
            "Error creating median entities for %s: %s", median_id, e
        )
        return entities


class SensorBridgeSensor(SensorEntity):
    """SensorBridge Sensor Entity."""

    def __init__(
        self,
        coordinator: SensorBridgeCoordinator,
        entity_data: Dict[str, Any],
        config_service: ConfigServiceProtocol,
    ) -> None:
        """Initialize the sensor."""
        self.coordinator = coordinator
        self.entity_data = entity_data
        self.config_service = config_service

        # Entity-Attribute setzen
        device_id = entity_data.get("device_id", "")
        sensor_name = entity_data.get("sensor_type", "")

        self._attr_unique_id = f"{device_id}_{sensor_name}"

        # HA 2025 Translation-API: translation_key setzen
        self._attr_translation_key = sensor_name

        device_name = entity_data.get("device_name", device_id)

        # Entity-ID vorbereiten. Mit `has_entity_name=True` stellt Home
        # Assistant den Gerätenamen automatisch voran. Wir schlagen daher
        # nur einen Object-ID vor, die aus Geräte- und Sensorname besteht,
        # damit das erste Registrieren einen stabilen Wert nutzt.
        object_id = f"{slugify(device_name)}_{slugify(sensor_name)}"
        self._attr_suggested_object_id = object_id

        # Erzwinge das gewünschte entity_id-Schema bereits bei Erstellung
        try:
            self.entity_id = async_generate_entity_id(
                "sensor.{}", object_id, hass=self.coordinator.hass
            )
        except Exception as e:
            _LOGGER.debug("Konnte entity_id nicht vorab generieren: %s", e)

        self._attr_has_entity_name = True

        # Sensor-Attribute asynchron laden
        self._attr_device_class = None
        self._attr_native_unit_of_measurement = None
        self._attr_icon = "mdi:sensor"

        # State-Class bestimmen
        self._attr_state_class = SensorStateClass.MEASUREMENT

        # Device-Info setzen (ohne via_device)
        external_urls = entity_data.get("external_urls", {})
        makerspace_url = external_urls.get("makerspace")
        opensensemap_url = external_urls.get("openSenseMap")

        configuration_url = makerspace_url or opensensemap_url

        device_info_kwargs: Dict[str, Any] = {
            "identifiers": {(DOMAIN, device_id)},
            "name": device_name,
            "manufacturer": MANUFACTURER,
            "model": device_id,
        }

        if configuration_url:
            device_info_kwargs["configuration_url"] = configuration_url

        self._attr_device_info = DeviceInfo(**device_info_kwargs)

        _LOGGER.info("=== SENSOR CREATION DEBUG ===")
        _LOGGER.info("Created sensor: %s", self._attr_unique_id)
        _LOGGER.info("suggested_object_id: %s | entity_id(now): %s", object_id, getattr(self, "entity_id", None))
        _LOGGER.info("translation_key: %s", self._attr_translation_key)
        _LOGGER.info("has_entity_name: %s", self._attr_has_entity_name)
        _LOGGER.info("device_name: %s", device_name)
        _LOGGER.info("sensor_name: %s", sensor_name)

        # Debug-Translation-Test nicht automatisch ausführen
        self.hass = None  # Wird in async_added_to_hass gesetzt

    async def async_added_to_hass(self) -> None:
        """Wird aufgerufen wenn Entity zu Home Assistant hinzugefügt wird."""
        await super().async_added_to_hass()

        # Hass-Referenz setzen
        self.hass = self.coordinator.hass
        # Kein automatischer Translation-Test (reduziert Log-Lärm)

        # Sensor-Attribute laden
        await self._load_sensor_attributes()

        # Coordinator-Update-Callback registrieren
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

        _LOGGER.debug(
            "SensorBridge sensor added to hass: %s", self._attr_unique_id
        )

    async def _load_sensor_attributes(self) -> None:
        """Lädt die Sensor-Attribute aus der Konfiguration."""
        try:
            sensor_name = self.entity_data.get("sensor_type", "")

            # Field-Mapping laden
            field_mapping = await self.config_service.get_field_mapping()
            units = field_mapping.get("units", {})
            device_classes = field_mapping.get("device_classes", {})

            # Unit setzen
            unit = units.get(sensor_name)
            if unit:
                self._attr_native_unit_of_measurement = unit

            # Device-Class setzen
            device_class_str = device_classes.get(sensor_name)
            if device_class_str:
                self._attr_device_class = await self._get_device_class(
                    device_class_str
                )

            # Icon setzen
            self._attr_icon = await self._get_sensor_icon(
                sensor_name, device_class_str
            )

            # Anzeigename aus Übersetzung auffüllen, damit die UI-Felder nicht leer sind
            try:
                sensor_names = await self.config_service.get_sensor_names()
                translated = sensor_names.get(sensor_name)
                self._attr_name = translated or sensor_name
            except Exception as name_err:
                _LOGGER.debug("Konnte übersetzten Namen nicht laden: %s", name_err)
                self._attr_name = sensor_name

            # Device-Info setzen (ohne via_device)
            device_id = self.entity_data.get("device_id")
            if device_id:
                external_urls = self.entity_data.get("external_urls", {})
                makerspace_url = external_urls.get("makerspace")
                opensensemap_url = external_urls.get("openSenseMap")

                configuration_url = makerspace_url or opensensemap_url

                device_info_kwargs: Dict[str, Any] = {
                    "identifiers": {(DOMAIN, device_id)},
                    "name": self.entity_data.get("device_name", device_id),
                    "manufacturer": MANUFACTURER,
                    "model": device_id,
                }
                if configuration_url:
                    device_info_kwargs["configuration_url"] = configuration_url

                self._attr_device_info = DeviceInfo(**device_info_kwargs)

            _LOGGER.info(
                "Sensor attributes loaded for %s: "
                "translation_key='%s', unit='%s', device_class='%s', "
                "icon='%s'",
                self._attr_unique_id,
                self._attr_translation_key,
                unit,
                device_class_str,
                self._attr_icon,
            )

            # Namen-Änderungen sofort in den Zustand übernehmen
            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error("Error loading sensor attributes: %s", e)

    async def _get_device_class(
        self, device_class_str: str
    ) -> Optional[SensorDeviceClass]:
        """Konvertiert String zu SensorDeviceClass."""
        try:
            # Device Class Mapping aus der Konfiguration laden
            device_class_mapping = (
                await self.config_service.get_device_class_mapping()
            )

            # Device Class Enum aus der Konfiguration holen
            device_class_enum = device_class_mapping.get(device_class_str)

            if device_class_enum:
                return device_class_enum

            _LOGGER.warning("Unknown device class: %s", device_class_str)
            return None

        except Exception as e:
            _LOGGER.error(
                "Error converting device class %s: %s", device_class_str, e
            )
            return None

    async def _get_sensor_icon(
        self, sensor_name: str, device_class_str: Optional[str]
    ) -> str:
        """Bestimmt das Icon für einen Sensor."""
        try:
            # Icon-Mapping aus Konfiguration laden
            icons = await self.config_service.get_icons()

            # Sensor-Kategorien laden
            sensor_categories = (
                await self.config_service.get_sensor_categories()
            )

            # Sensor-Kategorie bestimmen
            sensor_category = "unknown"
            for category, sensors in sensor_categories.items():
                if sensor_name in sensors:
                    sensor_category = category
                    break

            # Icon basierend auf Device-Class (höchste Priorität)
            if device_class_str and device_class_str in icons:
                return icons[device_class_str]

            # Icon basierend auf Sensor-Kategorie
            if sensor_category in icons:
                return icons[sensor_category]

            # Default-Icon aus Konfiguration
            return icons.get("default", "mdi:sensor")

        except Exception as e:
            _LOGGER.error("Error determining sensor icon: %s", e)
            return "mdi:sensor"

    @property
    def native_value(self) -> StateType:
        """Gibt den aktuellen Sensor-Wert zurück."""
        device_id = self.entity_data.get("device_id")
        sensor_name = self.entity_data.get("sensor_type")

        if not device_id or not sensor_name:
            return None

        # Daten vom Coordinator holen
        coordinator_data = self.coordinator.data
        device_data = coordinator_data.get(device_id, {})

        return device_data.get(sensor_name)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Gibt zusätzliche Entity-Attribute zurück."""
        return self.entity_data.get("attributes", {})

    @property
    def available(self) -> bool:
        """Gibt zurück ob der Sensor verfügbar ist."""
        return self.coordinator.last_update_success

    async def async_will_remove_from_hass(self) -> None:
        """Wird aufgerufen wenn Entity aus Home Assistant entfernt wird."""
        await super().async_will_remove_from_hass()

        _LOGGER.debug(
            "SensorBridge sensor removed from hass: %s", self._attr_unique_id
        )

    async def test_translation(self) -> Dict[str, Any]:
        """Test-Methode um die Translation-Funktionalität zu validieren."""
        try:
            sensor_name = self.entity_data.get("sensor_type", "")
            device_name = self.entity_data.get("device_name", "")

            # Translation-Info sammeln
            test_result = {
                "unique_id": self._attr_unique_id,
                "translation_key": self._attr_translation_key,
                "has_entity_name": self._attr_has_entity_name,
                "current_name": self._attr_name,
                "device_name": device_name,
                "sensor_name": sensor_name,
            }

            _LOGGER.info(
                "Translation Test für %s: %s",
                self._attr_unique_id,
                test_result,
            )
            return test_result

        except Exception as e:
            _LOGGER.error("Fehler beim Translation-Test: %s", e)

            return {"error": str(e)}

    async def force_name_update(self) -> None:
        """Erzwingt ein Update des Entity-Namens."""
        try:
            # Entity-State aktualisieren
            self.async_write_ha_state()
            _LOGGER.info(
                "Entity-Name Update erzwungen für %s", self._attr_unique_id
            )
        except Exception as e:
            _LOGGER.error("Fehler beim erzwungenen Name-Update: %s", e)

    async def _test_translation_on_add(self) -> None:
        """Testet die Translation beim Hinzufügen zur Hass."""
        try:
            sensor_name = self.entity_data.get("sensor_type", "")

            # Translation-API direkt testen

            from homeassistant.helpers.translation import (
                async_get_translations,
            )

            translations = await async_get_translations(
                self.hass, self.hass.config.language, "entity", [DOMAIN]
            )

            # Korrekte Struktur basierend auf de.json:
            # entity.sensor.{sensor_name}.name
            entity_translations = translations.get("entity", {})
            sensor_translations = entity_translations.get("sensor", {})

            _LOGGER.info(
                "=== TRANSLATION TEST für %s ===", self._attr_unique_id
            )
            _LOGGER.info("Language: %s", self.hass.config.language)
            _LOGGER.info("Domain: %s", DOMAIN)

            if sensor_name in sensor_translations:
                sensor_data = sensor_translations[sensor_name]
                if isinstance(sensor_data, dict) and "name" in sensor_data:
                    _LOGGER.info(
                        "✅ Translation gefunden für %s: %s",
                        sensor_name,
                        sensor_data["name"],
                    )
                else:
                    _LOGGER.warning(
                        "❌ Invalid translation structure for %s: %s",
                        sensor_name,
                        sensor_data,
                    )
            else:
                _LOGGER.warning(
                    "❌ KEINE Translation gefunden für Key: %s", sensor_name
                )
                _LOGGER.warning(
                    "Verfügbare Keys: %s", list(sensor_translations.keys())
                )

        except Exception as e:
            _LOGGER.error("Fehler beim Translation-Test: %s", e)
