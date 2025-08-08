"""
Konstanten für SmartCity SensorBridge Partheland Integration
HA 2025 Compliant mit vollständigen Type Hints
"""

from typing import Final
from homeassistant.const import Platform

# Integration Details
DOMAIN: Final[str] = "sensorbridge_partheland"
NAME: Final[str] = "SmartCity SensorBridge Partheland"
MANUFACTURER: Final[str] = "Makerspace Partheland e.V."
VERSION: Final[str] = "0.1.0"

# Platforms
PLATFORMS: Final[list[Platform]] = [Platform.SENSOR]

# MQTT Configuration (Default-Werte, werden aus config.json überschrieben)
MQTT_VERSION: Final[int] = 4  # MQTT v3.1.1
CLIENT_ID_PREFIX: Final[str] = "hacs-sc-sensorbridge-"

# Configuration Keys
CONF_SELECTED_DEVICES: Final[str] = "selected_devices"
CONF_SELECTED_MEDIAN_ENTITIES: Final[str] = "selected_median_entities"
CONF_SENSOR_STATIONS: Final[str] = "sensor_stations"

# Default Values
DEFAULT_SCAN_INTERVAL: Final[int] = 30  # Health check interval for MQTT
DEFAULT_TIMEOUT: Final[int] = 10  # Sekunden

# Service Names
SERVICE_RELOAD_CONFIG: Final[str] = "reload_config"
SERVICE_FORCE_UPDATE: Final[str] = "force_update"

# Event Names
EVENT_SENSOR_DATA_RECEIVED: Final[str] = f"{DOMAIN}_sensor_data_received"
EVENT_MQTT_CONNECTED: Final[str] = f"{DOMAIN}_mqtt_connected"
EVENT_MQTT_DISCONNECTED: Final[str] = f"{DOMAIN}_mqtt_disconnected"

# File Paths
CONFIG_FILE: Final[str] = "config.json"
TRANSLATIONS_DIR: Final[str] = "translations"

# Error Messages
ERROR_CANNOT_CONNECT: Final[str] = "cannot_connect"
ERROR_UNKNOWN: Final[str] = "unknown"
ERROR_VALIDATION: Final[str] = "validierungsfehler"
ERROR_NO_SELECTION: Final[str] = "mindestens_eine_auswahl"

# Abort Messages
ABORT_ALREADY_CONFIGURED: Final[str] = "already_configured"
ABORT_NO_DEVICES: Final[str] = "no_devices_available"
ABORT_SINGLE_INSTANCE: Final[str] = "single_instance_allowed"
