"""
MQTT Service für SmartCity SensorBridge Partheland
HA 2025 Compliant - Reine Connection-Verwaltung
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import threading
import uuid
from typing import Any, Callable, Dict, Optional

import paho.mqtt.client as mqtt
from homeassistant.core import HomeAssistant

from .const import (
    CLIENT_ID_PREFIX,
    DOMAIN,
    EVENT_MQTT_CONNECTED,
    EVENT_MQTT_DISCONNECTED,
    MQTT_VERSION,
)
from .interfaces import ConfigServiceProtocol, MQTTServiceProtocol

_LOGGER = logging.getLogger(__name__)


class MQTTService(MQTTServiceProtocol):
    """HA 2025 MQTT Service für reine Connection-Verwaltung."""
    
    def __init__(
        self,
        hass: HomeAssistant,
        config_service: ConfigServiceProtocol,
        entry_id: str,
    ) -> None:
        """Initialisiert den MQTT Service."""
        self.hass = hass
        self.config_service = config_service
        self.entry_id = entry_id
        self.client: Optional[mqtt.Client] = None
        self._connected = False
        self._callbacks: Dict[str, Callable[[str, Any], None]] = {}
        self._active_subscriptions: set[str] = set()
        self._subscription_waiters: Dict[int, asyncio.Future[bool]] = {}
        self._subscription_results: Dict[int, bool] = {}
        self._subscription_expected_mids: set[int] = set()
        self._subscription_unregistered_mids: set[int] = set()
        self._subscription_quarantined_mids: set[int] = set()
        self._subscription_ack_lock = threading.Lock()
        self._subscription_ack_timeout = 10
        self._client_id = f"{CLIENT_ID_PREFIX}{uuid.uuid4().hex[:8]}"
        self._broker_url: Optional[str] = None
        self._broker_port: Optional[int] = None
        self._ws_path: str = "/"  # Default WebSocket path
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._event_processor_task: Optional[asyncio.Task] = None
        self._ssl_context: Optional[ssl.SSLContext] = None
        self._keepalive: int = 60
        self._reconnect_min_delay: int = 1
        self._reconnect_max_delay: int = 120
        self._subscription_lock = asyncio.Lock()
        self._connection_lock = asyncio.Lock()
        self._loop_started = False
        self._force_client_recreation = False
        self._replacing_client = False
        self._stopping = False
    
    async def connect(self) -> bool:
        """Verbindet zum MQTT-Broker."""
        async with self._connection_lock:
            if self._stopping:
                return False
            network_loop_running = self._network_loop_running()
            if (
                not self._force_client_recreation
                and network_loop_running
            ):
                return True
            if self._loop_started and not network_loop_running:
                self._loop_started = False
            if (
                self._connected
                or self._loop_started
                or self._force_client_recreation
            ):
                self._connected = False
                self._active_subscriptions.clear()

            return await self._connect_locked()

    async def _connect_locked(self) -> bool:
        """Verbindet unter exklusiver Kontrolle des Verbindungszustands."""
        try:
            # MQTT-Konfiguration laden
            mqtt_config = await self.config_service.get_mqtt_config()
            if self._stopping:
                return False

            self._broker_url = mqtt_config.get("broker_url")
            # Optional konfigurierbare Parameter mit Bounds
            try:
                self._keepalive = int(mqtt_config.get("keepalive", 60))
                self._keepalive = max(15, min(self._keepalive, 600))
            except Exception:
                self._keepalive = 60
            try:
                self._reconnect_min_delay = int(mqtt_config.get("reconnect_min_delay", 1))
                self._reconnect_max_delay = int(mqtt_config.get("reconnect_max_delay", 120))
                if self._reconnect_min_delay < 1:
                    self._reconnect_min_delay = 1
                if self._reconnect_max_delay < self._reconnect_min_delay:
                    self._reconnect_max_delay = self._reconnect_min_delay
            except Exception:
                # Defaults bleiben erhalten
                pass

            if not self._broker_url:
                _LOGGER.error("Keine Broker-URL in der Konfiguration gefunden")
                return False

            # Broker-URL parsen
            broker_host, broker_port = self._parse_broker_url(self._broker_url)
            self._broker_port = broker_port

            _LOGGER.debug("Verbinde zum MQTT-Broker: %s:%d", broker_host, broker_port)

            # Bestehenden Client bereinigen
            if self.client:
                self._replacing_client = True
                try:
                    if self._loop_started:
                        await self.hass.async_add_executor_job(
                            self.client.loop_stop
                        )
                    await self.hass.async_add_executor_job(self.client.disconnect)
                except Exception as e:
                    _LOGGER.debug("Fehler beim Bereinigen des alten Clients: %s", e)
                finally:
                    self._loop_started = False
                    self._connected = False
                    self._active_subscriptions.clear()
                    self._fail_pending_subscriptions()
                    self._replacing_client = False
            if self._stopping:
                return False

            # SSL-Context im Executor erstellen (vermeidet Blocking im Event Loop)
            if self._broker_url.startswith("wss://"):
                self._ssl_context = await self.hass.async_add_executor_job(self._create_ssl_context)
            if self._stopping:
                return False

            # MQTT Client erstellen (Callback API Version 2)
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=self._client_id,
                protocol=mqtt.MQTTv311 if MQTT_VERSION == 4 else mqtt.MQTTv5,
                transport="websockets"
            )
            with self._subscription_ack_lock:
                self._subscription_quarantined_mids.clear()
            self._force_client_recreation = False

            # Callbacks setzen
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message
            self.client.on_subscribe = self._on_subscribe

            # WebSocket-Verbindung konfigurieren
            if self._broker_url.startswith("wss://") and self._ssl_context:
                _LOGGER.debug("Konfiguriere WebSocket-Verbindung mit Pfad: %s", self._ws_path)
                try:
                    self.client.ws_set_options(path=self._ws_path)
                    self.client.tls_set_context(self._ssl_context)
                    _LOGGER.debug("WebSocket-Verbindung mit SSL-Context konfiguriert")
                except Exception as e:
                    _LOGGER.warning("Fehler bei WebSocket-Konfiguration: %s", e)
                    _LOGGER.info("Versuche Fallback-Verbindung ohne spezielle WebSocket-Konfiguration")

            # Verbindungsoptionen setzen
            self.client.reconnect_delay_set(min_delay=self._reconnect_min_delay, max_delay=self._reconnect_max_delay)

            # Keep-Alive und Timeout konfigurieren
            self.client.keepalive = self._keepalive
            self.client.max_inflight_messages_set(20)

            # Für öffentliche Broker: Keine Authentifizierung
            _LOGGER.debug("Konfiguriere Verbindung für öffentlichen MQTT-Broker")

            # Verbindung herstellen
            _LOGGER.debug("Starte MQTT-Verbindung zu %s:%d", broker_host, broker_port)
            try:
                connect_result = await self.hass.async_add_executor_job(
                    self.client.connect,
                    broker_host,
                    broker_port,
                    self._keepalive,
                )
                if self._stopping:
                    await self.hass.async_add_executor_job(self.client.disconnect)
                    return False
                if connect_result != mqtt.MQTT_ERR_SUCCESS:
                    _LOGGER.error(
                        "MQTT-Verbindungsaufbau fehlgeschlagen: %s",
                        connect_result,
                    )
                    return False
            except Exception as connect_error:
                _LOGGER.error("Fehler bei MQTT-Verbindungsaufbau: %s", connect_error)
                if "Connection refused" in str(connect_error):
                    _LOGGER.error("Verbindung verweigert - Broker möglicherweise nicht erreichbar")
                elif "timeout" in str(connect_error).lower():
                    _LOGGER.error("Verbindungs-Timeout - Netzwerkproblem oder falscher Port")
                elif "ssl" in str(connect_error).lower():
                    _LOGGER.error("SSL/TLS-Fehler - Zertifikatsproblem")
                elif "websocket" in str(connect_error).lower():
                    _LOGGER.error("WebSocket-Fehler - Prüfe URL und Pfad")
                return False

            # Loop starten
            await self.hass.async_add_executor_job(self.client.loop_start)
            self._loop_started = True
            if self._stopping:
                await self.hass.async_add_executor_job(self.client.loop_stop)
                await self.hass.async_add_executor_job(self.client.disconnect)
                self._loop_started = False
                return False

            # Event-Processor starten
            self._start_event_processor()

            _LOGGER.debug("MQTT-Verbindung erfolgreich hergestellt")
            return True

        except Exception as e:
            _LOGGER.error("Fehler beim MQTT-Verbinden: %s", e)
            return False

    def _network_loop_running(self) -> bool:
        """Prüft, ob Pahos Netzwerk-Thread tatsächlich noch läuft."""
        if not self._loop_started or self.client is None:
            return False
        thread = getattr(self.client, "_thread", None)
        return bool(thread is not None and thread.is_alive())
    
    def _create_ssl_context(self) -> ssl.SSLContext:
        """Erstellt SSL-Context im Executor (vermeidet Blocking im Event Loop)."""
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    
    def _parse_broker_url(self, broker_url: str) -> tuple[str, int]:
        """Parst die Broker-URL und gibt Host und Port zurück."""
        try:
            if broker_url.startswith("wss://"):
                _LOGGER.debug("Parse WebSocket URL: %s", broker_url)
                # WebSocket URL: wss://host:port/path
                url_parts = broker_url.replace("wss://", "").split("/", 1)
                host_port = url_parts[0].split(":")
                
                if len(host_port) == 2:
                    host = host_port[0]
                    port = int(host_port[1])
                else:
                    host = host_port[0]
                    port = 443  # Default WebSocket Port
                
                # Pfad extrahieren (falls vorhanden)
                path = "/" + url_parts[1] if len(url_parts) > 1 else "/"
                self._ws_path = path
                
                _LOGGER.debug("Parsed WebSocket: Host=%s, Port=%d, Path=%s", host, port, path)
                return host, port
            else:
                raise ValueError(f"Unsupported broker URL format: {broker_url}")
                
        except Exception as e:
            _LOGGER.error("Fehler beim Parsen der Broker-URL %s: %s", broker_url, e)
            raise ValueError(f"Invalid broker URL: {broker_url}")
    
    async def disconnect(self) -> None:
        """Trennt die MQTT-Verbindung."""
        self._stopping = True
        async with self._connection_lock:
            if self.client:
                try:
                    _LOGGER.debug("Trenne MQTT-Verbindung")

                    # Event-Processor stoppen
                    await self._stop_event_processor()

                    # Loop stoppen
                    if self._loop_started:
                        await self.hass.async_add_executor_job(
                            self.client.loop_stop
                        )

                    # Verbindung trennen
                    await self.hass.async_add_executor_job(self.client.disconnect)

                    _LOGGER.debug("MQTT-Verbindung getrennt")

                except Exception as e:
                    _LOGGER.error("Fehler beim MQTT-Trennen: %s", e)
                    raise
                finally:
                    self._connected = False
                    self._loop_started = False
                    self._active_subscriptions.clear()
                    self._fail_pending_subscriptions()
            else:
                self._connected = False
                self._loop_started = False
                self._active_subscriptions.clear()
                self._fail_pending_subscriptions()
    
    async def subscribe(self, topic: str, callback: Callable[[str, Any], None]) -> None:
        """Merkt ein Topic und abonniert es bei bestehender Verbindung."""
        self._callbacks[topic] = callback
        async with self._subscription_lock:
            if (
                not self.client
                or not self._connected
                or topic in self._active_subscriptions
            ):
                return
            await self._subscribe_topic(topic)

    async def _subscribe_topic(self, topic: str) -> None:
        """Abonniert ein vorgemerktes Topic beim Broker."""
        if not self.client or not self._connected:
            raise RuntimeError("MQTT ist nicht verbunden")

        client = self.client
        result, mid, quarantined_mid = await self.hass.async_add_executor_job(
            self._subscribe_and_track_ack, client, topic
        )
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(
                f"MQTT-Topic {topic} konnte nicht abonniert werden: {result}"
            )
        if quarantined_mid:
            self._force_client_recreation = True
            self._connected = False
            raise RuntimeError(
                "MQTT-Abonnement benötigt einen neuen Verbindungsaufbau"
            )
        if client is not self.client or not self._connected:
            self._discard_subscription_ack(mid)
            raise RuntimeError("MQTT-Verbindung wurde während des Abonnements getrennt")

        acknowledged = asyncio.get_running_loop().create_future()
        self._subscription_waiters[mid] = acknowledged
        with self._subscription_ack_lock:
            self._subscription_unregistered_mids.discard(mid)
        self._handle_subscription_result(mid)

        try:
            accepted = await asyncio.wait_for(
                acknowledged,
                timeout=self._subscription_ack_timeout,
            )
        except asyncio.TimeoutError as err:
            with self._subscription_ack_lock:
                self._subscription_quarantined_mids.add(mid)
            self._force_client_recreation = True
            self._connected = False
            raise RuntimeError(
                f"MQTT-Topic {topic} wurde vom Broker nicht bestätigt"
            ) from err
        finally:
            self._subscription_waiters.pop(mid, None)
            self._discard_subscription_ack(mid)

        if not accepted:
            raise RuntimeError(
                f"MQTT-Topic {topic} wurde vom Broker abgelehnt"
            )
        self._active_subscriptions.add(topic)
        _LOGGER.debug("Topic erfolgreich abonniert: %s (MID: %d)", topic, mid)

    def _subscribe_and_track_ack(
        self,
        client: mqtt.Client,
        topic: str,
    ) -> tuple[int, int, bool]:
        """Sendet SUBSCRIBE und registriert die MID vor einem möglichen SUBACK."""
        with self._subscription_ack_lock:
            result, mid = client.subscribe(topic, 0)
            quarantined_mid = (
                result == mqtt.MQTT_ERR_SUCCESS
                and mid in self._subscription_quarantined_mids
            )
            if result == mqtt.MQTT_ERR_SUCCESS and not quarantined_mid:
                self._subscription_expected_mids.add(mid)
                self._subscription_unregistered_mids.add(mid)
            return result, mid, quarantined_mid

    def _discard_subscription_ack(self, mid: int) -> None:
        """Entfernt alle Zustände einer abgeschlossenen SUBACK-Zuordnung."""
        with self._subscription_ack_lock:
            self._subscription_expected_mids.discard(mid)
            self._subscription_unregistered_mids.discard(mid)
            self._subscription_results.pop(mid, None)

    async def restore_subscriptions(self) -> bool:
        """Stellt alle vorgemerkten Topic-Abonnements wieder her."""
        return await self._resubscribe_all()
    
    async def unsubscribe(self, topic: str) -> None:
        """Deabonniert ein MQTT-Topic."""
        async with self._subscription_lock:
            if not self.client or not self._connected:
                self._callbacks.pop(topic, None)
                self._active_subscriptions.discard(topic)
                return

            try:
                result = await self.hass.async_add_executor_job(
                    self.client.unsubscribe, topic
                )

                if result[0] == mqtt.MQTT_ERR_SUCCESS:
                    self._callbacks.pop(topic, None)
                    self._active_subscriptions.discard(topic)
                    _LOGGER.debug("Topic erfolgreich deabonniert: %s", topic)
                else:
                    raise RuntimeError(
                        f"MQTT-Topic {topic} konnte nicht gekündigt werden: "
                        f"{result[0]}"
                    )

            except Exception as e:
                _LOGGER.error(
                    "Fehler beim Deabonnieren von Topic %s: %s", topic, e
                )
                raise
    
    @property
    def is_connected(self) -> bool:
        """Gibt zurück ob die MQTT-Verbindung aktiv ist."""
        return self._connected and self._network_loop_running()

    @property
    def subscriptions_ready(self) -> bool:
        """Gibt zurück, ob alle vorgemerkten Topics aktiv sind."""
        return self._connected and set(self._callbacks).issubset(
            self._active_subscriptions
        )

    @staticmethod
    def _reason_code_value(reason_code: Any) -> Any:
        """Gibt einen stabil vergleichbaren Paho-Reason-Code zurück."""
        value = getattr(reason_code, "value", reason_code)
        try:
            return int(value)
        except (TypeError, ValueError):
            return str(value)

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Dict, reason_code, properties=None) -> None:
        """Callback für MQTT-Verbindung (API Version 2)."""
        if client is not self.client:
            return
        if self._force_client_recreation:
            return
        if reason_code == 0:
            self._connected = True
            self._active_subscriptions.clear()
            _LOGGER.info("MQTT-Verbindung erfolgreich hergestellt")

            # Thread-sicher: Event in Queue einreihen über Event Loop
            self.hass.loop.call_soon_threadsafe(
                self._queue_event, "connect", None
            )
        else:
            self._connected = False
            # Neue API verwendet ReasonCode-Objekte statt Integer-Codes
            reason_code_value = self._reason_code_value(reason_code)
            error_messages = {
                1: "Unacceptable protocol version",
                2: "Identifier rejected",
                3: "Server unavailable",
                4: "Bad username or password",
                5: "Not authorized"
            }
            error_msg = error_messages.get(reason_code_value, f"Unknown error code: {reason_code_value}")
            _LOGGER.error("MQTT-Verbindung fehlgeschlagen: %s (Code: %s)", error_msg, reason_code_value)

            # Bei WebSocket-Verbindung zusätzliche Debug-Info
            if self._broker_url and self._broker_url.startswith("wss://"):
                _LOGGER.error("WebSocket-Verbindung fehlgeschlagen. Prüfe URL: %s, Pfad: %s",
                            self._broker_url, self._ws_path)
                if reason_code_value == 2:  # Identifier rejected
                    _LOGGER.error("Client-ID möglicherweise bereits in Verwendung - generiere neue ID")
                    # Neue Client-ID generieren für nächsten Versuch
                    self._client_id = f"{CLIENT_ID_PREFIX}{uuid.uuid4().hex[:8]}"
    
    def _on_disconnect(self, client: mqtt.Client, userdata: Any, flags, reason_code, properties=None) -> None:
        """Callback für MQTT-Trennung (API Version 2)."""
        if client is not self.client:
            return
        if self._replacing_client:
            return
        self._connected = False
        self._active_subscriptions.clear()
        self.hass.loop.call_soon_threadsafe(
            self._fail_pending_subscriptions
        )
        # Freundlichere Fehlermeldung für gängige Gründe
        if reason_code == 0:
            _LOGGER.info("MQTT-Verbindung ordnungsgemäß getrennt")
        else:
            # Neue API verwendet ReasonCode-Objekte statt Integer-Codes
            reason_code_value = self._reason_code_value(reason_code)
            reason_map = {
                getattr(mqtt, "MQTT_ERR_CONN_LOST", 7): "Verbindung verloren",
                getattr(mqtt, "MQTT_ERR_NO_CONN", 4): "Keine Verbindung",
                getattr(mqtt, "MQTT_ERR_PROTOCOL", 2): "Protokollfehler",
                getattr(mqtt, "MQTT_ERR_INVAL", 3): "Ungültiger Zustand",
            }
            msg = reason_map.get(reason_code_value, f"RC: {reason_code_value}")
            _LOGGER.warning("MQTT-Verbindung unerwartet getrennt (%s)", msg)
        
        # Thread-sicher: Event in Queue einreihen über Event Loop
        if not self._stopping:
            self.hass.loop.call_soon_threadsafe(
                self._queue_event, "disconnect", reason_code
            )

    def _on_subscribe(
        self,
        client: mqtt.Client,
        userdata: Any,
        mid: int,
        reason_codes: list[Any],
        properties: Any = None,
    ) -> None:
        """Verarbeitet die Bestätigung eines Topic-Abonnements."""
        if client is not self.client:
            return
        values = [self._reason_code_value(code) for code in reason_codes]
        accepted = bool(values) and all(
            isinstance(value, int) and value < 128 for value in values
        )
        with self._subscription_ack_lock:
            if mid not in self._subscription_expected_mids:
                return
            self._subscription_results[mid] = accepted
        self.hass.loop.call_soon_threadsafe(
            self._handle_subscription_result,
            mid,
        )

    def _handle_subscription_result(self, mid: int) -> None:
        """Ordnet eine SUBACK-Bestätigung dem wartenden Abonnement zu."""
        waiter = self._subscription_waiters.get(mid)
        with self._subscription_ack_lock:
            if mid in self._subscription_unregistered_mids:
                return
            if mid not in self._subscription_results:
                return
            accepted = self._subscription_results.pop(mid)
            self._subscription_expected_mids.discard(mid)
        if waiter is None or waiter.done():
            return
        waiter.set_result(accepted)

    def _fail_pending_subscriptions(self) -> None:
        """Beendet wartende Abonnements nach einem Verbindungsabbruch."""
        for waiter in self._subscription_waiters.values():
            if not waiter.done():
                waiter.set_result(False)
        with self._subscription_ack_lock:
            self._subscription_quarantined_mids.update(
                self._subscription_expected_mids
            )
            self._subscription_results.clear()
            self._subscription_expected_mids.clear()
            self._subscription_unregistered_mids.clear()
    
    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        """Callback für MQTT-Nachrichten."""
        topic = msg.topic
        payload = msg.payload
        
        # Debug-Logging für MQTT-Nachrichten (nur bei Debug-Level)
        _LOGGER.debug("MQTT-Nachricht empfangen: Topic=%s, Payload-Length=%d", topic, len(payload))
        
        # Thread-sicher: Callback über Event Loop aufrufen
        if topic in self._callbacks:
            try:
                _LOGGER.debug("Rufe Callback für Topic %s auf", topic)
                # WICHTIG: Callback direkt aufrufen, nicht als Coroutine
                callback = self._callbacks[topic]
                self.hass.loop.call_soon_threadsafe(
                    lambda: self._execute_callback_safe(callback, topic, payload)
                )
            except Exception as e:
                _LOGGER.error("Fehler im Topic-Callback für %s: %s", topic, e)
        else:
            _LOGGER.debug("Kein Callback für Topic %s registriert", topic)

    async def _resubscribe_all(self) -> bool:
        """Abonniert alle zuvor registrierten Topics nach einem Reconnect erneut."""
        async with self._subscription_lock:
            if not self.client or not self._connected:
                return False
            if not self._callbacks:
                return True
            success = True
            for topic in list(self._callbacks.keys()):
                try:
                    if topic not in self._active_subscriptions:
                        await self._subscribe_topic(topic)
                except Exception as e:
                    success = False
                    _LOGGER.error(
                        "Fehler bei Re-Subscription für %s: %s", topic, e
                    )
            return success and self.subscriptions_ready
    
    def _execute_callback_safe(self, callback: Callable[[str, Any], None], topic: str, payload: Any) -> None:
        """Führt Callback sicher aus (vermeidet Coroutine-Probleme)."""
        try:
            # Prüfen ob Callback eine Coroutine ist
            if asyncio.iscoroutinefunction(callback):
                _LOGGER.warning("Callback für Topic %s ist eine Coroutine - wird ignoriert", topic)
                return
            
            # Synchrone Callback ausführen
            callback(topic, payload)
            
        except Exception as e:
            _LOGGER.error("Fehler bei Callback-Ausführung für Topic %s: %s", topic, e)
    
    def _queue_event(self, event_type: str, event_data: Any) -> None:
        """Thread-sicher: Event in Queue einreihen."""
        try:
            self._event_queue.put_nowait((event_type, event_data))
        except asyncio.QueueFull:
            _LOGGER.warning("Event-Queue voll, ignoriere %s-Event", event_type)
    
    def _start_event_processor(self) -> None:
        """Startet den Event-Processor."""
        if self._event_processor_task and not self._event_processor_task.done():
            return
        
        self._event_processor_task = self.hass.async_create_background_task(
            self._process_events(),
            f"{DOMAIN} MQTT events {self.entry_id}",
            eager_start=False,
        )
        _LOGGER.debug("Event-Processor gestartet")
    
    async def _stop_event_processor(self) -> None:
        """Stoppt den Event-Processor."""
        task = self._event_processor_task
        if task is None:
            return
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._event_processor_task is task:
            self._event_processor_task = None
        _LOGGER.debug("Event-Processor beendet")
    
    async def _process_events(self) -> None:
        """Verarbeitet Events aus der Queue."""
        try:
            while True:
                event_type = None
                try:
                    # Event aus Queue holen
                    event_type, event_data = await asyncio.wait_for(
                        self._event_queue.get(), timeout=1.0
                    )
                    
                    # Event verarbeiten - mit robusteren Null-Checks
                    if event_type == "connect":
                        if self.hass is not None and hasattr(self.hass, 'bus') and self.hass.bus is not None:
                            try:
                                if await self.restore_subscriptions():
                                    self.hass.bus.async_fire(
                                        EVENT_MQTT_CONNECTED,
                                        {"entry_id": self.entry_id},
                                    )
                                else:
                                    _LOGGER.warning(
                                        "MQTT verbunden, aber Topics nicht "
                                        "vollständig abonniert"
                                    )
                            except Exception as e:
                                _LOGGER.error("Fehler beim Firen des Connect-Events: %s", e)
                        else:
                            _LOGGER.warning("Home Assistant Bus nicht verfügbar für Connect-Event")
                    elif event_type == "disconnect":
                        if self.hass is not None and hasattr(self.hass, 'bus') and self.hass.bus is not None:
                            try:
                                self.hass.bus.async_fire(
                                    EVENT_MQTT_DISCONNECTED,
                                    {"entry_id": self.entry_id},
                                )
                            except Exception as e:
                                _LOGGER.error("Fehler beim Firen des Disconnect-Events: %s", e)
                        else:
                            _LOGGER.warning("Home Assistant Bus nicht verfügbar für Disconnect-Event")
                    else:
                        _LOGGER.warning("Unbekannter Event-Typ: %s", event_type)
                    
                    # Event als verarbeitet markieren
                    self._event_queue.task_done()
                    
                except asyncio.TimeoutError:
                    # Timeout - weiter machen
                    continue
                except Exception as e:
                    _LOGGER.error("Fehler beim Verarbeiten von Event %s: %s", 
                                event_type or "unbekannt", e)
                    
        except asyncio.CancelledError:
            _LOGGER.debug("Event-Processor beendet")
        except Exception as e:
            _LOGGER.error("Event-Processor Fehler: %s", e)
