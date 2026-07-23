"""
SmartCity SensorBridge Partheland Integration
HA 2025 Compliant - Moderne Integration für Umweltsensorik
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api_client import DeviceCatalogError
from .config_service import ConfigService
from .const import (
    CONF_DEVICE_METADATA,
    CONF_INCLUDE_DWD_POLLEN,
    CONF_INCLUDE_GEOBOX_BRANDIS,
    CONF_SELECTED_DEVICES,
    CONF_SELECTED_MEDIAN_ENTITIES,
    CONFIG_ENTRY_VERSION,
    DOMAIN,
    DWD_POLLEN_DEVICE_ID,
    DWD_POLLEN_SOURCE,
    DWD_PRECIPITATION_STATIONS,
    GEOBOX_BRANDIS_DEVICE_ID,
    GEOBOX_BRANDIS_SOURCE,
    PLATFORMS,
)
from .entity_factory import EntityFactory
from .error_handler import ErrorHandler
from .mqtt_service import MQTTService
from .parser_service import ParserService
from .runtime import SensorBridgeConfigEntry, SensorBridgeRuntimeData

_LOGGER = logging.getLogger(__name__)
_SHUTDOWN_ATTEMPTS = 3
_PENDING_RUNTIME_SHUTDOWNS = "pending_runtime_shutdowns"
_PENDING_RUNTIME_TASKS = "pending_runtime_tasks"


async def async_migrate_entry(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> bool:
    """Migriert bestehende Config Entries auf den API-basierten Katalog."""
    if config_entry.version >= CONFIG_ENTRY_VERSION:
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
            if isinstance(stored, dict)
            and isinstance(stored.get(device_id), dict)
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
        config_entry, data=data, version=CONFIG_ENTRY_VERSION
    )
    return True


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the SmartCity SensorBridge Partheland integration."""
    try:
        _LOGGER.info("Setting up SmartCity SensorBridge Partheland")

        # Domain in hass.data initialisieren
        hass.data.setdefault(DOMAIN, {})

        # Hinweis: Geräte-Icons werden nicht separat gecacht – Gerätelisten-Icons stammen
        # aus der primären Entität (MDI), nicht aus benutzerdefinierten Mappings.

        # Debug-Services registrieren (nur wenn noch nicht registriert)
        try:
            hass.services.async_register(
                DOMAIN, "debug_translations", debug_translations_service
            )
            hass.services.async_register(
                DOMAIN, "test_translations", test_translations_service
            )
            hass.services.async_register(
                DOMAIN,
                "debug_translation_file",
                debug_translation_file_service,
            )
            _LOGGER.debug("Debug-Services erfolgreich registriert")
        except Exception as e:
            _LOGGER.warning("Fehler bei der Service-Registrierung: %s", e)

        _LOGGER.info(
            "SmartCity SensorBridge Partheland erfolgreich initialisiert"
        )
        return True

    except Exception as e:
        _LOGGER.error("Fehler beim Setup der Integration: %s", e)
        return False


async def _async_create_runtime(
    hass: HomeAssistant, entry: SensorBridgeConfigEntry
) -> SensorBridgeRuntimeData:
    """Erstelle voneinander getrennte Laufzeitobjekte für einen Config-Entry."""
    config_service = ConfigService(hass)
    config_service.register_entry_data(dict(entry.data))
    if not await config_service.validate_config():
        raise ConfigEntryError("Lokale Integrationskonfiguration ist ungültig")

    mqtt_service = MQTTService(hass, config_service, entry.entry_id)
    parser_service = ParserService(hass, config_service)
    entity_factory = EntityFactory(hass, config_service)
    error_handler = ErrorHandler(hass)

    from .coordinator import SensorBridgeCoordinator

    coordinator = SensorBridgeCoordinator(
        hass=hass,
        entry=entry,
        config_service=config_service,
        mqtt_service=mqtt_service,
        parser_service=parser_service,
        entity_factory=entity_factory,
        error_handler=error_handler,
    )
    return SensorBridgeRuntimeData(
        config_service=config_service,
        coordinator=coordinator,
        supplemental_coordinators={},
    )


async def _async_shutdown_runtime(runtime: SensorBridgeRuntimeData) -> bool:
    """Beende alle Laufzeitobjekte unabhängig voneinander."""
    shutdown_ok = True
    for source, coordinator in list(runtime.supplemental_coordinators.items()):
        try:
            await coordinator.async_shutdown()
        except Exception as err:
            shutdown_ok = False
            _LOGGER.warning(
                "Zusatzquelle %s konnte nicht beendet werden: %s", source, err
            )
        else:
            runtime.supplemental_coordinators.pop(source, None)

    if not runtime.coordinator_shutdown:
        try:
            await runtime.coordinator.async_shutdown()
        except Exception as err:
            shutdown_ok = False
            _LOGGER.warning("Coordinator konnte nicht beendet werden: %s", err)
        else:
            runtime.coordinator_shutdown = True

    return shutdown_ok


async def _async_shutdown_runtime_with_retries(
    runtime: SensorBridgeRuntimeData,
) -> bool:
    """Wiederhole ausschließlich noch nicht abgeschlossene Cleanup-Schritte."""
    async with runtime.shutdown_lock:
        for _attempt in range(_SHUTDOWN_ATTEMPTS):
            if await _async_shutdown_runtime(runtime):
                return True
    return False


def _async_remove_pending_runtime(
    hass: HomeAssistant,
    entry_id: str,
    runtime: SensorBridgeRuntimeData,
) -> None:
    """Entferne einen vollständig beendeten ausstehenden Runtime-Owner."""
    pending_runtimes = hass.data.get(DOMAIN, {}).get(
        _PENDING_RUNTIME_SHUTDOWNS, {}
    )
    if pending_runtimes.get(entry_id) is runtime:
        pending_runtimes.pop(entry_id, None)
    if not pending_runtimes:
        hass.data.get(DOMAIN, {}).pop(_PENDING_RUNTIME_SHUTDOWNS, None)


async def _async_retry_pending_runtime_shutdown(
    hass: HomeAssistant,
    entry: SensorBridgeConfigEntry,
    runtime: SensorBridgeRuntimeData,
) -> None:
    """Beende eine ausstehende Runtime unabhängig von einem Folgesetup."""
    entry_id = entry.entry_id
    retry_delay = 1
    try:
        while (
            hass.data.get(DOMAIN, {})
            .get(_PENDING_RUNTIME_SHUTDOWNS, {})
            .get(entry_id)
            is runtime
        ):
            platforms_unloaded = await _async_unload_runtime_platforms(
                hass, entry, runtime
            )
            runtime_shutdown = (
                platforms_unloaded
                and await _async_shutdown_runtime_with_retries(runtime)
            )
            if runtime_shutdown:
                _async_remove_pending_runtime(hass, entry_id, runtime)
                if getattr(entry, "runtime_data", None) is runtime:
                    entry.runtime_data = None
                return
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)
    finally:
        pending_tasks = hass.data.get(DOMAIN, {}).get(
            _PENDING_RUNTIME_TASKS, {}
        )
        task_owner = pending_tasks.get(entry_id)
        if (
            task_owner is not None
            and task_owner[0] is runtime
            and task_owner[1] is asyncio.current_task()
        ):
            pending_tasks.pop(entry_id, None)
        if not pending_tasks:
            hass.data.get(DOMAIN, {}).pop(_PENDING_RUNTIME_TASKS, None)


def _async_schedule_pending_runtime_cleanup(
    hass: HomeAssistant,
    entry: SensorBridgeConfigEntry,
    runtime: SensorBridgeRuntimeData,
) -> None:
    """Plane den unabhängigen Cleanup einer ausstehenden Runtime."""
    entry_id = entry.entry_id
    pending_tasks = hass.data.setdefault(DOMAIN, {}).setdefault(
        _PENDING_RUNTIME_TASKS, {}
    )
    task_owner = pending_tasks.get(entry_id)
    if (
        task_owner is not None
        and task_owner[0] is runtime
        and not task_owner[1].done()
    ):
        return
    task = hass.async_create_background_task(
        _async_retry_pending_runtime_shutdown(hass, entry, runtime),
        f"{DOMAIN} pending runtime cleanup {entry_id}",
        eager_start=False,
    )
    pending_tasks[entry_id] = (runtime, task)


async def _async_unload_runtime_platforms(
    hass: HomeAssistant,
    entry: SensorBridgeConfigEntry,
    runtime: SensorBridgeRuntimeData,
) -> bool:
    """Entlade jede noch aktive Plattform einzeln und idempotent."""
    if runtime.platforms_unloaded:
        return True
    if not runtime.pending_platforms:
        runtime.platforms_unloaded = True
        return True

    for _attempt in range(_SHUTDOWN_ATTEMPTS):
        for platform in list(runtime.pending_platforms):
            try:
                unload_ok = (
                    await hass.config_entries.async_forward_entry_unload(
                        entry, platform
                    )
                )
            except ValueError as err:
                if "was never loaded" not in str(err):
                    _LOGGER.warning(
                        "Fehler beim Entladen der Plattform %s: %s",
                        platform,
                        err,
                    )
                    continue
                unload_ok = True
            except Exception as err:
                _LOGGER.warning(
                    "Fehler beim Entladen der Plattform %s: %s",
                    platform,
                    err,
                )
                continue
            if unload_ok:
                runtime.pending_platforms.discard(platform)
            else:
                _LOGGER.warning(
                    "Plattform %s konnte nicht entladen werden", platform
                )
        if not runtime.pending_platforms:
            runtime.platforms_unloaded = True
            return True

    return False


async def _async_unload_runtime(
    hass: HomeAssistant,
    entry: SensorBridgeConfigEntry,
    runtime: SensorBridgeRuntimeData,
    *,
    allow_incomplete_shutdown: bool = False,
) -> bool:
    """Entlade Plattformen und Runtime mit wiederholbarem Fehler-Retry."""
    if not await _async_unload_runtime_platforms(hass, entry, runtime):
        return False

    shutdown_ok = await _async_shutdown_runtime_with_retries(runtime)
    if not shutdown_ok:
        _LOGGER.error(
            "Runtime-Cleanup blieb nach %d Versuchen unvollständig",
            _SHUTDOWN_ATTEMPTS,
        )
        if not allow_incomplete_shutdown:
            return False
        pending_runtimes = hass.data.setdefault(DOMAIN, {}).setdefault(
            _PENDING_RUNTIME_SHUTDOWNS, {}
        )
        pending_runtimes[entry.entry_id] = runtime
        _async_schedule_pending_runtime_cleanup(
            hass, entry, runtime
        )
    else:
        _async_remove_pending_runtime(hass, entry.entry_id, runtime)

    entry.runtime_data = None
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: SensorBridgeConfigEntry
) -> bool:
    """Set up SmartCity SensorBridge Partheland from a config entry."""
    runtime: SensorBridgeRuntimeData | None = None
    platforms_started = False
    try:
        pending_runtimes = hass.data.get(DOMAIN, {}).get(
            _PENDING_RUNTIME_SHUTDOWNS, {}
        )
        pending_runtime = pending_runtimes.get(entry.entry_id)
        if pending_runtime is not None:
            platforms_unloaded = await _async_unload_runtime_platforms(
                hass, entry, pending_runtime
            )
            runtime_shutdown = (
                platforms_unloaded
                and await _async_shutdown_runtime_with_retries(
                    pending_runtime
                )
            )
            if not runtime_shutdown:
                raise ConfigEntryNotReady(
                    "Ausstehende SensorBridge-Runtime konnte nicht beendet "
                    "werden"
                )
            _async_remove_pending_runtime(
                hass, entry.entry_id, pending_runtime
            )
            if getattr(entry, "runtime_data", None) is pending_runtime:
                entry.runtime_data = None

        previous_runtime = getattr(entry, "runtime_data", None)
        if previous_runtime is not None and not await _async_unload_runtime(
            hass, entry, previous_runtime
        ):
            raise ConfigEntryNotReady(
                "Vorherige SensorBridge-Runtime konnte nicht beendet werden"
            )

        _LOGGER.info(
            "Setting up SmartCity SensorBridge Partheland config entry: %s",
            entry.entry_id,
        )

        runtime = await _async_create_runtime(hass, entry)
        entry.runtime_data = runtime
        runtime.pending_platforms.clear()

        # Config Entry Daten loggen
        selected_devices = entry.data.get("selected_devices", [])
        selected_median_entities = entry.data.get(
            "selected_median_entities", []
        )
        _LOGGER.debug(
            "Config: selected_devices=%s, selected_median_entities=%s",
            selected_devices,
            selected_median_entities,
        )

        # Coordinator starten
        await runtime.coordinator.async_config_entry_first_refresh()

        if entry.data.get(CONF_INCLUDE_DWD_POLLEN, False):
            from .pollen import DwdPollenCoordinator

            pollen_coordinator = DwdPollenCoordinator(hass, entry)
            runtime.supplemental_coordinators[DWD_POLLEN_SOURCE] = (
                pollen_coordinator
            )
            await pollen_coordinator.async_refresh()
        for station_id, station in DWD_PRECIPITATION_STATIONS.items():
            if not entry.data.get(station["config_key"], False):
                continue
            from .precipitation import DwdPrecipitationCoordinator

            precipitation_coordinator = DwdPrecipitationCoordinator(
                hass, entry, station_id
            )
            runtime.supplemental_coordinators[station["source"]] = (
                precipitation_coordinator
            )
            await precipitation_coordinator.async_refresh()
        if entry.data.get(CONF_INCLUDE_GEOBOX_BRANDIS, False):
            from .geobox import GeoBoxBrandisCoordinator

            geobox_coordinator = GeoBoxBrandisCoordinator(hass, entry)
            runtime.supplemental_coordinators[GEOBOX_BRANDIS_SOURCE] = (
                geobox_coordinator
            )
            await geobox_coordinator.async_refresh()

        platforms_started = True
        runtime.pending_platforms = {str(platform) for platform in PLATFORMS}
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        # Nach dem (Neu-)Setup: Nicht mehr ausgewählte Entitäten/Geräte aus den Registern entfernen
        try:
            await _async_cleanup_unselected_entities_and_devices(hass, entry)
        except Exception as cleanup_err:
            _LOGGER.warning(
                "Cleanup der nicht ausgewählten Entitäten/Geräte fehlgeschlagen: %s",
                cleanup_err,
            )

        _LOGGER.info(
            (
                "SmartCity SensorBridge Partheland successfully set up with "
                "%d devices and %d median entities"
            ),
            len(selected_devices),
            len(selected_median_entities),
        )

        return True

    except Exception as err:
        rollback_ok = True
        if platforms_started:
            if runtime is not None:
                rollback_ok = await _async_unload_runtime_platforms(
                    hass, entry, runtime
                )
        elif runtime is not None:
            runtime.platforms_unloaded = True
        if runtime is not None:
            if rollback_ok and await _async_shutdown_runtime_with_retries(
                runtime
            ):
                entry.runtime_data = None
            else:
                entry.runtime_data = runtime
                pending_runtimes = hass.data.setdefault(
                    DOMAIN, {}
                ).setdefault(_PENDING_RUNTIME_SHUTDOWNS, {})
                pending_runtimes[entry.entry_id] = runtime
                _async_schedule_pending_runtime_cleanup(
                    hass, entry, runtime
                )
        if isinstance(err, UpdateFailed):
            raise ConfigEntryNotReady(
                f"SensorBridge konnte nicht gestartet werden: {err}"
            ) from err
        raise


async def async_unload_entry(
    hass: HomeAssistant, entry: SensorBridgeConfigEntry
) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading SensorBridge integration")

    runtime = entry.runtime_data
    if not await _async_unload_runtime(
        hass,
        entry,
        runtime,
        allow_incomplete_shutdown=True,
    ):
        return False

    _LOGGER.info("SensorBridge integration unloaded successfully")
    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry
) -> bool:
    """Ermöglicht das direkte Löschen eines Geräts in der Geräte-Ansicht.

    - Entfernt die Geräte-/Median-ID aus der Auswahl im Config Entry
    - Triggert ein Reload, Cleanup entfernt verbleibende Entitäten/Geräte
    - Rückgabe True erlaubt Home Assistant, das Gerät zu entfernen
    """

    try:
        # Externe ID (unsere device_id/median_id) aus den Identifiers extrahieren
        external_ids = [did for (dom, did) in device_entry.identifiers if dom == DOMAIN]
        if not external_ids:
            return False

        external_id = external_ids[0]

        data = dict(entry.data)
        changed = False
        removed_source: str | None = None

        # Aus ausgewählten Geräten entfernen
        if external_id in data.get(CONF_SELECTED_DEVICES, []):
            data[CONF_SELECTED_DEVICES] = [d for d in data.get(CONF_SELECTED_DEVICES, []) if d != external_id]
            changed = True

        # Aus ausgewählten Median-Entities entfernen
        if external_id in data.get(CONF_SELECTED_MEDIAN_ENTITIES, []):
            data[CONF_SELECTED_MEDIAN_ENTITIES] = [
                m for m in data.get(CONF_SELECTED_MEDIAN_ENTITIES, []) if m != external_id
            ]
            changed = True

        if external_id == DWD_POLLEN_DEVICE_ID:
            removed_source = DWD_POLLEN_SOURCE
            if data.get(CONF_INCLUDE_DWD_POLLEN, False):
                data[CONF_INCLUDE_DWD_POLLEN] = False
                changed = True

        for station in DWD_PRECIPITATION_STATIONS.values():
            if external_id == station["device_id"]:
                removed_source = station["source"]
                if data.get(station["config_key"], False):
                    data[station["config_key"]] = False
                    changed = True
                break
        if external_id == GEOBOX_BRANDIS_DEVICE_ID:
            removed_source = GEOBOX_BRANDIS_SOURCE
            if data.get(CONF_INCLUDE_GEOBOX_BRANDIS, False):
                data[CONF_INCLUDE_GEOBOX_BRANDIS] = False
                changed = True

        if changed:
            # 1) Config-Entry aktualisieren (damit Auswahl konsistent ist)
            hass.config_entries.async_update_entry(entry, data=data)

        if removed_source is not None:
            runtime = getattr(entry, "runtime_data", None)
            supplemental_coordinators = (
                runtime.supplemental_coordinators if runtime is not None else {}
            )
            supplemental_coordinator = supplemental_coordinators.get(
                removed_source
            )
            if supplemental_coordinator is not None:
                await supplemental_coordinator.async_shutdown()
                supplemental_coordinators.pop(removed_source, None)

        # 2) Entitäten dieses Geräts direkt entfernen (korrekte Filterung: über config_entry_id & device_id)
        entity_registry = er.async_get(hass)
        for ent_id, reg_entry in list(entity_registry.entities.items()):
            if reg_entry.config_entry_id == entry.entry_id and reg_entry.device_id == device_entry.id:
                entity_registry.async_remove(ent_id)

        # 3) Verknüpfung des Geräts zur Config Entry lösen und Gerät entfernen
        device_registry = dr.async_get(hass)
        try:
            try:
                device_registry.async_update_device(
                    device_entry.id, remove_config_entry_id=entry.entry_id
                )
            except Exception as link_err:
                _LOGGER.debug("Konnte ConfigEntry-Verknüpfung nicht lösen: %s", link_err)

            # Gerät entfernen; falls noch andere Config-Entries verknüpft sind, ignoriert Core dies
            device_registry.async_remove_device(device_entry.id)
        except Exception as dev_err:
            _LOGGER.debug("Gerät konnte nicht direkt entfernt werden: %s", dev_err)

        # 4) Ausstehende Tasks verarbeiten, UI-Update beschleunigen
        try:
            await hass.async_block_till_done()
        except Exception:
            pass

        return True

    except Exception as e:
        _LOGGER.error("Fehler beim Entfernen des Geräts über UI: %s", e)
        return False


async def _async_cleanup_unselected_entities_and_devices(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Entfernt Entitäten und Geräte dieser Integration, die nicht mehr ausgewählt sind.

    Vorgehen:
    - Ermittelt `selected_devices` und `selected_median_entities` aus dem Config Entry
    - Durchläuft die Entity Registry (nur Plattform == DOMAIN)
    - Ermittelt die externe ID über die Device-Identifiers (DOMAIN, external_id)
    - Entfernt Entitäten, deren externe ID nicht mehr ausgewählt ist
    - Entfernt anschließend verwaiste Geräte ohne verbleibende Entitäten
    """

    selected_devices = set(entry.data.get("selected_devices", []))
    selected_median = set(entry.data.get("selected_median_entities", []))
    selected_supplemental = set()
    if entry.data.get(CONF_INCLUDE_DWD_POLLEN, False):
        selected_supplemental.add(DWD_POLLEN_DEVICE_ID)
    for station in DWD_PRECIPITATION_STATIONS.values():
        if entry.data.get(station["config_key"], False):
            selected_supplemental.add(station["device_id"])
    if entry.data.get(CONF_INCLUDE_GEOBOX_BRANDIS, False):
        selected_supplemental.add(GEOBOX_BRANDIS_DEVICE_ID)

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    # 1) Nicht mehr ausgewählte Entitäten entfernen (nur solche unseres Config-Entries)
    for entity_id, reg_entry in list(entity_registry.entities.items()):
        if reg_entry.config_entry_id != entry.entry_id:
            continue

        device_entry = device_registry.async_get(reg_entry.device_id)
        if not device_entry:
            continue

        external_ids = [did for (dom, did) in device_entry.identifiers if dom == DOMAIN]
        if not external_ids:
            continue

        external_id = external_ids[0]
        is_selected = (
            (external_id in selected_devices)
            or (external_id in selected_median)
            or (external_id in selected_supplemental)
        )
        if not is_selected:
            entity_registry.async_remove(entity_id)

    # 2) Geräte ohne Entitäten entfernen
    for device_id, device_entry in list(device_registry.devices.items()):
        if not any(dom == DOMAIN for dom, _ in device_entry.identifiers):
            continue

        has_entities = any(
            (reg_entry.device_id == device_id) and (reg_entry.platform == DOMAIN)
            for reg_entry in entity_registry.entities.values()
        )

        if not has_entities:
            try:
                device_registry.async_remove_device(device_id)
            except Exception as e:
                _LOGGER.debug("Konnte Gerät %s nicht entfernen: %s", device_id, e)


async def debug_translations_service(hass: HomeAssistant, call) -> None:
    """Service zum Debug der Übersetzungen."""
    try:
        _LOGGER.info("Translation Debug Service gestartet")

        if DOMAIN not in hass.data:
            _LOGGER.error("Domain %s nicht in hass.data gefunden", DOMAIN)
            return

        config_service = next(
            (
                runtime.config_service
                for entry in hass.config_entries.async_entries(DOMAIN)
                if (runtime := getattr(entry, "runtime_data", None))
                is not None
            ),
            None,
        )
        if config_service:
            # Translation-API direkt testen
            from homeassistant.helpers.translation import async_get_translations

            translations = await async_get_translations(
                hass, hass.config.language, "entity", [DOMAIN]
            )

            _LOGGER.info("=== TRANSLATION DEBUG ===")
            _LOGGER.info("Language: %s", hass.config.language)
            _LOGGER.info("Domain: %s", DOMAIN)
            _LOGGER.info("Raw translations: %s", translations)

            # Sensor-Translations extrahieren
            sensor_translations = translations.get("sensor", {})
            _LOGGER.info("Sensor translations: %s", sensor_translations)

            # Alle Sensor-Entities finden und testen
            import homeassistant.helpers.entity_registry

            entity_registry = (
                homeassistant.helpers.entity_registry.async_get(hass)
            )

            if entity_registry:
                for entity_id, entity in entity_registry.entities.items():
                    if entity.domain == "sensor" and DOMAIN in entity_id:
                        _LOGGER.info("Entity %s:", entity_id)
                        _LOGGER.info(
                            "  - translation_key: %s",
                            getattr(entity, "translation_key", "N/A"),
                        )
                        _LOGGER.info(
                            "  - has_entity_name: %s",
                            getattr(entity, "has_entity_name", "N/A"),
                        )
                        _LOGGER.info(
                            "  - name: %s", getattr(entity, "name", "N/A")
                        )

                        # Translation für diese Entity testen
                        translation_key = getattr(
                            entity, "translation_key", None
                        )
                        if (
                            translation_key
                            and translation_key in sensor_translations
                        ):
                            _LOGGER.info(
                                "  - Translation gefunden: %s",
                                sensor_translations[translation_key],
                            )
                        else:
                            _LOGGER.warning(
                                "  - Keine Translation gefunden für key: %s",
                                translation_key,
                            )

            debug_info = await config_service.debug_translations()
            _LOGGER.info("ConfigService Debug: %s", debug_info)

        else:
            _LOGGER.error("ConfigService nicht verfügbar")

    except Exception as e:
        _LOGGER.error("Fehler im Translation Debug Service: %s", e)


async def test_translations_service(hass: HomeAssistant, call) -> None:
    """Service zum Test der Übersetzungen für alle Sensor-Entities."""
    try:
        _LOGGER.info("Translation Test Service gestartet")

        # Alle Sensor-Entities finden
        sensor_entities = []

        # Entity Registry verwenden
        entity_registry = hass.helpers.entity_registry.async_get(hass)
        if entity_registry:
            for entity_id, entity in entity_registry.entities.items():
                if entity.domain == "sensor" and DOMAIN in entity_id:
                    sensor_entities.append(entity_id)

        _LOGGER.info("Gefundene Sensor-Entities: %s", sensor_entities)

        # Translation-Tests für jede Entity ausführen
        for entity_id in sensor_entities:
            entity = hass.states.get(entity_id)
            if entity:
                friendly_name = entity.attributes.get(
                    "friendly_name", entity.name
                )
                _LOGGER.info("Entity %s: %s", entity_id, friendly_name)
            else:
                _LOGGER.warning(
                    "Entity %s nicht in States gefunden", entity_id
                )

        _LOGGER.info("Translation Test Service abgeschlossen")

    except Exception as e:
        _LOGGER.error("Fehler im Translation Test Service: %s", e)


async def debug_translation_file_service(hass: HomeAssistant, call) -> None:
    """Service zum direkten Debug der Translation-Datei."""
    try:
        _LOGGER.info("=== TRANSLATION FILE DEBUG ===")

        # Translation-Datei direkt lesen
        import json
        import os

        translation_file = os.path.join(
            hass.config.config_dir,
            "custom_components",
            "sensorbridge_partheland",
            "translations",
            "de.json",
        )

        _LOGGER.info("Translation file path: %s", translation_file)
        _LOGGER.info("File exists: %s", os.path.exists(translation_file))

        if os.path.exists(translation_file):
            with open(translation_file, "r", encoding="utf-8") as f:
                content = f.read()
                _LOGGER.info("File content length: %d", len(content))
                _LOGGER.info("File content: %s", content)

                # JSON validieren
                try:
                    data = json.loads(content)
                    _LOGGER.info("JSON is valid")
                    _LOGGER.info(
                        "Entity sensor keys: %s",
                        list(data.get("entity", {}).get("sensor", {}).keys()),
                    )
                except json.JSONDecodeError as e:
                    _LOGGER.error("JSON validation failed: %s", e)

        # HA Translation API testen
        from homeassistant.helpers.translation import async_get_translations

        translations = await async_get_translations(
            hass, hass.config.language, "entity", [DOMAIN]
        )

        _LOGGER.info("HA Translation API result: %s", translations)

    except Exception as e:
        _LOGGER.error("Fehler im Translation File Debug Service: %s", e)
