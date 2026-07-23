from __future__ import annotations

import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sensorbridge_partheland import (
    _PENDING_RUNTIME_SHUTDOWNS,
    _PENDING_RUNTIME_TASKS,
    _async_retry_pending_runtime_shutdown,
    _async_schedule_pending_runtime_cleanup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.sensorbridge_partheland.const import (
    CONF_INCLUDE_DWD_POLLEN,
    CONF_INCLUDE_DWD_PRECIPITATION_BRANDIS,
    DOMAIN,
    DWD_POLLEN_SOURCE,
    EVENT_MQTT_CONNECTED,
    EVENT_MQTT_DISCONNECTED,
    PLATFORMS,
)
from custom_components.sensorbridge_partheland.coordinator import (
    SensorBridgeCoordinator,
)
from custom_components.sensorbridge_partheland.mqtt_service import MQTTService
from custom_components.sensorbridge_partheland.runtime import (
    SensorBridgeRuntimeData,
)


def _runtime(
    coordinator: AsyncMock | None = None,
    supplemental_coordinators: dict[str, AsyncMock] | None = None,
) -> SensorBridgeRuntimeData:
    runtime = SensorBridgeRuntimeData(
        config_service=Mock(),
        coordinator=coordinator or AsyncMock(),
        supplemental_coordinators=supplemental_coordinators or {},
    )
    runtime.pending_platforms = {str(platform) for platform in PLATFORMS}
    return runtime


def _prepare_setup(hass, mocker, runtimes):
    mocker.patch(
        "custom_components.sensorbridge_partheland._async_create_runtime",
        new_callable=AsyncMock,
        side_effect=runtimes,
    )
    forward_entry_setups = mocker.patch.object(
        hass.config_entries,
        "async_forward_entry_setups",
        new_callable=AsyncMock,
    )
    mocker.patch(
        "custom_components.sensorbridge_partheland."
        "_async_cleanup_unselected_entities_and_devices",
        new_callable=AsyncMock,
    )
    return forward_entry_setups


async def test_setup_sets_entry_runtime_data(hass, mocker):
    coordinator = AsyncMock()
    runtime = _runtime(coordinator)
    _prepare_setup(hass, mocker, [runtime])
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    assert await async_setup_entry(hass, entry) is True

    assert entry.runtime_data is runtime
    assert entry.runtime_data.coordinator is coordinator
    assert entry.runtime_data.supplemental_coordinators == {}


async def test_setup_failure_cleans_started_runtime(hass, mocker):
    coordinator = AsyncMock()
    pollen_coordinator = AsyncMock()
    precipitation_coordinator = AsyncMock()
    precipitation_coordinator.async_refresh.side_effect = RuntimeError(
        "supplemental setup failed"
    )
    runtime = _runtime(coordinator)
    _prepare_setup(hass, mocker, [runtime])
    mocker.patch(
        "custom_components.sensorbridge_partheland.pollen."
        "DwdPollenCoordinator",
        return_value=pollen_coordinator,
    )
    mocker.patch(
        "custom_components.sensorbridge_partheland.precipitation."
        "DwdPrecipitationCoordinator",
        return_value=precipitation_coordinator,
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_INCLUDE_DWD_POLLEN: True,
            CONF_INCLUDE_DWD_PRECIPITATION_BRANDIS: True,
        },
    )
    entry.add_to_hass(hass)

    with pytest.raises(RuntimeError, match="supplemental setup failed"):
        await async_setup_entry(hass, entry)

    coordinator.async_shutdown.assert_awaited_once_with()
    pollen_coordinator.async_shutdown.assert_awaited_once_with()
    precipitation_coordinator.async_shutdown.assert_awaited_once_with()
    assert entry.runtime_data is None


async def test_transient_coordinator_failure_becomes_not_ready(hass, mocker):
    coordinator = AsyncMock()
    coordinator.async_config_entry_first_refresh.side_effect = UpdateFailed(
        "mqtt unavailable"
    )
    runtime = _runtime(coordinator)
    _prepare_setup(hass, mocker, [runtime])
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    with pytest.raises(ConfigEntryNotReady, match="mqtt unavailable"):
        await async_setup_entry(hass, entry)

    coordinator.async_shutdown.assert_awaited_once_with()
    assert entry.runtime_data is None


async def test_platform_setup_failure_rolls_back_complete_runtime(hass, mocker):
    coordinator = AsyncMock()
    pollen_coordinator = AsyncMock()
    runtime = _runtime(coordinator)
    forward_entry_setups = _prepare_setup(hass, mocker, [runtime])
    forward_entry_setups.side_effect = RuntimeError("platform setup failed")
    unload_platform = mocker.patch.object(
        hass.config_entries,
        "async_forward_entry_unload",
        new_callable=AsyncMock,
        return_value=True,
    )
    mocker.patch(
        "custom_components.sensorbridge_partheland.pollen."
        "DwdPollenCoordinator",
        return_value=pollen_coordinator,
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_INCLUDE_DWD_POLLEN: True},
    )
    entry.add_to_hass(hass)

    with pytest.raises(RuntimeError, match="platform setup failed"):
        await async_setup_entry(hass, entry)

    forward_entry_setups.assert_awaited_once_with(entry, PLATFORMS)
    assert unload_platform.await_count == len(PLATFORMS)
    assert {
        call.args[1] for call in unload_platform.await_args_list
    } == {str(platform) for platform in PLATFORMS}
    coordinator.async_shutdown.assert_awaited_once_with()
    pollen_coordinator.async_shutdown.assert_awaited_once_with()
    assert entry.runtime_data is None


async def test_failed_platform_unload_keeps_runtime_active(hass, mocker):
    coordinator = AsyncMock()
    supplemental = AsyncMock()
    runtime = _runtime(
        coordinator,
        {DWD_POLLEN_SOURCE: supplemental},
    )
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    entry.runtime_data = runtime
    unload_platform = mocker.patch.object(
        hass.config_entries,
        "async_forward_entry_unload",
        new_callable=AsyncMock,
        return_value=False,
    )

    assert await async_unload_entry(hass, entry) is False

    assert unload_platform.await_count == 3 * len(PLATFORMS)
    coordinator.async_shutdown.assert_not_awaited()
    supplemental.async_shutdown.assert_not_awaited()
    assert entry.runtime_data is runtime


async def test_platform_unload_is_retried_before_failed_unload(hass, mocker):
    coordinator = AsyncMock()
    runtime = _runtime(coordinator)
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    entry.runtime_data = runtime
    platform_attempts = {}

    async def _unload_platform(_entry, platform):
        platform_attempts[platform] = platform_attempts.get(platform, 0) + 1
        if platform == str(PLATFORMS[-1]):
            return platform_attempts[platform] > 1
        return True

    unload_platform = mocker.patch.object(
        hass.config_entries,
        "async_forward_entry_unload",
        new_callable=AsyncMock,
        side_effect=_unload_platform,
    )

    assert await async_unload_entry(hass, entry) is True

    assert unload_platform.await_count == len(PLATFORMS) + 1
    assert platform_attempts[str(PLATFORMS[0])] == 1
    assert platform_attempts[str(PLATFORMS[-1])] == 2
    coordinator.async_shutdown.assert_awaited_once_with()
    assert entry.runtime_data is None


async def test_successful_unload_shuts_runtime_down_once(hass, mocker):
    coordinator = AsyncMock()
    pollen_coordinator = AsyncMock()
    precipitation_coordinator = AsyncMock()
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    entry.runtime_data = _runtime(
        coordinator,
        {
            DWD_POLLEN_SOURCE: pollen_coordinator,
            "dwd_precipitation_07362": precipitation_coordinator,
        },
    )
    mocker.patch.object(
        hass.config_entries,
        "async_forward_entry_unload",
        new_callable=AsyncMock,
        return_value=True,
    )

    assert await async_unload_entry(hass, entry) is True

    coordinator.async_shutdown.assert_awaited_once_with()
    pollen_coordinator.async_shutdown.assert_awaited_once_with()
    precipitation_coordinator.async_shutdown.assert_awaited_once_with()
    assert entry.runtime_data is None


async def test_unload_retries_failed_runtime_resources_internally(
    hass, mocker
):
    coordinator = AsyncMock()
    failed_supplemental = AsyncMock()
    failed_supplemental.async_shutdown.side_effect = [
        RuntimeError("shutdown failed"),
        None,
    ]
    successful_supplemental = AsyncMock()
    runtime = _runtime(
        coordinator,
        {
            DWD_POLLEN_SOURCE: failed_supplemental,
            "dwd_precipitation_07362": successful_supplemental,
        },
    )
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    entry.runtime_data = runtime
    unload_platform = mocker.patch.object(
        hass.config_entries,
        "async_forward_entry_unload",
        new_callable=AsyncMock,
        return_value=True,
    )

    assert await async_unload_entry(hass, entry) is True

    assert unload_platform.await_count == len(PLATFORMS)
    coordinator.async_shutdown.assert_awaited_once_with()
    successful_supplemental.async_shutdown.assert_awaited_once_with()
    assert failed_supplemental.async_shutdown.await_count == 2
    assert entry.runtime_data is None


async def test_unload_does_not_enter_failed_unload_after_platforms_are_gone(
    hass, mocker
):
    coordinator = AsyncMock()
    failed_supplemental = AsyncMock()
    failed_supplemental.async_shutdown.side_effect = RuntimeError(
        "shutdown failed"
    )
    runtime = _runtime(
        coordinator,
        {DWD_POLLEN_SOURCE: failed_supplemental},
    )
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    entry.runtime_data = runtime
    unload_platform = mocker.patch.object(
        hass.config_entries,
        "async_forward_entry_unload",
        new_callable=AsyncMock,
        return_value=True,
    )
    schedule_cleanup = mocker.patch(
        "custom_components.sensorbridge_partheland."
        "_async_schedule_pending_runtime_cleanup"
    )

    assert await async_unload_entry(hass, entry) is True

    assert unload_platform.await_count == len(PLATFORMS)
    assert failed_supplemental.async_shutdown.await_count == 3
    coordinator.async_shutdown.assert_awaited_once_with()
    assert entry.runtime_data is None
    assert (
        hass.data[DOMAIN][_PENDING_RUNTIME_SHUTDOWNS][entry.entry_id]
        is runtime
    )
    schedule_cleanup.assert_called_once_with(hass, entry, runtime)

    create_runtime = mocker.patch(
        "custom_components.sensorbridge_partheland._async_create_runtime",
        new_callable=AsyncMock,
    )
    with pytest.raises(
        ConfigEntryNotReady,
        match="Ausstehende SensorBridge-Runtime",
    ):
        await async_setup_entry(hass, entry)

    assert failed_supplemental.async_shutdown.await_count == 6
    create_runtime.assert_not_awaited()
    assert (
        hass.data[DOMAIN][_PENDING_RUNTIME_SHUTDOWNS][entry.entry_id]
        is runtime
    )


async def test_pending_runtime_cleanup_retries_without_followup_setup(
    hass, mocker
):
    coordinator = AsyncMock()
    failed_supplemental = AsyncMock()
    failed_supplemental.async_shutdown.side_effect = [
        RuntimeError("shutdown failed"),
        RuntimeError("shutdown failed"),
        RuntimeError("shutdown failed"),
        None,
    ]
    runtime = _runtime(
        coordinator,
        {DWD_POLLEN_SOURCE: failed_supplemental},
    )
    runtime.platforms_unloaded = True
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    entry_id = entry.entry_id
    hass.data.setdefault(DOMAIN, {})[_PENDING_RUNTIME_SHUTDOWNS] = {
        entry_id: runtime
    }
    sleep = mocker.patch(
        "custom_components.sensorbridge_partheland.asyncio.sleep",
        new_callable=AsyncMock,
    )

    await _async_retry_pending_runtime_shutdown(hass, entry, runtime)

    assert failed_supplemental.async_shutdown.await_count == 4
    coordinator.async_shutdown.assert_awaited_once_with()
    sleep.assert_awaited_once_with(1)
    assert _PENDING_RUNTIME_SHUTDOWNS not in hass.data[DOMAIN]


def test_new_pending_runtime_replaces_stale_cleanup_task(hass, mocker):
    old_runtime = _runtime()
    new_runtime = _runtime()
    old_task = Mock()
    old_task.done.return_value = False
    new_task = Mock()
    new_task.done.return_value = False
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    entry_id = entry.entry_id
    hass.data.setdefault(DOMAIN, {})[_PENDING_RUNTIME_TASKS] = {
        entry_id: (old_runtime, old_task)
    }

    def _create_background_task(coroutine, _name, eager_start):
        coroutine.close()
        assert eager_start is False
        return new_task

    create_background_task = mocker.patch.object(
        hass,
        "async_create_background_task",
        side_effect=_create_background_task,
    )

    _async_schedule_pending_runtime_cleanup(
        hass, entry, new_runtime
    )

    create_background_task.assert_called_once()
    assert hass.data[DOMAIN][_PENDING_RUNTIME_TASKS][entry_id] == (
        new_runtime,
        new_task,
    )


async def test_setup_cleans_pending_unload_runtime_before_new_runtime(
    hass, mocker
):
    old_coordinator = AsyncMock()
    old_supplemental = AsyncMock()
    old_runtime = _runtime(
        old_coordinator,
        {DWD_POLLEN_SOURCE: old_supplemental},
    )
    old_runtime.platforms_unloaded = True
    old_runtime.coordinator_shutdown = True
    new_runtime = _runtime(AsyncMock())
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    entry.runtime_data = None
    hass.data.setdefault(DOMAIN, {})[_PENDING_RUNTIME_SHUTDOWNS] = {
        entry.entry_id: old_runtime
    }
    _prepare_setup(hass, mocker, [new_runtime])

    assert await async_setup_entry(hass, entry) is True

    old_supplemental.async_shutdown.assert_awaited_once_with()
    assert _PENDING_RUNTIME_SHUTDOWNS not in hass.data[DOMAIN]
    assert entry.runtime_data is new_runtime


async def test_setup_does_not_replace_incompletely_stopped_runtime(
    hass, mocker
):
    coordinator = AsyncMock()
    failed_supplemental = AsyncMock()
    failed_supplemental.async_shutdown.side_effect = RuntimeError(
        "shutdown failed"
    )
    runtime = _runtime(
        coordinator,
        {DWD_POLLEN_SOURCE: failed_supplemental},
    )
    runtime.platforms_unloaded = True
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    entry.runtime_data = runtime
    create_runtime = mocker.patch(
        "custom_components.sensorbridge_partheland._async_create_runtime",
        new_callable=AsyncMock,
    )

    with pytest.raises(
        ConfigEntryNotReady,
        match="Vorherige SensorBridge-Runtime",
    ):
        await async_setup_entry(hass, entry)

    assert failed_supplemental.async_shutdown.await_count == 3
    coordinator.async_shutdown.assert_awaited_once_with()
    create_runtime.assert_not_awaited()
    assert entry.runtime_data is runtime


async def test_failed_setup_schedules_incomplete_runtime_shutdown(
    hass, mocker
):
    coordinator = AsyncMock()
    coordinator.async_shutdown.side_effect = RuntimeError("shutdown failed")
    runtime = _runtime(coordinator)
    forward_entry_setups = _prepare_setup(hass, mocker, [runtime])
    forward_entry_setups.side_effect = RuntimeError("platform setup failed")
    mocker.patch.object(
        hass.config_entries,
        "async_forward_entry_unload",
        new_callable=AsyncMock,
        return_value=True,
    )
    schedule_cleanup = mocker.patch(
        "custom_components.sensorbridge_partheland."
        "_async_schedule_pending_runtime_cleanup"
    )
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    with pytest.raises(RuntimeError, match="platform setup failed"):
        await async_setup_entry(hass, entry)

    assert coordinator.async_shutdown.await_count == 3
    assert entry.runtime_data is runtime
    assert (
        hass.data[DOMAIN][_PENDING_RUNTIME_SHUTDOWNS][entry.entry_id]
        is runtime
    )
    schedule_cleanup.assert_called_once_with(hass, entry, runtime)


@pytest.mark.parametrize(
    "rollback_failure",
    [False, RuntimeError("rollback failed")],
)
async def test_failed_setup_rollback_is_retried_before_next_setup(
    hass, mocker, rollback_failure
):
    old_coordinator = AsyncMock()
    old_runtime = _runtime(old_coordinator)
    new_runtime = _runtime(AsyncMock())
    forward_entry_setups = _prepare_setup(
        hass, mocker, [old_runtime, new_runtime]
    )
    forward_entry_setups.side_effect = RuntimeError("platform setup failed")
    unload_platform = mocker.patch.object(
        hass.config_entries,
        "async_forward_entry_unload",
        new_callable=AsyncMock,
    )
    if isinstance(rollback_failure, Exception):
        unload_platform.side_effect = rollback_failure
    else:
        unload_platform.return_value = rollback_failure
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    schedule_cleanup = mocker.patch(
        "custom_components.sensorbridge_partheland."
        "_async_schedule_pending_runtime_cleanup"
    )

    with pytest.raises(RuntimeError, match="platform setup failed"):
        await async_setup_entry(hass, entry)

    assert entry.runtime_data is old_runtime
    assert old_runtime.platforms_unloaded is False
    old_coordinator.async_shutdown.assert_not_awaited()
    schedule_cleanup.assert_called_once_with(hass, entry, old_runtime)

    unload_platform.side_effect = None
    unload_platform.return_value = True
    forward_entry_setups.side_effect = None

    assert await async_setup_entry(hass, entry) is True

    assert unload_platform.await_count == 4 * len(PLATFORMS)
    old_coordinator.async_shutdown.assert_awaited_once_with()
    assert entry.runtime_data is new_runtime


async def test_coordinator_shutdown_retries_only_failed_steps(mocker):
    coordinator = object.__new__(SensorBridgeCoordinator)
    coordinator._base_shutdown_complete = False
    coordinator._mqtt_disconnect_complete = False
    coordinator._mqtt_topics = ["topic/a"]
    successful_unsub = Mock()
    retrying_unsub = Mock(
        side_effect=[RuntimeError("listener failed"), None]
    )
    coordinator._mqtt_unsubs = [successful_unsub, retrying_unsub]
    coordinator.mqtt_service = Mock(
        unsubscribe=AsyncMock(),
        disconnect=AsyncMock(
            side_effect=[RuntimeError("disconnect failed"), None]
        ),
    )
    coordinator.error_handler = Mock(handle_error=AsyncMock())
    base_shutdown = mocker.patch.object(
        DataUpdateCoordinator,
        "async_shutdown",
        new_callable=AsyncMock,
    )

    with pytest.raises(RuntimeError, match="Coordinator-Shutdown"):
        await coordinator.async_shutdown()

    await coordinator.async_shutdown()

    base_shutdown.assert_awaited_once_with()
    coordinator.mqtt_service.unsubscribe.assert_awaited_once_with("topic/a")
    assert coordinator.mqtt_service.disconnect.await_count == 2
    successful_unsub.assert_called_once_with()
    assert retrying_unsub.call_count == 2
    assert coordinator._mqtt_topics == []
    assert coordinator._mqtt_unsubs == []


async def test_coordinator_preserves_unexpected_start_error():
    coordinator = object.__new__(SensorBridgeCoordinator)
    coordinator._setup_mqtt_topics = AsyncMock(
        side_effect=RuntimeError("programming error")
    )
    coordinator.error_handler = Mock(handle_error=AsyncMock())

    with pytest.raises(RuntimeError, match="programming error"):
        await coordinator.async_config_entry_first_refresh()

    coordinator.error_handler.handle_error.assert_awaited_once()


async def test_mqtt_connection_events_are_scoped_to_entry():
    coordinator = object.__new__(SensorBridgeCoordinator)
    coordinator.entry = Mock(entry_id="entry-a")
    coordinator._sensor_data = {}
    coordinator.async_set_updated_data = Mock()

    await coordinator._on_mqtt_connected_event(
        Mock(data={"entry_id": "entry-b"})
    )
    await coordinator._on_mqtt_disconnected_event(
        Mock(data={"entry_id": "entry-b"})
    )
    coordinator.async_set_updated_data.assert_not_called()

    await coordinator._on_mqtt_connected_event(
        Mock(data={"entry_id": "entry-a"})
    )
    await coordinator._on_mqtt_disconnected_event(
        Mock(data={"entry_id": "entry-a"})
    )
    assert coordinator.async_set_updated_data.call_count == 2


async def test_mqtt_service_emits_entry_scoped_connection_event(hass):
    config_service = Mock()
    service = MQTTService(hass, config_service, "entry-a")
    service._resubscribe_all = AsyncMock()
    events = []
    remove_connected_listener = hass.bus.async_listen(
        EVENT_MQTT_CONNECTED, events.append
    )
    remove_disconnected_listener = hass.bus.async_listen(
        EVENT_MQTT_DISCONNECTED, events.append
    )
    processor = asyncio.create_task(service._process_events())

    try:
        await service._event_queue.put(("connect", None))
        await service._event_queue.put(("disconnect", None))
        for _attempt in range(20):
            await asyncio.sleep(0)
            if len(events) == 2:
                break
    finally:
        processor.cancel()
        with suppress(asyncio.CancelledError):
            await processor
        remove_connected_listener()
        remove_disconnected_listener()

    service._resubscribe_all.assert_awaited_once_with()
    assert [event.event_type for event in events] == [
        EVENT_MQTT_CONNECTED,
        EVENT_MQTT_DISCONNECTED,
    ]
    assert [event.data for event in events] == [
        {"entry_id": "entry-a"},
        {"entry_id": "entry-a"},
    ]


async def test_entries_receive_separate_runtime_objects(hass, mocker):
    first_coordinator = AsyncMock()
    second_coordinator = AsyncMock()
    first_runtime = _runtime(first_coordinator)
    second_runtime = _runtime(second_coordinator)
    _prepare_setup(hass, mocker, [first_runtime, second_runtime])
    first_entry = MockConfigEntry(domain=DOMAIN, data={})
    second_entry = MockConfigEntry(domain=DOMAIN, data={})
    first_entry.add_to_hass(hass)
    second_entry.add_to_hass(hass)

    assert await async_setup_entry(hass, first_entry) is True
    assert await async_setup_entry(hass, second_entry) is True

    assert first_entry.runtime_data is first_runtime
    assert second_entry.runtime_data is second_runtime
    assert first_entry.runtime_data is not second_entry.runtime_data
    assert first_entry.runtime_data.coordinator is first_coordinator
    assert second_entry.runtime_data.coordinator is second_coordinator
