"""
Error Handler für SmartCity SensorBridge Partheland
HA 2025 Compliant - Reine Fehlerbehandlung
"""

from __future__ import annotations

import logging
import traceback
from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .interfaces import ErrorHandlerProtocol

_LOGGER = logging.getLogger(__name__)


class SensorBridgeError(HomeAssistantError):
    """Basis-Fehler für SmartCity SensorBridge."""
    pass


class MQTTConnectionError(SensorBridgeError):
    """Fehler bei MQTT-Verbindung."""
    pass


class ConfigValidationError(SensorBridgeError):
    """Fehler bei Konfigurationsvalidierung."""
    pass


class MessageParsingError(SensorBridgeError):
    """Fehler beim Message-Parsing."""
    pass


class EntityCreationError(SensorBridgeError):
    """Fehler bei Entity-Erstellung."""
    pass


class ErrorHandler(ErrorHandlerProtocol):
    """HA 2025 Error Handler für reine Fehlerbehandlung."""
    
    def __init__(self, hass: HomeAssistant) -> None:
        """Initialisiert den Error Handler."""
        self.hass = hass
        self._error_count: Dict[str, int] = {}
        self._max_errors_per_context = 10
        self._config_service: Optional[ConfigService] = None
    
    async def handle_error(self, error: Exception, context: str) -> None:
        """Behandelt einen Fehler."""
        try:
            # Fehler loggen
            await self.log_error(error, context)
            
            # Fehler-Zähler aktualisieren
            self._increment_error_count(context)
            
            # Benutzerfreundliche Meldung generieren
            user_message = await self.get_user_friendly_message(error)
            
            # Fehler-Typ bestimmen
            error_type = self._get_error_type(error)
            
            # Fehler-spezifische Behandlung
            await self._handle_specific_error(error, error_type, context, user_message)
            
        except Exception as e:
            _LOGGER.error("Fehler beim Fehlerbehandlung: %s", e)
    
    async def log_error(self, error: Exception, context: str) -> None:
        """Loggt einen Fehler."""
        try:
            # Fehler-Zähler prüfen
            error_count = self._error_count.get(context, 0)
            
            if error_count >= self._max_errors_per_context:
                if error_count == self._max_errors_per_context:
                    _LOGGER.error(
                        "Maximale Anzahl von Fehlern für Kontext '%s' erreicht. "
                        "Weitere Fehler werden unterdrückt.",
                        context
                    )
                return
            
            # Fehler-Details sammeln
            error_details = {
                "type": type(error).__name__,
                "message": str(error),
                "context": context,
                "count": error_count + 1
            }
            
            # Stack-Trace für Debug-Level
            if _LOGGER.isEnabledFor(logging.DEBUG):
                error_details["traceback"] = traceback.format_exc()
            
            # Fehler loggen
            _LOGGER.error(
                "SmartCity SensorBridge Fehler [%s]: %s (Anzahl: %d)",
                context,
                str(error),
                error_count + 1,
                exc_info=_LOGGER.isEnabledFor(logging.DEBUG)
            )
            
        except Exception as e:
            _LOGGER.error("Fehler beim Loggen: %s", e)
    
    async def get_user_friendly_message(self, error: Exception) -> str:
        """Gibt eine benutzerfreundliche Fehlermeldung zurück."""
        try:
            # Config Service initialisieren falls nötig
            if not self._config_service:
                from .config_service import ConfigService
                self._config_service = ConfigService(self.hass)
            
            # Fehler-Typ bestimmen
            error_type = self._get_error_type(error)
            
            # Fehlermeldungen aus der Konfiguration laden
            error_messages = await self._config_service.get_error_messages()
            
            # Spezifische Meldung aus der Konfiguration
            if error_type in error_messages:
                return error_messages[error_type]
            
            # Fallback für unbekannte Fehler
            return error_messages.get("unknown_error", "Ein unerwarteter Fehler ist aufgetreten")
            
        except Exception as e:
            _LOGGER.error("Fehler beim Generieren der Benutzer-Meldung: %s", e)
            return "Fehler bei der Fehlerbehandlung"
    
    def _get_error_type(self, error: Exception) -> str:
        """Bestimmt den Fehler-Typ."""
        if isinstance(error, MQTTConnectionError):
            return "mqtt_connection"
        elif isinstance(error, ConfigValidationError):
            return "config_validation"
        elif isinstance(error, MessageParsingError):
            return "message_parsing"
        elif isinstance(error, EntityCreationError):
            return "entity_creation"
        elif isinstance(error, SensorBridgeError):
            return "sensor_bridge"
        else:
            return "unknown"
    
    def _increment_error_count(self, context: str) -> None:
        """Erhöht den Fehler-Zähler für einen Kontext."""
        self._error_count[context] = self._error_count.get(context, 0) + 1
    
    async def _handle_specific_error(
        self, 
        error: Exception, 
        error_type: str, 
        context: str, 
        user_message: str
    ) -> None:
        """Behandelt spezifische Fehler-Typen."""
        try:
            if error_type == "mqtt_connection":
                await self._handle_mqtt_error(error, context, user_message)
            elif error_type == "config_validation":
                await self._handle_config_error(error, context, user_message)
            elif error_type == "message_parsing":
                await self._handle_parsing_error(error, context, user_message)
            elif error_type == "entity_creation":
                await self._handle_entity_error(error, context, user_message)
            else:
                await self._handle_generic_error(error, context, user_message)
                
        except Exception as e:
            _LOGGER.error("Fehler bei spezifischer Fehlerbehandlung: %s", e)
    
    async def _handle_mqtt_error(
        self, 
        error: Exception, 
        context: str, 
        user_message: str
    ) -> None:
        """Behandelt MQTT-Fehler."""
        _LOGGER.warning(
            "MQTT-Fehler in Kontext '%s': %s. Automatische Reconnection wird versucht.",
            context,
            user_message
        )
        
        # Event auslösen für UI-Benachrichtigung
        self.hass.bus.async_fire(
            "sensorbridge_partheland_mqtt_error",
            {
                "context": context,
                "message": user_message,
                "error": str(error)
            }
        )
    
    async def _handle_config_error(
        self, 
        error: Exception, 
        context: str, 
        user_message: str
    ) -> None:
        """Behandelt Konfigurationsfehler."""
        _LOGGER.error(
            "Konfigurationsfehler in Kontext '%s': %s. Integration kann nicht gestartet werden.",
            context,
            user_message
        )
        
        # Event auslösen für UI-Benachrichtigung
        self.hass.bus.async_fire(
            "sensorbridge_partheland_config_error",
            {
                "context": context,
                "message": user_message,
                "error": str(error)
            }
        )
    
    async def _handle_parsing_error(
        self, 
        error: Exception, 
        context: str, 
        user_message: str
    ) -> None:
        """Behandelt Parsing-Fehler."""
        _LOGGER.warning(
            "Parsing-Fehler in Kontext '%s': %s. Nachricht wird ignoriert.",
            context,
            user_message
        )
        
        # Event auslösen für UI-Benachrichtigung
        self.hass.bus.async_fire(
            "sensorbridge_partheland_parsing_error",
            {
                "context": context,
                "message": user_message,
                "error": str(error)
            }
        )
    
    async def _handle_entity_error(
        self, 
        error: Exception, 
        context: str, 
        user_message: str
    ) -> None:
        """Behandelt Entity-Fehler."""
        _LOGGER.warning(
            "Entity-Fehler in Kontext '%s': %s. Entity wird übersprungen.",
            context,
            user_message
        )
        
        # Event auslösen für UI-Benachrichtigung
        self.hass.bus.async_fire(
            "sensorbridge_partheland_entity_error",
            {
                "context": context,
                "message": user_message,
                "error": str(error)
            }
        )
    
    async def _handle_generic_error(
        self, 
        error: Exception, 
        context: str, 
        user_message: str
    ) -> None:
        """Behandelt generische Fehler."""
        _LOGGER.error(
            "Generischer Fehler in Kontext '%s': %s",
            context,
            user_message
        )
        
        # Event auslösen für UI-Benachrichtigung
        self.hass.bus.async_fire(
            "sensorbridge_partheland_generic_error",
            {
                "context": context,
                "message": user_message,
                "error": str(error)
            }
        )
    
    def reset_error_count(self, context: Optional[str] = None) -> None:
        """Setzt den Fehler-Zähler zurück."""
        if context:
            self._error_count[context] = 0
        else:
            self._error_count.clear()
    
    def get_error_count(self, context: str) -> int:
        """Gibt die Anzahl der Fehler für einen Kontext zurück."""
        return self._error_count.get(context, 0)
    
    def get_total_error_count(self) -> int:
        """Gibt die Gesamtanzahl der Fehler zurück."""
        return sum(self._error_count.values()) 