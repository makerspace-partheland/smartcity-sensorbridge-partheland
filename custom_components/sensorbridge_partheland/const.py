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
PLATFORMS: Final[list[Platform]] = [
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
]

# MQTT Configuration (Default-Werte, werden aus config.json überschrieben)
MQTT_VERSION: Final[int] = 4  # MQTT v3.1.1
CLIENT_ID_PREFIX: Final[str] = "hacs-sc-sensorbridge-"

# Configuration Keys
CONF_SELECTED_DEVICES: Final[str] = "selected_devices"
CONF_SELECTED_MEDIAN_ENTITIES: Final[str] = "selected_median_entities"
CONF_DEVICE_METADATA: Final[str] = "device_metadata"
CONF_INCLUDE_DWD_POLLEN: Final[str] = "include_dwd_pollen"
CONF_INCLUDE_DWD_PRECIPITATION_BRANDIS: Final[str] = (
    "include_dwd_precipitation_brandis"
)
CONF_INCLUDE_DWD_PRECIPITATION_BELGERSHAIN: Final[str] = (
    "include_dwd_precipitation_belgershain"
)
CONF_INCLUDE_GEOBOX_BRANDIS: Final[str] = "include_geobox_brandis"
CONF_SENSOR_STATIONS: Final[str] = "sensor_stations"
CONF_SEARCH_TERM: Final[str] = "search_term"
CONFIG_ENTRY_VERSION: Final[int] = 2

# Supplemental sources
SUPPLEMENTAL_COORDINATORS: Final[str] = "supplemental_coordinators"
DWD_POLLEN_SOURCE: Final[str] = "dwd_pollen"
DWD_POLLEN_DEVICE_ID: Final[str] = "supplemental:dwd_pollen:81"
DWD_POLLEN_URL: Final[str] = (
    "https://opendata.dwd.de/climate_environment/health/alerts/s31fg.json"
)
DWD_PRECIPITATION_STATIONS: Final[dict[str, dict[str, str]]] = {
    "07362": {
        "name": "Brandis",
        "config_key": CONF_INCLUDE_DWD_PRECIPITATION_BRANDIS,
        "source": "dwd_precipitation_07362",
        "device_id": "supplemental:dwd_precipitation:07362",
        "url": (
            "https://opendata.dwd.de/climate_environment/CDC/observations_germany/"
            "climate/5_minutes/precipitation/now/"
            "5minutenwerte_nieder_07362_now.zip"
        ),
    },
    "07323": {
        "name": "Belgershain",
        "config_key": CONF_INCLUDE_DWD_PRECIPITATION_BELGERSHAIN,
        "source": "dwd_precipitation_07323",
        "device_id": "supplemental:dwd_precipitation:07323",
        "url": (
            "https://opendata.dwd.de/climate_environment/CDC/observations_germany/"
            "climate/5_minutes/precipitation/now/"
            "5minutenwerte_nieder_07323_now.zip"
        ),
    },
}
GEOBOX_BRANDIS_SOURCE: Final[str] = "geobox_brandis_01038"
GEOBOX_BRANDIS_DEVICE_ID: Final[str] = "supplemental:geobox:01038"
GEOBOX_BRANDIS_URL: Final[str] = (
    "https://geoservice.rlp.de/server/rest/services/"
    "REF_DE_Wetterstationen_komplett/FeatureServer/0/query"
)

# Default Values
DEFAULT_SCAN_INTERVAL: Final[int] = 30  # Health check interval for MQTT
DEFAULT_TIMEOUT: Final[int] = 10  # Sekunden
DEVICE_API_URL: Final[str] = "https://data.makerspace-partheland.de/v2/geojson/devices/"

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
ERROR_NO_MATCHES: Final[str] = "keine_treffer"

# Abort Messages
ABORT_ALREADY_CONFIGURED: Final[str] = "already_configured"
ABORT_NO_DEVICES: Final[str] = "no_devices_available"
ABORT_SINGLE_INSTANCE: Final[str] = "single_instance_allowed"
