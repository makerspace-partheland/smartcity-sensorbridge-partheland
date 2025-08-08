"""
MQTT Service für SmartCity SensorBridge Partheland
HA 2025 Compliant - Reine Connection-Verwaltung
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable, Dict, Optional

import paho.mqtt.client as mqtt
from homeassistant.core import HomeAssistant

from .const import (
    MQTT_VERSION, CLIENT_ID_PREFIX,
    EVENT_MQTT_CONNECTED, EVENT_MQTT_DISCONNECTED
)
from .interfaces import MQTTServiceProtocol, ConfigServiceProtocol

import ssl

_LOGGER = logging.getLogger(__name__)


class MQTTService(MQTTServiceProtocol):
    """HA 2025 MQTT Service für reine Connection-Verwaltung."""
    
    def __init__(self, hass: HomeAssistant, config_service: ConfigServiceProtocol) -> None:
        """Initialisiert den MQTT Service."""
        self.hass = hass
        self.config_service = config_service
        self.client: Optional[mqtt.Client] = None
        self._connected = False
        self._callbacks: Dict[str, Callable[[str, Any], None]] = {}
        self._client_id = f"{CLIENT_ID_PREFIX}{uuid.uuid4().hex[:8]}"
        self._reconnect_task: Optional[asyncio.Task] = None
        self._reconnect_delay = 3  # Kürzerer Delay für öffentliche Broker
        self._broker_url: Optional[str] = None
        self._broker_port: Optional[int] = None
        self._ws_path: str = "/"  # Default WebSocket path
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._event_processor_task: Optional[asyncio.Task] = None
        self._ssl_context: Optional[ssl.SSLContext] = None
    
    async def connect(self) -> bool:
        """Verbindet zum MQTT-Broker."""
        try:
            # MQTT-Konfiguration laden
            mqtt_config = await self.config_service.get_mqtt_config()
            self._broker_url = mqtt_config.get("broker_url")
            
            if not self._broker_url:
                _LOGGER.error("Keine Broker-URL in der Konfiguration gefunden")
                return False
            
            # Broker-URL parsen
            broker_host, broker_port = self._parse_broker_url(self._broker_url)
            self._broker_port = broker_port
            
            _LOGGER.debug("Verbinde zum MQTT-Broker: %s:%d", broker_host, broker_port)
            
            # Bestehenden Client bereinigen
            if self.client:
                try:
                    await self.hass.async_add_executor_job(self.client.loop_stop)
                    await self.hass.async_add_executor_job(self.client.disconnect)
                except Exception as e:
                    _LOGGER.debug("Fehler beim Bereinigen des alten Clients: %s", e)
            
            # SSL-Context im Executor erstellen (vermeidet Blocking im Event Loop)
            if self._broker_url.startswith("wss://"):
                self._ssl_context = await self.hass.async_add_executor_job(self._create_ssl_context)
            
            # MQTT Client erstellen
            self.client = mqtt.Client(
                client_id=self._client_id,
                protocol=mqtt.MQTTv311 if MQTT_VERSION == 4 else mqtt.MQTTv5,
                transport="websockets"
            )
            
            # Callbacks setzen
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message
            
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
            self.client.reconnect_delay_set(min_delay=1, max_delay=120)
            
            # Keep-Alive und Timeout konfigurieren
            self.client.keepalive = 60
            self.client.max_inflight_messages_set(20)
            
            # Für öffentliche Broker: Keine Authentifizierung
            _LOGGER.debug("Konfiguriere Verbindung für öffentlichen MQTT-Broker")
            
            # Verbindung herstellen
            _LOGGER.debug("Starte MQTT-Verbindung zu %s:%d", broker_host, broker_port)
            try:
                await self.hass.async_add_executor_job(
                    self.client.connect, broker_host, broker_port, 60
                )
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
            
            # Event-Processor starten
            self._start_event_processor()
            
            _LOGGER.debug("MQTT-Verbindung erfolgreich hergestellt")
            return True
            
        except Exception as e:
            _LOGGER.error("Fehler beim MQTT-Verbinden: %s", e)
            return False
    
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
        if self.client:
            try:
                _LOGGER.debug("Trenne MQTT-Verbindung")
                
                # Event-Processor stoppen
                self._stop_event_processor()
                
                # Reconnect-Task stoppen
                if self._reconnect_task and not self._reconnect_task.done():
                    self._reconnect_task.cancel()
                
                # Loop stoppen
                await self.hass.async_add_executor_job(self.client.loop_stop)
                
                # Verbindung trennen
                await self.hass.async_add_executor_job(self.client.disconnect)
                
                self._connected = False
                _LOGGER.debug("MQTT-Verbindung getrennt")
                
            except Exception as e:
                _LOGGER.error("Fehler beim MQTT-Trennen: %s", e)
    
    async def subscribe(self, topic: str, callback: Callable[[str, Any], None]) -> None:
        """Abonniert ein MQTT-Topic."""
        try:
            if not self.client:
                _LOGGER.warning("MQTT-Client nicht verfügbar, kann Topic nicht abonnieren: %s", topic)
                return
            
            # Warten bis Verbindung hergestellt ist (max 10 Sekunden)
            max_wait = 10
            wait_time = 0
            while not self._connected and wait_time < max_wait:
                await asyncio.sleep(0.1)
                wait_time += 0.1
            
            if not self._connected:
                _LOGGER.warning("MQTT-Verbindung nicht hergestellt nach %d Sekunden, kann Topic nicht abonnieren: %s", max_wait, topic)
                return
            
            # Callback registrieren
            self._callbacks[topic] = callback
            
            # Topic abonnieren
            result, mid = await self.hass.async_add_executor_job(
                self.client.subscribe, topic, 0
            )
            
            if result == mqtt.MQTT_ERR_SUCCESS:
                _LOGGER.debug("Topic erfolgreich abonniert: %s (MID: %d)", topic, mid)
            else:
                _LOGGER.error("Fehler beim Abonnieren von Topic %s: %d", topic, result)
                
        except Exception as e:
            _LOGGER.error("Fehler beim Abonnieren von Topic %s: %s", topic, e)
    
    async def unsubscribe(self, topic: str) -> None:
        """Deabonniert ein MQTT-Topic."""
        if not self.client or not self._connected:
            return
        
        try:
            # Topic deabonnieren
            result = await self.hass.async_add_executor_job(
                self.client.unsubscribe, topic
            )
            
            if result[0] == mqtt.MQTT_ERR_SUCCESS:
                self._callbacks.pop(topic, None)
                _LOGGER.debug("Topic erfolgreich deabonniert: %s", topic)
            else:
                _LOGGER.error("Fehler beim Deabonnieren von Topic %s: %s", topic, result[0])
                
        except Exception as e:
            _LOGGER.error("Fehler beim Deabonnieren von Topic %s: %s", topic, e)
    
    @property
    def is_connected(self) -> bool:
        """Gibt zurück ob die MQTT-Verbindung aktiv ist."""
        return self._connected
    
    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Dict, rc: int) -> None:
        """Callback für MQTT-Verbindung."""
        if rc == 0:
            self._connected = True
            _LOGGER.info("MQTT-Verbindung erfolgreich hergestellt")
            
            # Thread-sicher: Event in Queue einreihen über Event Loop
            self.hass.loop.call_soon_threadsafe(
                self._queue_event, "connect", None
            )
        else:
            self._connected = False
            error_messages = {
                1: "Unacceptable protocol version",
                2: "Identifier rejected", 
                3: "Server unavailable",
                4: "Bad username or password",
                5: "Not authorized"
            }
            error_msg = error_messages.get(rc, f"Unknown error code: {rc}")
            _LOGGER.error("MQTT-Verbindung fehlgeschlagen: %s (Code: %d)", error_msg, rc)
            
            # Bei WebSocket-Verbindung zusätzliche Debug-Info
            if self._broker_url and self._broker_url.startswith("wss://"):
                _LOGGER.error("WebSocket-Verbindung fehlgeschlagen. Prüfe URL: %s, Pfad: %s", 
                            self._broker_url, self._ws_path)
                if rc == 2:  # Identifier rejected
                    _LOGGER.error("Client-ID möglicherweise bereits in Verwendung - generiere neue ID")
                    # Neue Client-ID generieren für nächsten Versuch
                    self._client_id = f"{CLIENT_ID_PREFIX}{uuid.uuid4().hex[:8]}"
    
    def _on_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        """Callback für MQTT-Trennung."""
        self._connected = False
        
        if rc == 0:
            _LOGGER.info("MQTT-Verbindung ordnungsgemäß getrennt")
        else:
            _LOGGER.warning("MQTT-Verbindung unerwartet getrennt (RC: %d)", rc)
        
        # Thread-sicher: Event in Queue einreihen über Event Loop
        self.hass.loop.call_soon_threadsafe(
            self._queue_event, "disconnect", rc
        )
        
        # Reconnect nur bei unerwarteter Trennung starten
        if rc != 0:
            self.hass.loop.call_soon_threadsafe(self._start_reconnect_thread_safe)
    
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
    
    def _start_reconnect_thread_safe(self) -> None:
        """Thread-sicher: Startet den Reconnect-Prozess."""
        if self._reconnect_task and not self._reconnect_task.done():
            _LOGGER.debug("Reconnect bereits in Bearbeitung, überspringe")
            return
        
        _LOGGER.info("Starte MQTT-Reconnect in %d Sekunden", self._reconnect_delay)
        
        async def _reconnect() -> None:
            try:
                await asyncio.sleep(self._reconnect_delay)
                
                # Prüfen ob bereits verbunden
                if self._connected:
                    _LOGGER.debug("Bereits verbunden, überspringe Reconnect")
                    return
                
                success = await self.connect()
                if not success:
                    # Für öffentliche Broker: Kürzere Delays (max 30 Sekunden)
                    self._reconnect_delay = min(self._reconnect_delay * 1.2, 30)
                    _LOGGER.warning("MQTT-Reconnect fehlgeschlagen, nächster Versuch in %d Sekunden", self._reconnect_delay)
                else:
                    # Bei Erfolg Reconnect-Delay zurücksetzen
                    self._reconnect_delay = 3  # Kürzerer initialer Delay für öffentliche Broker
                    _LOGGER.info("MQTT-Reconnect erfolgreich")
                    
            except Exception as e:
                _LOGGER.error("Fehler beim MQTT-Reconnect: %s", e)
                # Bei Fehler auch Delay erhöhen
                self._reconnect_delay = min(self._reconnect_delay * 1.2, 30)
            finally:
                # Task als beendet markieren
                self._reconnect_task = None
        
        # Thread-sicher: Task über Event Loop erstellen
        self._reconnect_task = self.hass.async_create_task(_reconnect())
    
    def _start_event_processor(self) -> None:
        """Startet den Event-Processor."""
        if self._event_processor_task and not self._event_processor_task.done():
            return
        
        # Thread-sicher: Task über Event Loop erstellen
        self._event_processor_task = self.hass.async_create_task(self._process_events())
        _LOGGER.debug("Event-Processor gestartet")
    
    def _stop_event_processor(self) -> None:
        """Stoppt den Event-Processor."""
        if self._event_processor_task:
            if not self._event_processor_task.done():
                self._event_processor_task.cancel()
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
                                self.hass.bus.async_fire(EVENT_MQTT_CONNECTED)
                            except Exception as e:
                                _LOGGER.error("Fehler beim Firen des Connect-Events: %s", e)
                        else:
                            _LOGGER.warning("Home Assistant Bus nicht verfügbar für Connect-Event")
                    elif event_type == "disconnect":
                        if self.hass is not None and hasattr(self.hass, 'bus') and self.hass.bus is not None:
                            try:
                                self.hass.bus.async_fire(EVENT_MQTT_DISCONNECTED)
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