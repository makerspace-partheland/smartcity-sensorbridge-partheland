"""
Application Credentials Platform für SmartCity SensorBridge Partheland
HA 2025 Compliant
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.application_credentials import (
    ApplicationCredentials,
    ClientCredential,
    AuthorizationServer,
)

DOMAIN = "sensorbridge_partheland"

# Diese Integration benötigt keine OAuth2 Application Credentials
# MQTT-Verbindung erfolgt über direkte Konfiguration

async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    """Return authorization server."""
    return AuthorizationServer(
        authorize_url="",
        token_url="",
    )


async def async_get_client_credential(hass: HomeAssistant, config_entry: ConfigEntry) -> ClientCredential | None:
    """Return client credential."""
    return None 