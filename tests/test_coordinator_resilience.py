from __future__ import annotations

import asyncio
import threading
from contextlib import suppress
from unittest.mock import AsyncMock, Mock, call, patch

import paho.mqtt.client as mqtt
import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sensorbridge_partheland.const import (
    CONF_SELECTED_DEVICES,
    CONF_SELECTED_MEDIAN_ENTITIES,
    DOMAIN,
)
from custom_components.sensorbridge_partheland.coordinator import (
    SensorBridgeCoordinator,
)
from custom_components.sensorbridge_partheland.mqtt_service import MQTTService


class UnhashableReasonCode:
    __hash__ = None
    value = 7

    def __eq__(self, other):
        return other == self.value


class RecoveringMQTTService:
    def __init__(self) -> None:
        self.connection_attempts = 0
        self.callbacks = {}
        self.active_subscriptions = set()
        self._connected = False

    async def connect(self) -> bool:
        self.connection_attempts += 1
        self._connected = self.connection_attempts >= 2
        return self._connected

    async def disconnect(self) -> None:
        self._connected = False
        self.active_subscriptions.clear()

    async def subscribe(self, topic, callback) -> None:
        self.callbacks[topic] = callback

    async def unsubscribe(self, topic) -> None:
        self.callbacks.pop(topic, None)
        self.active_subscriptions.discard(topic)

    async def restore_subscriptions(self) -> bool:
        if not self._connected:
            return False
        self.active_subscriptions = set(self.callbacks)
        return True

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def subscriptions_ready(self) -> bool:
        return self._connected and set(self.callbacks).issubset(
            self.active_subscriptions
        )


def _coordinator(hass, entry, config_service, mqtt_service):
    return SensorBridgeCoordinator(
        hass=hass,
        entry=entry,
        config_service=config_service,
        mqtt_service=mqtt_service,
        parser_service=Mock(),
        entity_factory=Mock(),
        error_handler=Mock(handle_error=AsyncMock()),
    )


async def _wait_for_subscribe_calls(client, expected_count):
    for _attempt in range(50):
        if client.subscribe.call_count >= expected_count:
            return
        await asyncio.sleep(0)
    raise AssertionError(
        f"Erwartete {expected_count} Subscribe-Aufrufe, "
        f"erhielt {client.subscribe.call_count}"
    )


async def _wait_for_subscription_waiter(service, mid):
    for _attempt in range(50):
        if mid in service._subscription_waiters:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"Kein Subscription-Waiter für MID {mid}")


async def test_initial_mqtt_outage_recovers_without_entry_reload(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SELECTED_DEVICES: ["device-a"]},
    )
    entry.add_to_hass(hass)
    config_service = Mock(
        get_device_by_id=AsyncMock(
            return_value={"topic_pattern": "topic/a"}
        ),
        get_mqtt_config=AsyncMock(return_value={"keepalive": 60}),
        get_availability_config=AsyncMock(return_value={}),
    )
    mqtt_service = RecoveringMQTTService()
    coordinator = _coordinator(hass, entry, config_service, mqtt_service)

    await coordinator.async_start()

    assert coordinator.last_update_success is False
    assert mqtt_service.callbacks == {
        "topic/a": coordinator._mqtt_message_wrapper
    }

    await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert mqtt_service.connection_attempts == 2
    assert mqtt_service.active_subscriptions == {"topic/a"}
    await coordinator.async_shutdown()


async def test_mqtt_update_failure_keeps_old_data_and_reports_failure(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SELECTED_DEVICES: ["device-a"]},
    )
    entry.add_to_hass(hass)
    config_service = Mock(
        get_device_by_id=AsyncMock(
            return_value={"topic_pattern": "topic/a"}
        ),
        get_mqtt_config=AsyncMock(return_value={"keepalive": 60}),
        get_availability_config=AsyncMock(return_value={}),
    )
    mqtt_service = RecoveringMQTTService()
    coordinator = _coordinator(hass, entry, config_service, mqtt_service)
    coordinator._sensor_data = {"device-a": {"temperature": 20}}

    await coordinator.async_start()

    assert coordinator.last_update_success is False
    assert coordinator.data == {"device-a": {"temperature": 20}}
    await coordinator.async_shutdown()


async def test_mqtt_topic_setup_is_idempotent_and_deduplicated(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SELECTED_DEVICES: ["device-a", "device-b"],
            CONF_SELECTED_MEDIAN_ENTITIES: ["median-a"],
        },
    )
    entry.add_to_hass(hass)
    config_service = Mock(
        get_device_by_id=AsyncMock(
            side_effect=[
                {"topic_pattern": "topic/a"},
                {"topic_pattern": "topic/b"},
                {"topic_pattern": "topic/a"},
                {"topic_pattern": "topic/b"},
            ]
        ),
        get_median_entities=AsyncMock(
            return_value=[
                {"id": "median-a", "topic_pattern": "topic/a"}
            ]
        ),
    )
    coordinator = _coordinator(
        hass, entry, config_service, RecoveringMQTTService()
    )

    await coordinator._setup_mqtt_topics()
    await coordinator._setup_mqtt_topics()

    assert coordinator._mqtt_topics == ["topic/a", "topic/b"]


async def test_no_mqtt_topics_skips_broker_connection(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    config_service = Mock(
        get_mqtt_config=AsyncMock(return_value={"keepalive": 60}),
        get_availability_config=AsyncMock(return_value={}),
    )
    mqtt_service = Mock(
        connect=AsyncMock(),
        disconnect=AsyncMock(),
        subscribe=AsyncMock(),
        unsubscribe=AsyncMock(),
        is_connected=False,
        subscriptions_ready=False,
    )
    coordinator = _coordinator(hass, entry, config_service, mqtt_service)

    await coordinator.async_start()

    assert coordinator.last_update_success is True
    mqtt_service.connect.assert_not_awaited()
    await coordinator.async_shutdown()


async def test_mqtt_connect_event_subscribes_each_topic_once(hass):
    service = MQTTService(hass, Mock(), "entry-a")
    client = Mock()
    client.subscribe.side_effect = [
        (mqtt.MQTT_ERR_SUCCESS, 1),
        (mqtt.MQTT_ERR_SUCCESS, 2),
    ]
    service.client = client
    service._connected = True
    service._callbacks = {
        "topic/a": Mock(),
        "topic/b": Mock(),
    }
    processor = asyncio.create_task(service._process_events())

    try:
        await service._event_queue.put(("connect", None))
        await _wait_for_subscribe_calls(client, 1)
        service._on_subscribe(client, None, 1, [0])
        await _wait_for_subscribe_calls(client, 2)
        service._on_subscribe(client, None, 2, [0])
        for _attempt in range(50):
            if service.subscriptions_ready:
                break
            await asyncio.sleep(0)
    finally:
        processor.cancel()
        with suppress(asyncio.CancelledError):
            await processor

    assert client.subscribe.call_args_list == [
        call("topic/a", 0),
        call("topic/b", 0),
    ]


async def test_failed_resubscription_remains_retryable(hass):
    service = MQTTService(hass, Mock(), "entry-a")
    client = Mock()
    client.subscribe.side_effect = [
        (mqtt.MQTT_ERR_NO_CONN, 1),
        (mqtt.MQTT_ERR_SUCCESS, 2),
    ]
    service.client = client
    service._connected = True
    service._callbacks = {"topic/a": Mock()}

    assert await service.restore_subscriptions() is False
    assert service.subscriptions_ready is False
    retry = asyncio.create_task(service.restore_subscriptions())
    await _wait_for_subscribe_calls(client, 2)
    service._on_subscribe(client, None, 2, [0])
    assert await retry is True
    assert service.subscriptions_ready is True

    assert await service.restore_subscriptions() is True
    assert client.subscribe.call_count == 2


async def test_parallel_resubscription_subscribes_topic_once(hass):
    service = MQTTService(hass, Mock(), "entry-a")
    client = Mock()
    client.subscribe.return_value = (mqtt.MQTT_ERR_SUCCESS, 1)
    service.client = client
    service._connected = True
    service._callbacks = {"topic/a": Mock()}

    restore = asyncio.gather(
        service.restore_subscriptions(),
        service.restore_subscriptions(),
    )
    await _wait_for_subscribe_calls(client, 1)
    service._on_subscribe(client, None, 1, [0])
    assert await restore == [True, True]

    client.subscribe.assert_called_once_with("topic/a", 0)


async def test_rejected_suback_remains_retryable(hass):
    service = MQTTService(hass, Mock(), "entry-a")
    client = Mock()
    client.subscribe.side_effect = [
        (mqtt.MQTT_ERR_SUCCESS, 1),
        (mqtt.MQTT_ERR_SUCCESS, 2),
    ]
    service.client = client
    service._connected = True
    service._callbacks = {"topic/a": Mock()}

    rejected = asyncio.create_task(service.restore_subscriptions())
    await _wait_for_subscribe_calls(client, 1)
    service._on_subscribe(client, None, 1, [135])
    assert await rejected is False
    assert service.subscriptions_ready is False

    accepted = asyncio.create_task(service.restore_subscriptions())
    await _wait_for_subscribe_calls(client, 2)
    service._on_subscribe(client, None, 2, [0])
    assert await accepted is True
    assert service.subscriptions_ready is True


async def test_late_suback_after_timeout_is_not_reused(hass):
    service = MQTTService(hass, Mock(), "entry-a")
    service._subscription_ack_timeout = 0.01
    client = Mock()
    client.subscribe.side_effect = [
        (mqtt.MQTT_ERR_SUCCESS, 1),
        (mqtt.MQTT_ERR_SUCCESS, 1),
    ]
    service.client = client
    service._connected = True
    service._loop_started = True
    service._callbacks = {"topic/a": Mock()}

    assert await service.restore_subscriptions() is False
    service._on_subscribe(client, None, 1, [0])
    await asyncio.sleep(0)

    service._connected = True
    retry = asyncio.create_task(service.restore_subscriptions())
    await _wait_for_subscribe_calls(client, 2)
    assert await retry is False
    service._on_subscribe(client, None, 1, [0])
    await asyncio.sleep(0)
    assert service.subscriptions_ready is False
    assert service._subscription_results == {}


async def test_late_suback_after_disconnect_is_not_reused(hass):
    service = MQTTService(hass, Mock(), "entry-a")
    client = Mock()
    client.subscribe.side_effect = [
        (mqtt.MQTT_ERR_SUCCESS, 1),
        (mqtt.MQTT_ERR_SUCCESS, 1),
    ]
    service.client = client
    service._connected = True
    service._loop_started = True
    service._callbacks = {"topic/a": Mock()}

    pending = asyncio.create_task(service.restore_subscriptions())
    await _wait_for_subscribe_calls(client, 1)
    await _wait_for_subscription_waiter(service, 1)
    service._fail_pending_subscriptions()
    assert await pending is False
    service._on_subscribe(client, None, 1, [0])
    await asyncio.sleep(0)

    retry = asyncio.create_task(service.restore_subscriptions())
    await _wait_for_subscribe_calls(client, 2)
    assert await retry is False
    service._on_subscribe(client, None, 1, [0])
    await asyncio.sleep(0)
    assert service.subscriptions_ready is False
    assert service._subscription_results == {}


async def test_coordinator_reconnects_when_paho_thread_died(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    config_service = Mock(
        get_mqtt_config=AsyncMock(return_value={}),
    )
    service = MQTTService(hass, config_service, entry.entry_id)
    service.client = Mock()
    service.client._thread = Mock()
    service.client._thread.is_alive.return_value = False
    service._connected = True
    service._loop_started = True
    coordinator = _coordinator(hass, entry, config_service, service)
    coordinator._mqtt_topics = {"topic/a"}

    with pytest.raises(UpdateFailed, match="MQTT nicht verbunden"):
        await coordinator._async_update_data()

    config_service.get_mqtt_config.assert_awaited_once_with()
    assert service.is_connected is False


async def test_unexpected_mqtt_start_error_propagates(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_SELECTED_DEVICES: ["device-a"]},
    )
    entry.add_to_hass(hass)
    config_service = Mock(
        get_device_by_id=AsyncMock(
            return_value={"topic_pattern": "topic/a"}
        ),
        get_mqtt_config=AsyncMock(return_value={"keepalive": 60}),
        get_availability_config=AsyncMock(return_value={}),
    )
    mqtt_service = Mock(
        connect=AsyncMock(),
        disconnect=AsyncMock(),
        subscribe=AsyncMock(),
        unsubscribe=AsyncMock(),
        restore_subscriptions=AsyncMock(
            side_effect=RuntimeError("subscription bug")
        ),
        is_connected=True,
        subscriptions_ready=False,
    )
    coordinator = _coordinator(
        hass, entry, config_service, mqtt_service
    )

    try:
        await coordinator.async_start()
    except RuntimeError as err:
        assert str(err) == "subscription bug"
    else:
        raise AssertionError("unexpected MQTT error was swallowed")

    await coordinator.async_shutdown()


def test_unhashable_paho_disconnect_reason_is_handled(hass):
    service = MQTTService(hass, Mock(), "entry-a")
    client = Mock()
    service.client = client
    service._connected = True

    service._on_disconnect(
        client,
        None,
        {},
        UnhashableReasonCode(),
    )

    assert service.is_connected is False


async def test_mqtt_event_processor_stops_cleanly(hass):
    service = MQTTService(hass, Mock(), "entry-a")

    service._start_event_processor()
    task = service._event_processor_task

    assert task is not None
    assert task.done() is False

    await service._stop_event_processor()

    assert task.done() is True
    assert service._event_processor_task is None


async def test_dead_paho_loop_does_not_block_new_connect_attempt(hass):
    config_service = Mock(
        get_mqtt_config=AsyncMock(return_value={})
    )
    service = MQTTService(hass, config_service, "entry-a")
    service.client = Mock()
    service.client._thread = Mock()
    service.client._thread.is_alive.return_value = False
    service._loop_started = True
    service._connected = True

    assert await service.connect() is False

    config_service.get_mqtt_config.assert_awaited_once_with()
    assert service._loop_started is False
    assert service.is_connected is False


async def test_disconnect_during_connect_does_not_restart_runtime(hass):
    connect_started = threading.Event()
    finish_connect = threading.Event()
    client = Mock()

    def blocking_connect(*args):
        connect_started.set()
        assert finish_connect.wait(timeout=5)
        return mqtt.MQTT_ERR_SUCCESS

    client.connect.side_effect = blocking_connect
    config_service = Mock(
        get_mqtt_config=AsyncMock(
            return_value={
                "broker_url": "wss://mqtt.example.test/mqtt",
                "keepalive": 37,
            }
        )
    )
    service = MQTTService(hass, config_service, "entry-a")

    with patch(
        "custom_components.sensorbridge_partheland.mqtt_service.mqtt.Client",
        return_value=client,
    ):
        connect_task = hass.async_create_task(service.connect())
        assert await hass.async_add_executor_job(connect_started.wait, 2)

        disconnect_task = hass.async_create_task(service.disconnect())
        await asyncio.sleep(0)
        assert service._stopping is True
        finish_connect.set()

        assert await connect_task is False
        await disconnect_task

    client.connect.assert_called_once_with("mqtt.example.test", 443, 37)
    client.loop_start.assert_not_called()
    assert service._loop_started is False
    assert service.is_connected is False
    assert service._event_processor_task is None
