import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component

from custom_components.sensorbridge_partheland.api_client import DeviceCatalogError
from custom_components.sensorbridge_partheland.const import (
    CONF_DEVICE_METADATA,
    CONF_SEARCH_TERM,
    CONF_SELECTED_DEVICES,
    CONF_SELECTED_MEDIAN_ENTITIES,
    DOMAIN,
    NAME,
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
                {
                    "id": "Naunhof_Nr1",
                    "name": "Station Naunhof Nr 1",
                    "sensors": ["temperature", "humidity"],
                },
                {
                    "id": "Naunhof_Nr2",
                    "name": "Station Naunhof Nr 2",
                    "sensors": ["temperature"],
                },
            ]
        },
        "median_entities": [
            {
                "id": "median_Naunhof",
                "name": "Median Naunhof",
                "sensors": ["temperature", "humidity", "pm25"],
            }
        ],
    }

    # Device and entity retrieval
    service.get_devices.return_value = {
        "sensebox": [
            {
                "id": "Naunhof_Nr1",
                "name": "Station Naunhof Nr 1",
                "sensors": ["temperature", "humidity"],
            },
            {
                "id": "Naunhof_Nr2",
                "name": "Station Naunhof Nr 2",
                "sensors": ["temperature"],
            },
        ],
    }
    service.get_selection_candidates.return_value = {
        "senseBox": [
            {
                "id": "Naunhof_Nr1",
                "name": "Station Naunhof Nr 1",
                "type": "senseBox",
                "api_type": "SenseBoxDevice",
                "sensors": ["temperature", "humidity"],
            },
            {
                "id": "Naunhof_Nr2",
                "name": "Station Naunhof Nr 2",
                "type": "senseBox",
                "api_type": "SenseBoxDevice",
                "sensors": ["temperature"],
            },
        ],
        "WaterLevel": [
            {
                "id": "PEGEL_001",
                "name": "Pegel Kleinpösna",
                "type": "WaterLevel",
                "api_type": "WaterLevelDevice",
                "sensors": ["water_level"],
            }
        ],
        "Temperature": [
            {
                "id": "TEMP_001",
                "name": "Messpunkt Dreiskau",
                "type": "Temperature",
                "api_type": "TemperatureDevice",
                "sensors": ["air_temperature"],
            }
        ],
        "Moisture": [
            {
                "id": "MOIST_001",
                "name": "Feldsensor Belgershain",
                "type": "Moisture",
                "api_type": "MoistureDevice",
                "sensors": ["soil_moisture"],
            }
        ],
    }
    metadata = {
        "Naunhof_Nr1": {
            "id": "Naunhof_Nr1",
            "name": "Station Naunhof Nr 1",
            "type": "senseBox",
            "sensors": ["temperature", "humidity"],
            "topic_pattern": "senseBox:home/Naunhof_Nr1",
        },
        "Naunhof_Nr2": {
            "id": "Naunhof_Nr2",
            "name": "Station Naunhof Nr 2",
            "type": "senseBox",
            "sensors": ["temperature"],
            "topic_pattern": "senseBox:home/Naunhof_Nr2",
        },
        "PEGEL_001": {
            "id": "PEGEL_001",
            "name": "Pegel Kleinpösna",
            "type": "WaterLevel",
            "sensors": ["water_level"],
            "sensor_metadata": {"water_level": {"unit": "m"}},
            "topic_pattern": "sensoren/PEGEL_001",
        },
        "TEMP_001": {
            "id": "TEMP_001",
            "name": "Messpunkt Dreiskau",
            "type": "Temperature",
            "sensors": ["air_temperature"],
            "sensor_metadata": {"air_temperature": {"unit": "°C"}},
            "topic_pattern": "sensoren/TEMP_001",
        },
        "MOIST_001": {
            "id": "MOIST_001",
            "name": "Feldsensor Belgershain",
            "type": "Moisture",
            "sensors": ["soil_moisture"],
            "sensor_metadata": {"soil_moisture": {"unit": "%"}},
            "topic_pattern": "sensoren/MOIST_001",
        },
    }
    service.snapshot_devices.side_effect = lambda device_ids: {
        device_id: metadata[device_id] for device_id in device_ids
    }
    service.register_entry_data = mocker.Mock()
    service.get_device_categories.return_value = {"sensebox": "SenseBox"}
    service.get_ui_text.return_value = {"sensors": "Sensoren"}
    service.get_median_entities.return_value = [
        {
            "id": "median_Naunhof",
            "name": "Median Naunhof",
            "sensors": ["temperature", "humidity", "pm25"],
        }
    ]

    return service


@pytest.fixture
def mock_integration_setup(mocker, mock_config_service):
    """Mock für die Integration Setup, um den ConfigService korrekt zu injizieren."""

    # Mock die Integration Setup - verhindert echte Service-Initialisierung
    async def _mock_async_initialize_services(hass):
        mock_hass_data(hass)

    mocker.patch(
        "custom_components.sensorbridge_partheland._async_initialize_services",
        side_effect=_mock_async_initialize_services,
    )

    # Mock async_setup_entry um echte Coordinator-Erstellung zu verhindern
    mocker.patch(
        "custom_components.sensorbridge_partheland.async_setup_entry",
        new=mocker.AsyncMock(return_value=True),
    )

    # Fallback-Schutz: echte MQTT-Socketverbindung im Testlauf unterbinden
    mocker.patch(
        "custom_components.sensorbridge_partheland.mqtt_service.MQTTService.connect",
        new=mocker.AsyncMock(return_value=True),
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
        parser_service.parse_message = mocker.AsyncMock(
            return_value={
                "temperature": 23.5,
                "humidity": 45.2,
                "timestamp": "2025-01-01T12:00:00Z",
            }
        )

        entity_factory = mocker.AsyncMock()
        entity_factory.create_sensor_entities = mocker.AsyncMock(
            return_value=[
                {
                    "entity_id": "sensor.naunhof_nr1_temperature",
                    "name": "Temperature Naunhof Nr1",
                }
            ]
        )

        error_handler = mocker.AsyncMock()
        error_handler.handle_error = mocker.AsyncMock()

        translation_helper = mocker.AsyncMock()
        translation_helper.get_translation = mocker.AsyncMock(
            return_value="Translated Text"
        )

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

        # Verhindert das automatische echte Setup nach async_create_entry.
        mocker.patch.object(
            hass.config_entries,
            "async_setup",
            new=mocker.AsyncMock(return_value=True),
        )
        mocker.patch.object(
            hass.config_entries,
            "async_reload",
            new=mocker.AsyncMock(return_value=True),
        )

        # Mock die _async_initialize_config_service Methoden als AsyncMock
        async def mock_init_service(self):
            self.config_service = mock_config_service

        mocker.patch(
            "custom_components.sensorbridge_partheland.config_flow.ConfigFlow._async_initialize_config_service",
            new=mock_init_service,
        )

        mocker.patch(
            "custom_components.sensorbridge_partheland.config_flow.OptionsFlowHandler._async_initialize_config_service",
            new=mock_init_service,
        )

    return setup_mock_integration


async def test_user_flow_shows_selection_form(
    hass: HomeAssistant, mock_config_service, mock_integration_setup
):
    """Der Flow startet mit der Wahl zwischen Suche und Gesamtansicht."""
    mock_integration_setup(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.MENU
    assert result["step_id"] == "user"
    assert result["menu_options"] == ["search", "all_devices"]


async def test_user_flow_abort_if_already_configured(
    hass: HomeAssistant, mock_config_service, mock_integration_setup
):
    """Ein zweiter Start sollte abbrechen, wenn bereits ein Eintrag existiert."""
    mock_integration_setup(hass)

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        data={CONF_SELECTED_DEVICES: [], CONF_SELECTED_MEDIAN_ENTITIES: []},
        unique_id="test_unique_id",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.ABORT


async def test_user_flow_create_entry(
    hass: HomeAssistant, mock_config_service, mock_integration_setup
):
    """Erstellen eines Eintrags nach Auswahl von Geräten/Median-Entities."""
    mock_integration_setup(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.MENU

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "all_devices"},
    )
    assert result2["type"] == FlowResultType.FORM
    assert result2["step_id"] == "device_selection"

    result3 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "stations": ["Naunhof_Nr1"],
            CONF_SELECTED_MEDIAN_ENTITIES: ["median_Naunhof"],
        },
    )
    assert result3["type"] == FlowResultType.MENU
    assert result3["step_id"] == "selection_menu"

    result4 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "finish"},
    )
    assert result4["type"] == FlowResultType.CREATE_ENTRY
    assert result4["title"] == NAME
    assert result4["data"][CONF_SELECTED_DEVICES] == ["Naunhof_Nr1"]
    assert result4["data"][CONF_SELECTED_MEDIAN_ENTITIES] == ["median_Naunhof"]
    assert "Naunhof_Nr1" in result4["data"][CONF_DEVICE_METADATA]


async def test_user_flow_accumulates_multiple_searches(
    hass: HomeAssistant, mock_config_service, mock_integration_setup
):
    """Auswahlen aus mehreren Suchläufen bleiben erhalten."""
    mock_integration_setup(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "search"}
    )
    first = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SEARCH_TERM: "Nr 1"}
    )
    assert first["step_id"] == "device_selection"
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {"stations": ["Naunhof_Nr1"]}
    )

    await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "search"}
    )
    second = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SEARCH_TERM: "Naunhof_Nr2"}
    )
    assert second["step_id"] == "device_selection"
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {"stations": ["Naunhof_Nr2"]}
    )
    created = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )

    assert created["type"] == FlowResultType.CREATE_ENTRY
    assert created["data"][CONF_SELECTED_DEVICES] == [
        "Naunhof_Nr1",
        "Naunhof_Nr2",
    ]
    assert set(created["data"][CONF_DEVICE_METADATA]) == {
        "Naunhof_Nr1",
        "Naunhof_Nr2",
    }


async def test_user_flow_reports_search_without_matches(
    hass: HomeAssistant, mock_config_service, mock_integration_setup
):
    mock_integration_setup(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "search"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SEARCH_TERM: "nicht vorhanden"}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "search"
    assert result["errors"] == {"base": "keine_treffer"}


@pytest.mark.parametrize(
    ("query", "field", "expected_device", "expected_median"),
    [
        ("kleinpösna", "water_level", "PEGEL_001", None),
        ("TEMP_001", "temperature_moisture", "TEMP_001", None),
        ("MoistureDevice", "temperature_moisture", "MOIST_001", None),
        ("STATION NAUNHOF NR 1", "stations", "Naunhof_Nr1", None),
        ("Median Naunhof", CONF_SELECTED_MEDIAN_ENTITIES, None, "median_Naunhof"),
    ],
)
async def test_user_flow_searches_name_id_type_and_median(
    hass: HomeAssistant,
    mock_config_service,
    mock_integration_setup,
    query,
    field,
    expected_device,
    expected_median,
):
    """Suche trifft Anzeigename, Ort im Namen, ID, Typ und Median."""
    mock_integration_setup(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "search"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SEARCH_TERM: query}
    )

    selection = {field: [expected_device or expected_median]}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], selection
    )
    assert result["type"] == FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SELECTED_DEVICES] == (
        [expected_device] if expected_device else []
    )
    assert result["data"][CONF_SELECTED_MEDIAN_ENTITIES] == (
        [expected_median] if expected_median else []
    )


async def test_user_flow_selects_all_device_categories(
    hass: HomeAssistant, mock_config_service, mock_integration_setup
):
    """Alle Partheland-Gerätegruppen werden getrennt angeboten und gespeichert."""
    mock_integration_setup(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "all_devices"}
    )

    schema_fields = {
        key.schema: selector for key, selector in result["data_schema"].schema.items()
    }
    assert set(schema_fields) == {
        "stations",
        "water_level",
        "temperature_moisture",
        CONF_SELECTED_MEDIAN_ENTITIES,
    }

    await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "stations": ["Naunhof_Nr1"],
            "water_level": ["PEGEL_001"],
            "temperature_moisture": ["TEMP_001", "MOIST_001"],
            CONF_SELECTED_MEDIAN_ENTITIES: ["median_Naunhof"],
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )

    assert result["data"][CONF_SELECTED_DEVICES] == [
        "MOIST_001",
        "Naunhof_Nr1",
        "PEGEL_001",
        "TEMP_001",
    ]
    metadata = result["data"][CONF_DEVICE_METADATA]
    assert set(metadata) == set(result["data"][CONF_SELECTED_DEVICES])
    assert metadata["PEGEL_001"]["type"] == "WaterLevel"
    assert metadata["PEGEL_001"]["sensor_metadata"] == {"water_level": {"unit": "m"}}
    assert metadata["PEGEL_001"]["topic_pattern"] == "sensoren/PEGEL_001"
    mock_config_service.snapshot_devices.assert_awaited_once_with(
        result["data"][CONF_SELECTED_DEVICES]
    )


async def test_options_flow_sync_entry(
    hass: HomeAssistant, mock_config_service, mock_integration_setup
):
    """Optionsflow startet synchron (kein Coroutine) und aktualisiert den Eintrag."""
    mock_integration_setup(hass)

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        data={
            CONF_SELECTED_DEVICES: ["Naunhof_Nr1"],
            CONF_SELECTED_MEDIAN_ENTITIES: [],
        },
        unique_id="test2_unique_id",
        entry_id="test2",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.MENU
    assert result["step_id"] == "init"

    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"next_step_id": "search"},
    )
    await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SEARCH_TERM: "Nr 2"}
    )
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"], {"stations": ["Naunhof_Nr2"]}
    )
    assert result2["type"] == FlowResultType.MENU

    result3 = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    assert result3["type"] == FlowResultType.CREATE_ENTRY

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.data[CONF_SELECTED_DEVICES] == ["Naunhof_Nr1", "Naunhof_Nr2"]
    assert updated.data[CONF_SELECTED_MEDIAN_ENTITIES] == []
    assert set(updated.data[CONF_DEVICE_METADATA]) == {"Naunhof_Nr1", "Naunhof_Nr2"}


async def test_http_config_flow_happy_path(
    hass: HomeAssistant, hass_client, mock_integration_setup
):
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
    assert data["type"].lower() == "menu"
    assert data["step_id"] == "user"
    assert data["menu_options"] == ["search", "all_devices"]

    resp = await client.post(
        f"/api/config/config_entries/flow/{data['flow_id']}",
        json={"next_step_id": "all_devices"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["type"].lower() == "form"
    assert data["step_id"] == "device_selection"
    fields = {field["name"]: field for field in data["data_schema"]}
    assert set(fields) == {
        "stations",
        "water_level",
        "temperature_moisture",
        CONF_SELECTED_MEDIAN_ENTITIES,
    }
    assert all(field["selector"]["select"]["multiple"] for field in fields.values())
    assert {
        option["value"]
        for option in fields["water_level"]["selector"]["select"]["options"]
    } == {"PEGEL_001"}


async def test_http_config_flow_validation_no_selection(
    hass: HomeAssistant, hass_client, mock_integration_setup
):
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
    assert data["type"].lower() == "menu"


async def test_service_integration_functionality(
    hass: HomeAssistant, mock_config_service, mock_integration_setup
):
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
    parsed_data = await parser_service.parse_message(
        "test/topic", '{"temperature": 23.5}'
    )
    assert parsed_data is not None
    assert "temperature" in parsed_data

    # Test entity factory functionality
    entity_factory = hass.data[DOMAIN]["entity_factory"]
    entities = await entity_factory.create_sensor_entities()
    assert len(entities) == 1
    assert "entity_id" in entities[0]


async def test_config_flow_device_validation(
    hass: HomeAssistant, mock_config_service, mock_integration_setup
):
    """Test config flow validates device selection with actual device data."""
    mock_integration_setup(hass)

    # Start config flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.MENU
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "all_devices"}
    )

    # Test with empty selection - should show error
    result_empty = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "stations": [],
            CONF_SELECTED_MEDIAN_ENTITIES: [],
        },
    )
    assert result_empty["type"] == FlowResultType.MENU
    result_empty = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    assert result_empty["type"] == FlowResultType.FORM
    assert result_empty["errors"]["base"] == "mindestens_eine_auswahl"

    # Test with valid device selection
    result_valid = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "stations": ["Naunhof_Nr1"],
            CONF_SELECTED_MEDIAN_ENTITIES: ["median_Naunhof"],
        },
    )
    assert result_valid["type"] == FlowResultType.MENU
    result_valid = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )
    assert result_valid["type"] == FlowResultType.CREATE_ENTRY

    # Verify the data contains our selections
    assert result_valid["data"][CONF_SELECTED_DEVICES] == ["Naunhof_Nr1"]
    assert result_valid["data"][CONF_SELECTED_MEDIAN_ENTITIES] == ["median_Naunhof"]


async def test_integration_services_interaction(
    hass: HomeAssistant, mock_config_service, mock_integration_setup
):
    """Test that integration services work together properly."""
    mock_integration_setup(hass)

    # Test that all services are available
    assert DOMAIN in hass.data
    services = hass.data[DOMAIN]

    required_services = [
        "config_service",
        "mqtt_service",
        "parser_service",
        "entity_factory",
        "error_handler",
        "translation_helper",
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


async def test_user_flow_reports_catalog_connection_error(
    hass: HomeAssistant, mock_config_service, mock_integration_setup
):
    mock_integration_setup(hass)
    mock_config_service.get_selection_candidates.side_effect = DeviceCatalogError(
        "nicht erreichbar"
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_options_flow_keeps_filtered_existing_device(
    hass: HomeAssistant, mock_config_service, mock_integration_setup
):
    mock_integration_setup(hass)
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    mock_config_service.get_selection_candidates.return_value = {
        "senseBox": [
            {
                "id": "planned_existing",
                "name": "Bestehende Station",
                "type": "senseBox",
                "sensors": ["temperature"],
                "operationalstatus": "planned",
            }
        ]
    }
    mock_config_service.snapshot_devices.side_effect = lambda device_ids: {
        device_id: {
            "id": device_id,
            "name": "Bestehende Station",
            "type": "senseBox",
            "sensors": ["temperature"],
        }
        for device_id in device_ids
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        data={
            CONF_SELECTED_DEVICES: ["planned_existing"],
            CONF_SELECTED_MEDIAN_ENTITIES: ["median_removed"],
        },
        entry_id="planned-entry",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.MENU
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"next_step_id": "all_devices"},
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "stations": ["planned_existing"],
            CONF_SELECTED_MEDIAN_ENTITIES: ["median_removed"],
        },
    )
    assert result["type"] == FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_SELECTED_DEVICES] == ["planned_existing"]
    assert entry.data[CONF_SELECTED_MEDIAN_ENTITIES] == ["median_removed"]
    mock_config_service.get_selection_candidates.assert_awaited_with(
        ["planned_existing"]
    )


async def test_options_flow_removes_only_intentionally_deselected_device(
    hass: HomeAssistant, mock_config_service, mock_integration_setup
):
    """Die Gesamtansicht kann ein bestehendes Gerät bewusst entfernen."""
    mock_integration_setup(hass)
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        data={
            CONF_SELECTED_DEVICES: ["Naunhof_Nr1", "Naunhof_Nr2"],
            CONF_SELECTED_MEDIAN_ENTITIES: ["median_removed"],
        },
        entry_id="remove-entry",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "all_devices"}
    )
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "stations": ["Naunhof_Nr2"],
            CONF_SELECTED_MEDIAN_ENTITIES: [],
        },
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_SELECTED_DEVICES] == ["Naunhof_Nr2"]
    assert entry.data[CONF_SELECTED_MEDIAN_ENTITIES] == []
    assert set(entry.data[CONF_DEVICE_METADATA]) == {"Naunhof_Nr2"}


async def test_options_flow_api_failure_does_not_change_entry(
    hass: HomeAssistant, mock_config_service, mock_integration_setup
):
    """Ein Katalogfehler verändert den bestehenden Config Entry nicht."""
    mock_integration_setup(hass)
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    original_data = {
        CONF_SELECTED_DEVICES: ["Naunhof_Nr1"],
        CONF_SELECTED_MEDIAN_ENTITIES: ["median_Naunhof"],
        CONF_DEVICE_METADATA: {
            "Naunhof_Nr1": {
                "id": "Naunhof_Nr1",
                "name": "Station Naunhof Nr 1",
                "type": "senseBox",
                "sensors": ["temperature", "humidity"],
            }
        },
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        data=original_data,
        entry_id="offline-options-entry",
    )
    entry.add_to_hass(hass)
    mock_config_service.get_selection_candidates.side_effect = DeviceCatalogError(
        "nicht erreichbar"
    )
    mock_config_service.get_device_by_id.return_value = original_data[
        CONF_DEVICE_METADATA
    ]["Naunhof_Nr1"]

    mock_config_service.snapshot_devices.side_effect = lambda device_ids: {
        device_id: original_data[CONF_DEVICE_METADATA][device_id]
        for device_id in device_ids
    }

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "device_selection"
    assert result["errors"] == {"base": "cannot_connect"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "stations": ["Naunhof_Nr1"],
            CONF_SELECTED_MEDIAN_ENTITIES: ["median_Naunhof"],
        },
    )
    assert result["type"] == FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.data == original_data


async def test_options_flow_snapshot_failure_does_not_update_or_reload(
    hass: HomeAssistant, mock_config_service, mock_integration_setup
):
    """Ein Fehler beim finalen Snapshot lässt den Config Entry unangetastet."""
    mock_integration_setup(hass)
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    original_data = {
        CONF_SELECTED_DEVICES: ["Naunhof_Nr1"],
        CONF_SELECTED_MEDIAN_ENTITIES: [],
        CONF_DEVICE_METADATA: {
            "Naunhof_Nr1": {
                "id": "Naunhof_Nr1",
                "name": "Station Naunhof Nr 1",
                "type": "senseBox",
                "sensors": ["temperature", "humidity"],
            }
        },
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        data=original_data,
        entry_id="snapshot-error-entry",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "all_devices"}
    )
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"stations": ["Naunhof_Nr1", "Naunhof_Nr2"]}
    )
    mock_config_service.snapshot_devices.side_effect = DeviceCatalogError(
        "nicht erreichbar"
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "finish"}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data == original_data
    hass.config_entries.async_reload.assert_not_awaited()


async def test_migration_snapshots_api_metadata_and_legacy_sensors(
    hass: HomeAssistant, mocker
):
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        data={
            CONF_SELECTED_DEVICES: ["station"],
            CONF_SELECTED_MEDIAN_ENTITIES: [],
        },
        version=1,
        entry_id="migration-entry",
    )
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        "station_Temperatur",
        config_entry=entry,
    )
    mocker.patch(
        "custom_components.sensorbridge_partheland.config_service.ConfigService.async_get_catalog",
        new=mocker.AsyncMock(
            return_value=[
                {
                    "id": "station",
                    "name": "Station",
                    "type": "senseBox",
                    "sensors": [],
                    "sensor_metadata": {},
                    "topic_pattern": "senseBox:home/station",
                }
            ]
        ),
    )

    mocker.patch(
        "custom_components.sensorbridge_partheland.async_setup",
        new=mocker.AsyncMock(return_value=True),
    )
    setup_entry = mocker.patch(
        "custom_components.sensorbridge_partheland.async_setup_entry",
        new=mocker.AsyncMock(return_value=True),
    )
    loaded = await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert loaded is True
    setup_entry.assert_awaited_once_with(hass, entry)
    assert entry.version == 2
    assert entry.data[CONF_DEVICE_METADATA]["station"]["sensors"] == ["temperature"]


async def test_migration_loads_existing_entry_without_api(hass: HomeAssistant, mocker):
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        data={
            CONF_SELECTED_DEVICES: ["legacy_station"],
            CONF_SELECTED_MEDIAN_ENTITIES: ["median_Naunhof"],
        },
        version=1,
        entry_id="offline-migration-entry",
    )
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        "legacy_station_Temperatur",
        config_entry=entry,
    )
    mocker.patch(
        "custom_components.sensorbridge_partheland.config_service.ConfigService.async_get_catalog",
        new=mocker.AsyncMock(side_effect=DeviceCatalogError("offline")),
    )
    mocker.patch(
        "custom_components.sensorbridge_partheland.async_setup",
        new=mocker.AsyncMock(return_value=True),
    )
    setup_entry = mocker.patch(
        "custom_components.sensorbridge_partheland.async_setup_entry",
        new=mocker.AsyncMock(return_value=True),
    )

    loaded = await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert loaded is True
    setup_entry.assert_awaited_once_with(hass, entry)
    assert entry.version == 2
    assert entry.data[CONF_SELECTED_DEVICES] == ["legacy_station"]
    assert entry.data[CONF_SELECTED_MEDIAN_ENTITIES] == ["median_Naunhof"]
    assert entry.data[CONF_DEVICE_METADATA]["legacy_station"]["sensors"] == [
        "temperature"
    ]
