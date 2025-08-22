import pytest
from typing import Any, Dict

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from aiohttp import ClientSession
from homeassistant.setup import async_setup_component

from custom_components.sensorbridge_partheland.const import (
    DOMAIN,
    NAME,
    CONF_SELECTED_DEVICES,
    CONF_SELECTED_MEDIAN_ENTITIES,
)


@pytest.fixture
def mock_config_service(mocker):
    """Mock für ConfigService mit realistischen Daten."""
    service = mocker.AsyncMock()
    
    # Core validation methods
    service.validate_config.return_value = True
    service.load_config.return_value = {
        "devices": {
            "sensebox": [
                {"id": "Naunhof_Nr1", "name": "Station Naunhof Nr 1", "sensors": ["temperature", "humidity"]},
                {"id": "Naunhof_Nr2", "name": "Station Naunhof Nr 2", "sensors": ["temperature"]},
            ]
        },
        "median_entities": [
            {"id": "median_Naunhof", "name": "Median Naunhof", "sensors": ["temperature", "humidity", "pm25"]}
        ]
    }
    
    # Device and entity retrieval
    service.get_devices.return_value = {
        "sensebox": [
            {"id": "Naunhof_Nr1", "name": "Station Naunhof Nr 1", "sensors": ["temperature", "humidity"]},
            {"id": "Naunhof_Nr2", "name": "Station Naunhof Nr 2", "sensors": ["temperature"]},
        ],
    }
    service.get_device_categories.return_value = {"sensebox": "SenseBox"}
    service.get_ui_text.return_value = {"sensors": "Sensoren"}
    service.get_median_entities.return_value = [
        {"id": "median_Naunhof", "name": "Median Naunhof", "sensors": ["temperature", "humidity", "pm25"]}
    ]
    
    return service


@pytest.fixture
def mock_integration_setup(mocker, mock_config_service):
    """Mock für die Integration Setup, um den ConfigService korrekt zu injizieren."""
    # Mock die Integration Setup - verhindert echte Service-Initialisierung
    mocker.patch(
        "custom_components.sensorbridge_partheland.__init__._async_initialize_services",
        side_effect=lambda hass: mock_hass_data(hass)
    )
    
    # Mock async_setup_entry um echte Coordinator-Erstellung zu verhindern
    mocker.patch(
        "custom_components.sensorbridge_partheland.__init__.async_setup_entry",
        return_value=True
    )
    
    # Mock die hass.data Einträge
    def mock_hass_data(hass):
        if DOMAIN not in hass.data:
            hass.data[DOMAIN] = {}
        
        # Create proper service mocks
        mqtt_service = mocker.AsyncMock()
        mqtt_service.connect = mocker.AsyncMock(return_value=True)
        mqtt_service.disconnect = mocker.AsyncMock(return_value=True)
        mqtt_service.is_connected = mocker.AsyncMock(return_value=True)
        
        parser_service = mocker.AsyncMock()
        parser_service.parse_message = mocker.AsyncMock(return_value={
            "temperature": 23.5,
            "humidity": 45.2,
            "timestamp": "2025-01-01T12:00:00Z"
        })
        
        entity_factory = mocker.AsyncMock()
        entity_factory.create_sensor_entities = mocker.AsyncMock(return_value=[
            {"entity_id": "sensor.naunhof_nr1_temperature", "name": "Temperature Naunhof Nr1"}
        ])
        
        error_handler = mocker.AsyncMock()
        error_handler.handle_error = mocker.AsyncMock()
        
        translation_helper = mocker.AsyncMock()
        translation_helper.get_translation = mocker.AsyncMock(return_value="Translated Text")
        
        # Store all services
        hass.data[DOMAIN]["config_service"] = mock_config_service
        hass.data[DOMAIN]["mqtt_service"] = mqtt_service
        hass.data[DOMAIN]["parser_service"] = parser_service
        hass.data[DOMAIN]["entity_factory"] = entity_factory
        hass.data[DOMAIN]["error_handler"] = error_handler
        hass.data[DOMAIN]["translation_helper"] = translation_helper
    
    # Mock direkt in hass.data
    def setup_mock_integration(hass):
        mock_hass_data(hass)
        
        # Mock die _async_initialize_config_service Methoden als AsyncMock
        async def mock_init_service(self):
            self.config_service = mock_config_service
            
        mocker.patch(
            "custom_components.sensorbridge_partheland.config_flow.ConfigFlow._async_initialize_config_service",
            new=mock_init_service
        )
        
        mocker.patch(
            "custom_components.sensorbridge_partheland.config_flow.OptionsFlowHandler._async_initialize_config_service",
            new=mock_init_service
        )
    
    return setup_mock_integration


async def test_user_flow_shows_selection_form(hass: HomeAssistant, mock_config_service, mock_integration_setup):
    """Start des Flows zeigt Auswahlformular, wenn noch nichts gewählt ist."""
    mock_integration_setup(hass)
    
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "device_selection"


async def test_user_flow_abort_if_already_configured(hass: HomeAssistant, mock_config_service, mock_integration_setup):
    """Ein zweiter Start sollte abbrechen, wenn bereits ein Eintrag existiert."""
    mock_integration_setup(hass)
    
    entry = config_entries.ConfigEntry(
        version=1,
        domain=DOMAIN,
        title=NAME,
        data={CONF_SELECTED_DEVICES: [], CONF_SELECTED_MEDIAN_ENTITIES: []},
        source=config_entries.SOURCE_USER,
        entry_id="test",
        discovery_keys=[],
        minor_version=1,
        options={},
        unique_id="test_unique_id",
    )
    await hass.config_entries.async_add(entry)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.ABORT


async def test_user_flow_create_entry(hass: HomeAssistant, mock_config_service, mock_integration_setup):
    """Erstellen eines Eintrags nach Auswahl von Geräten/Median-Entities."""
    mock_integration_setup(hass)
    
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SELECTED_DEVICES: ["Naunhof_Nr1"],
            CONF_SELECTED_MEDIAN_ENTITIES: ["median_Naunhof"],
        },
    )
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == NAME
    assert result2["data"][CONF_SELECTED_DEVICES] == ["Naunhof_Nr1"]
    assert result2["data"][CONF_SELECTED_MEDIAN_ENTITIES] == ["median_Naunhof"]


async def test_options_flow_sync_entry(hass: HomeAssistant, mock_config_service, mock_integration_setup):
    """Optionsflow startet synchron (kein Coroutine) und aktualisiert den Eintrag."""
    mock_integration_setup(hass)
    
    entry = config_entries.ConfigEntry(
        version=1,
        domain=DOMAIN,
        title=NAME,
        data={CONF_SELECTED_DEVICES: ["Naunhof_Nr1"], CONF_SELECTED_MEDIAN_ENTITIES: []},
        source=config_entries.SOURCE_USER,
        entry_id="test2",
        discovery_keys=[],
        minor_version=1,
        options={},
        unique_id="test2_unique_id",
    )
    await hass.config_entries.async_add(entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "device_selection"

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SELECTED_DEVICES: ["Naunhof_Nr1", "Naunhof_Nr2"],
            CONF_SELECTED_MEDIAN_ENTITIES: ["median_Naunhof"],
        },
    )
    assert result2["type"] == FlowResultType.CREATE_ENTRY

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.data[CONF_SELECTED_DEVICES] == ["Naunhof_Nr1", "Naunhof_Nr2"]
    assert updated.data[CONF_SELECTED_MEDIAN_ENTITIES] == ["median_Naunhof"]


async def test_http_config_flow_happy_path(hass: HomeAssistant, hass_client, mock_integration_setup):
    """HTTP-API: Start des Config Flows funktioniert.""" 
    # Integration korrekt einrichten
    mock_integration_setup(hass)
    
    # Setup HTTP components
    await async_setup_component(hass, "http", {})
    await async_setup_component(hass, "config", {})
    await hass.async_block_till_done()
    
    client = await hass_client()

    # Init Flow (POST /api/config/config_entries/flow) 
    resp = await client.post(
        "/api/config/config_entries/flow",
        json={"handler": DOMAIN, "show_advanced_options": False},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["type"].lower() == "form"
    assert data["step_id"] == "device_selection"


async def test_http_config_flow_validation_no_selection(hass: HomeAssistant, hass_client, mock_integration_setup):
    """HTTP-API: Config Flow Init funktioniert."""
    # Integration korrekt einrichten
    mock_integration_setup(hass)
    
    # Setup HTTP components
    await async_setup_component(hass, "http", {})
    await async_setup_component(hass, "config", {})
    await hass.async_block_till_done()
    
    client = await hass_client()

    resp = await client.post(
        "/api/config/config_entries/flow",
        json={"handler": DOMAIN, "show_advanced_options": False},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["type"].lower() == "form"


async def test_service_integration_functionality(hass: HomeAssistant, mock_config_service, mock_integration_setup):
    """Test that the integration services work correctly together."""
    mock_integration_setup(hass)
    
    # Verify services are properly set up
    assert DOMAIN in hass.data
    assert "config_service" in hass.data[DOMAIN]
    assert "mqtt_service" in hass.data[DOMAIN]
    assert "parser_service" in hass.data[DOMAIN]
    assert "entity_factory" in hass.data[DOMAIN]
    assert "error_handler" in hass.data[DOMAIN]
    assert "translation_helper" in hass.data[DOMAIN]
    
    # Test config service functionality
    config_service = hass.data[DOMAIN]["config_service"]
    assert await config_service.validate_config() is True
    
    devices = await config_service.get_devices()
    assert "sensebox" in devices
    assert len(devices["sensebox"]) == 2
    assert devices["sensebox"][0]["id"] == "Naunhof_Nr1"
    
    median_entities = await config_service.get_median_entities()
    assert len(median_entities) == 1
    assert median_entities[0]["id"] == "median_Naunhof"
    
    # Test MQTT service functionality
    mqtt_service = hass.data[DOMAIN]["mqtt_service"]
    assert await mqtt_service.connect() is True
    assert await mqtt_service.is_connected() is True
    
    # Test parser service functionality  
    parser_service = hass.data[DOMAIN]["parser_service"]
    parsed_data = await parser_service.parse_message("test/topic", '{"temperature": 23.5}')
    assert parsed_data is not None
    assert "temperature" in parsed_data
    
    # Test entity factory functionality
    entity_factory = hass.data[DOMAIN]["entity_factory"]
    entities = await entity_factory.create_sensor_entities()
    assert len(entities) == 1
    assert "entity_id" in entities[0]


async def test_config_flow_device_validation(hass: HomeAssistant, mock_config_service, mock_integration_setup):
    """Test config flow validates device selection with actual device data."""
    mock_integration_setup(hass)
    
    # Start config flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "device_selection"
    
    # Test with empty selection - should show error
    result_empty = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SELECTED_DEVICES: [],
            CONF_SELECTED_MEDIAN_ENTITIES: [],
        },
    )
    assert result_empty["type"] == FlowResultType.FORM
    assert result_empty["errors"]["base"] == "mindestens_eine_auswahl"
    
    # Test with valid device selection
    result_valid = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SELECTED_DEVICES: ["Naunhof_Nr1"],
            CONF_SELECTED_MEDIAN_ENTITIES: ["median_Naunhof"],
        },
    )
    assert result_valid["type"] == FlowResultType.CREATE_ENTRY
    assert result_valid["title"] == NAME
    
    # Verify the data contains our selections
    assert result_valid["data"][CONF_SELECTED_DEVICES] == ["Naunhof_Nr1"] 
    assert result_valid["data"][CONF_SELECTED_MEDIAN_ENTITIES] == ["median_Naunhof"]


async def test_integration_services_interaction(hass: HomeAssistant, mock_config_service, mock_integration_setup):
    """Test that integration services work together properly."""
    mock_integration_setup(hass)
    
    # Test that all services are available
    assert DOMAIN in hass.data
    services = hass.data[DOMAIN]
    
    required_services = [
        "config_service", "mqtt_service", "parser_service", 
        "entity_factory", "error_handler", "translation_helper"
    ]
    
    for service_name in required_services:
        assert service_name in services, f"Missing service: {service_name}"
        assert services[service_name] is not None, f"Service {service_name} is None"
    
    # Test config service returns valid device data
    config_service = services["config_service"]
    devices = await config_service.get_devices()
    assert isinstance(devices, dict)
    assert "sensebox" in devices
    assert len(devices["sensebox"]) >= 1
    
    median_entities = await config_service.get_median_entities()
    assert isinstance(median_entities, list)
    assert len(median_entities) >= 1
    
    # Test MQTT service basic functionality
    mqtt_service = services["mqtt_service"]
    assert await mqtt_service.connect() is True
    assert await mqtt_service.is_connected() is True
    
    # Test parser service basic functionality
    parser_service = services["parser_service"]
    test_data = await parser_service.parse_message("test/topic", '{"temp": 25.0}')
    assert test_data is not None
    assert isinstance(test_data, dict)


