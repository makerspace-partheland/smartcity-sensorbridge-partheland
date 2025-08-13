"""
Sensor-Entities für SmartCity SensorBridge Partheland
HA 2025 Compliant - Sensor-Entity-Implementierung
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
import time

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
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

        # 1) Gerätespezifische primäre Darstellung sicherstellen
        device_type = device_info.get("type", "").lower()

        # Für senseBox: dedizierte Meta-Entity zuerst (Icon: mdi:memory)
        if device_type == "sensebox":
            meta_entity_data = {
                "device_id": device_id,
                "sensor_type": "__device_meta",
                "device_name": device_info.get("name", device_id),
                "attributes": {
                    "device_id": device_id,
                    "device_name": device_info.get("name", device_id),
                    "device_type": device_info.get("type", "senseBox"),
                    "topic_pattern": device_info.get("topic_pattern"),
                    "sensors": sensors,
                    "sensors_count": len(sensors),
                },
            }
            meta_entity = SensorBridgeSensor(coordinator, meta_entity_data, config_service)
            # Icon-Override und Kategorie für Meta-Entity setzen
            meta_entity._attr_icon = "mdi:memory"
            meta_entity._attr_entity_category = EntityCategory.DIAGNOSTIC
            entities.append(meta_entity)

        # Für median: dedizierte Meta-Entity zuerst (Icon: mdi:chart-box-outline)
        if device_type == "median":
            meta_entity_data = {
                "device_id": device_id,
                "sensor_type": "__device_meta",
                "device_name": device_info.get("name", device_id),
                "attributes": {
                    "device_id": device_id,
                    "device_name": device_info.get("name", device_id),
                    "device_type": device_info.get("type", "median"),
                    "topic_pattern": device_info.get("topic_pattern"),
                    "sensors": sensors,
                    "sensors_count": len(sensors),
                },
            }
            meta_entity = SensorBridgeSensor(coordinator, meta_entity_data, config_service)
            meta_entity._attr_icon = "mdi:chart-box-outline"
            meta_entity._attr_entity_category = EntityCategory.DIAGNOSTIC
            entities.append(meta_entity)

        # Für alle anderen Gerätetypen ebenfalls eine Meta-Entity (Icon je Typ)
        if device_type not in ("sensebox", "median"):
            meta_entity_data = {
                "device_id": device_id,
                "sensor_type": "__device_meta",
                "device_name": device_info.get("name", device_id),
                "attributes": {
                    "device_id": device_id,
                    "device_name": device_info.get("name", device_id),
                    "device_type": device_info.get("type", device_type),
                    "topic_pattern": device_info.get("topic_pattern"),
                    "sensors": sensors,
                    "sensors_count": len(sensors),
                },
            }
            meta_entity = SensorBridgeSensor(coordinator, meta_entity_data, config_service)
            # Icon abhängig vom Gerätetyp bestimmen
            if device_type == "waterlevel":
                meta_entity._attr_icon = "mdi:waves"
            elif device_type == "temperature":
                meta_entity._attr_icon = "mdi:thermometer"
            else:
                meta_entity._attr_icon = "mdi:sensor"
            meta_entity._attr_entity_category = EntityCategory.DIAGNOSTIC
            entities.append(meta_entity)

        # 2) Sensor-Reihenfolge pro Typ: wichtigstes zuerst
        if device_type == "waterlevel":
            if "water_level" in sensors:
                sensors = ["water_level"] + [s for s in sensors if s != "water_level"]
        elif device_type == "temperature":
            priority = ["LuftTemp", "TempC1", "TempC2", "WasserTemp", "WasserTemp_1", "WasserTemp_2"]
            sensors = sorted(sensors, key=lambda s: (s not in priority, priority.index(s) if s in priority else 999))

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

        # Meta-Entity (Diagnose) anlegen, damit Geräte-Icon/Status klar ist
        try:
            from homeassistant.helpers.entity import EntityCategory
        except Exception:
            EntityCategory = None  # type: ignore

        meta_entity_data = {
            "device_id": median_id,
            "sensor_type": "__device_meta",
            "device_name": median_info.get("name", median_id),
            "attributes": {
                "device_id": median_id,
                "device_name": median_info.get("name", median_id),
                "device_type": "median",
                "location": median_info.get("location", ""),
                "sensors": sensors,
                "sensors_count": len(sensors),
            },
        }
        meta_entity = SensorBridgeSensor(coordinator, meta_entity_data, config_service)
        meta_entity._attr_icon = "mdi:chart-box-outline"
        if EntityCategory is not None:
            meta_entity._attr_entity_category = EntityCategory.DIAGNOSTIC
        entities.append(meta_entity)

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
        if sensor_name == "__device_meta":
            # Meta-Entity liefert textuellen Status (online/stale/offline)
            self._attr_state_class = None
        else:
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

        # Repräsentative HA-Entity dem Coordinator melden (für Logbuch-Zuordnung)
        try:
            device_id = self.entity_data.get("device_id")
            if device_id and hasattr(self.coordinator, "register_ha_entity_for_device"):
                self.coordinator.register_ha_entity_for_device(device_id, self.entity_id)
        except Exception:
            pass

        # Geräte-Icon anhand der Diagnose-Entität auf das Gerät anwenden
        try:
            if self.entity_data.get("sensor_type") == "__device_meta":
                device_id = self.entity_data.get("device_id")
                if device_id:
                    device_registry = dr.async_get(self.coordinator.hass)
                    dev = device_registry.async_get_device(identifiers={(DOMAIN, device_id)})
                    if dev is not None:
                        # Verwende das bereits gesetzte Icon dieser Meta-Entity
                        device_registry.async_update_device(dev.id, icon=self._attr_icon)
        except Exception as e:
            _LOGGER.debug("Konnte Geräte-Icon nicht setzen: %s", e)

        # Coordinator-Update-Callback registrieren
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

        # Initialen State sofort schreiben, damit neue State-Texte (z. B. Deutsch) direkt sichtbar sind
        try:
            self.async_write_ha_state()
        except Exception:
            pass

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

            # Icon setzen (für Meta explizit lassen)
            if sensor_name != "__device_meta":
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

            # Namen-Änderungen ggf. in den Zustand übernehmen
            # Meta-Entity schreibt den State sehr früh ohnehin; doppelte Logbucheinträge vermeiden
            if sensor_name != "__device_meta":
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

    def _format_duration(self, seconds: float) -> str:
        """Formatiert eine Dauer kurz (z. B. 'vor 5 min', 'vor 2 Std.')."""
        try:
            total_seconds = int(max(0, round(seconds)))
            if total_seconds < 60:
                return f"vor {total_seconds} s"

            total_minutes = total_seconds // 60
            if total_minutes < 60:
                return f"vor {total_minutes} min"

            total_hours = total_minutes // 60
            if total_hours < 24:
                rem_min = total_minutes % 60
                if rem_min:
                    return f"vor {total_hours} Std. {rem_min} min"
                return f"vor {total_hours} Std."

            total_days = total_hours // 24
            rem_hours = total_hours % 24
            if rem_hours:
                return f"vor {total_days} Tg. {rem_hours} Std."
            return f"vor {total_days} Tg."
        except Exception:
            return "vor 1 s"

    @property
    def native_value(self) -> StateType:
        """Gibt den aktuellen Sensor-Wert zurück."""
        device_id = self.entity_data.get("device_id")
        sensor_name = self.entity_data.get("sensor_type")

        # Meta-Entity: Online/Stale/Offline Status
        if sensor_name == "__device_meta":
            # Als textueller Sensor behandeln
            self._attr_device_class = None
            self._attr_native_unit_of_measurement = None
            # MQTT verbunden?
            mqtt_connected = False
            try:
                mqtt_connected = bool(self.coordinator.mqtt_service.is_connected)
            except Exception:
                mqtt_connected = False

            # Last Seen und Threshold
            last_seen = None
            try:
                if hasattr(self.coordinator, "get_device_last_seen"):
                    last_seen = self.coordinator.get_device_last_seen(device_id)
            except Exception:
                last_seen = None

            # Threshold bestimmen
            stale_after = 300
            try:
                device_type = self.entity_data.get("attributes", {}).get("device_type")
                if hasattr(self.coordinator, "get_effective_stale_seconds"):
                    stale_after = int(self.coordinator.get_effective_stale_seconds(device_id, device_type))
            except Exception:
                pass

            # Statuslogik
            if not mqtt_connected:
                return "Offline"
            if last_seen is None:
                return "Veraltet"
            import time as _t
            return "Online" if (_t.monotonic() - last_seen) <= stale_after else "Veraltet"

        if not device_id or not sensor_name:
            return None

        # Daten vom Coordinator holen
        coordinator_data = self.coordinator.data
        device_data = coordinator_data.get(device_id, {})

        return device_data.get(sensor_name)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Gibt zusätzliche Entity-Attribute zurück."""
        attrs = dict(self.entity_data.get("attributes", {}))
        # Zusätzliche Diagnoseattribute
        try:
            mqtt_connected = getattr(self.coordinator.mqtt_service, "is_connected", False)
            attrs["mqtt_connected"] = "Ja" if bool(mqtt_connected) else "Nein"
            device_id = self.entity_data.get("device_id")
            last_seen = None
            if hasattr(self.coordinator, "get_device_last_seen"):
                last_seen = self.coordinator.get_device_last_seen(device_id)
            if last_seen is not None:
                delta_seconds = max(0.0, time.monotonic() - last_seen)
                attrs["last_seen"] = self._format_duration(delta_seconds)
            # Für Meta-Entity: zusätzliche Schwelle und Sensorliste/Topic
            if self.entity_data.get("sensor_type") == "__device_meta":
                # Threshold
                try:
                    device_type = attrs.get("device_type")
                    if hasattr(self.coordinator, "get_effective_stale_seconds"):
                        threshold_seconds = int(
                            self.coordinator.get_effective_stale_seconds(device_id, device_type)
                        )
                        # In Minuten ausgeben, da UI/Config in Minuten arbeitet
                        attrs["inactivity_threshold_minutes"] = int(round(threshold_seconds / 60))
                except Exception:
                    pass
                # Sensors/Topic sind für Meta-Entity bereits in attributes enthalten
        except Exception:
            pass
        return attrs

    @property
    def available(self) -> bool:
        """Gibt zurück ob der Sensor verfügbar ist."""
        # Meta-Entity soll immer verfügbar sein, Status steckt im State
        if self.entity_data.get("sensor_type") == "__device_meta":
            return True
        # Globaler Coordinator-Status und MQTT-Verbindung
        if not self.coordinator.last_update_success:
            return False
        try:
            if not self.coordinator.mqtt_service.is_connected:
                return False
        except Exception:
            # Fallback auf Coordinator-State
            return False

        # Stale-Detection pro Gerät
        device_id = self.entity_data.get("device_id")
        last_seen = None
        if hasattr(self.coordinator, "get_device_last_seen"):
            last_seen = self.coordinator.get_device_last_seen(device_id)
        if last_seen is None:
            # Noch keine Daten empfangen → nicht als unavailable markieren
            return True
        stale_after = 300
        # Gerätetyp bestimmen (für per-type Stale)
        device_type = self.entity_data.get("attributes", {}).get("device_type")
        # Effektiven Threshold vom Coordinator holen, falls verfügbar
        if hasattr(self.coordinator, "get_effective_stale_seconds"):
            try:
                stale_after = int(self.coordinator.get_effective_stale_seconds(self.entity_data.get("device_id"), device_type))
            except Exception:
                pass
        elif hasattr(self.coordinator, "get_stale_after_seconds"):
            try:
                stale_after = int(self.coordinator.get_stale_after_seconds())
            except Exception:
                pass
        return (time.monotonic() - last_seen) <= stale_after

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
                        "Translation gefunden für %s: %s",
                        sensor_name,
                        sensor_data["name"],
                    )
                else:
                    _LOGGER.warning(
                        "Invalid translation structure for %s: %s",
                        sensor_name,
                        sensor_data,
                    )
            else:
                _LOGGER.warning(
                    "KEINE Translation gefunden für Key: %s", sensor_name
                )
                _LOGGER.warning(
                    "Verfügbare Keys: %s", list(sensor_translations.keys())
                )

        except Exception as e:
            _LOGGER.error("Fehler beim Translation-Test: %s", e)
