"""
Translation Helper für SmartCity SensorBridge Partheland
HA 2025 Compliant - Native Übersetzungsfunktionen
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class TranslationHelper:
    """HA 2025 Translation Helper für native Übersetzungsfunktionen."""
    
    def __init__(self, hass: HomeAssistant) -> None:
        """Initialisiert den Translation Helper."""
        self.hass = hass
    
    async def get_sensor_names(self) -> Dict[str, str]:
        """Gibt die Sensor-Namen-Übersetzungen zurück (Legacy-Support)."""
        try:
            translations = await async_get_translations(
                self.hass, self.hass.config.language, "entity", [DOMAIN]
            )
            
            # Korrekte HA 2025 Struktur: entity.sensor.{sensor_name}.name
            entity_translations = translations.get("entity", {})
            sensor_translations = entity_translations.get("sensor", {})
            sensor_names = {}
            
            for sensor_key, sensor_data in sensor_translations.items():
                if isinstance(sensor_data, dict) and "name" in sensor_data:
                    sensor_names[sensor_key] = sensor_data["name"]
            
            _LOGGER.debug("Sensor-Namen aus HA 2025 Übersetzungen geladen: %s", sensor_names)
            return sensor_names
            
        except Exception as e:
            _LOGGER.warning("Fehler beim Laden der Sensor-Namen-Übersetzungen: %s", e)
            return {}
    
    async def get_device_categories(self) -> Dict[str, str]:
        """Gibt die Geräte-Kategorien-Übersetzungen zurück."""
        try:
            translations = await async_get_translations(
                self.hass, self.hass.config.language, "entity", [DOMAIN]
            )
            
            # Korrekte Struktur: entity.device_categories
            entity_translations = translations.get("entity", {})
            device_categories = entity_translations.get("device_categories", {})
            
            _LOGGER.debug("Geräte-Kategorien aus Übersetzungen geladen: %s", device_categories)
            return device_categories
            
        except Exception as e:
            _LOGGER.warning("Fehler beim Laden der Geräte-Kategorien-Übersetzungen: %s", e)
            return {}
    
    async def get_ui_text(self) -> Dict[str, str]:
        """Gibt die UI-Texte zurück."""
        try:
            translations = await async_get_translations(
                self.hass, self.hass.config.language, "config", [DOMAIN]
            )
            
            # UI-Texte aus den Übersetzungen extrahieren
            ui_text = translations.get("ui_text", {})
            
            _LOGGER.debug("UI-Texte aus Übersetzungen geladen: %s", ui_text)
            return ui_text
            
        except Exception as e:
            _LOGGER.warning("Fehler beim Laden der UI-Texte: %s", e)
            return {}
    
    async def get_error_messages(self) -> Dict[str, str]:
        """Gibt die Fehlermeldungen zurück."""
        try:
            translations = await async_get_translations(
                self.hass, self.hass.config.language, "config", [DOMAIN]
            )
            
            # Fehlermeldungen aus den Übersetzungen extrahieren
            error_messages = translations.get("error_messages", {})
            
            _LOGGER.debug("Fehlermeldungen aus Übersetzungen geladen: %s", error_messages)
            return error_messages
            
        except Exception as e:
            _LOGGER.warning("Fehler beim Laden der Fehlermeldungen: %s", e)
            return {}
    
    async def get_state_text(self) -> Dict[str, str]:
        """Gibt die Zustands-Texte zurück."""
        try:
            translations = await async_get_translations(
                self.hass, self.hass.config.language, "state", [DOMAIN]
            )
            return translations
        except Exception as e:
            _LOGGER.warning("Fehler beim Laden der Zustands-Texte: %s", e)
            return {}
    
    def format_field_name(self, field_name: str, sensor_names: Optional[Dict[str, str]] = None) -> str:
        """Gibt den übersetzten Namen des Sensors zurück."""
        if sensor_names and field_name in sensor_names:
            return sensor_names[field_name]
        
        # Fallback: Verwende den ursprünglichen Feldnamen
        return field_name
    
    def format_device_category(self, category: str, device_categories: Optional[Dict[str, str]] = None) -> str:
        """Gibt den übersetzten Namen der Gerätekategorie zurück."""
        if device_categories and category in device_categories:
            return device_categories[category]
        
        # Fallback: Verwende den ursprünglichen Kategorienamen
        return category
    
    async def debug_translations(self) -> Dict[str, Any]:
        """Debug-Methode um alle verfügbaren Übersetzungen zu überprüfen."""
        try:
            debug_info = {}
            
            # Entity-Übersetzungen laden
            entity_translations = await async_get_translations(
                self.hass, self.hass.config.language, "entity", [DOMAIN]
            )
            debug_info["entity_translations"] = entity_translations
            
            # Config-Übersetzungen laden
            config_translations = await async_get_translations(
                self.hass, self.hass.config.language, "config", [DOMAIN]
            )
            debug_info["config_translations"] = config_translations
            
            # State-Übersetzungen laden
            state_translations = await async_get_translations(
                self.hass, self.hass.config.language, "state", [DOMAIN]
            )
            debug_info["state_translations"] = state_translations
            
            # Spezifische Sensor-Namen extrahieren
            sensor_names = entity_translations.get("sensor_names", {})
            debug_info["sensor_names"] = sensor_names
            
            _LOGGER.info("Translation Debug Info: %s", debug_info)
            return debug_info
            
        except Exception as e:
            _LOGGER.error("Fehler beim Debug der Übersetzungen: %s", e)
            return {"error": str(e)} 