import pytest
from typing import Any, Dict

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from aiohttp import ClientSession

from custom_components.sensorbridge_partheland.const import (
    DOMAIN,
    NAME,
    CONF_SELECTED_DEVICES,
    CONF_SELECTED_MEDIAN_ENTITIES,
)


@pytest.fixture
def mock_config_service(mocker):
    """Mock für ConfigService mit deterministischen Antworten."""
    mock = mocker.patch(
        "custom_components.sensorbridge_partheland.config_flow.ConfigService",
        autospec=True,
    )
    instance = mock.return_value
    instance.validate_config.return_value = True
    instance.get_devices.return_value = {
        "sensebox": [
            {"id": "Naunhof_Nr1", "name": "Station Naunhof Nr 1", "sensors": [1, 2]},
            {"id": "Naunhof_Nr2", "name": "Station Naunhof Nr 2", "sensors": [1]},
        ],
    }
    instance.get_device_categories.return_value = {"sensebox": "SenseBox"}
    instance.get_ui_text.return_value = {"sensors": "Sensoren"}
    instance.get_median_entities.return_value = [
        {"id": "Median_Naunhof", "name": "Median Naunhof", "sensors": [1, 2, 3]}
    ]
    return instance


async def test_user_flow_shows_selection_form(hass: HomeAssistant, enable_custom_integrations, mock_config_service):
    """Start des Flows zeigt Auswahlformular, wenn noch nichts gewählt ist."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "device_selection"


async def test_user_flow_abort_if_already_configured(hass: HomeAssistant, enable_custom_integrations, mock_config_service):
    """Ein zweiter Start sollte abbrechen, wenn bereits ein Eintrag existiert."""
    entry = config_entries.ConfigEntry(
        version=1,
        domain=DOMAIN,
        title=NAME,
        data={CONF_SELECTED_DEVICES: [], CONF_SELECTED_MEDIAN_ENTITIES: []},
        source=config_entries.SOURCE_USER,
        entry_id="test",
    )
    hass.config_entries._entries.append(entry)  # inject existierenden Eintrag

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.ABORT


async def test_user_flow_create_entry(hass: HomeAssistant, enable_custom_integrations, mock_config_service):
    """Erstellen eines Eintrags nach Auswahl von Geräten/Median-Entities."""
    # Start
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM

    # Auswahl bestätigen
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SELECTED_DEVICES: ["Naunhof_Nr1"],
            CONF_SELECTED_MEDIAN_ENTITIES: ["Median_Naunhof"],
        },
    )
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == NAME
    assert result2["data"][CONF_SELECTED_DEVICES] == ["Naunhof_Nr1"]
    assert result2["data"][CONF_SELECTED_MEDIAN_ENTITIES] == ["Median_Naunhof"]


async def test_options_flow_sync_entry(hass: HomeAssistant, enable_custom_integrations, mock_config_service):
    """Optionsflow startet synchron (kein Coroutine) und aktualisiert den Eintrag."""
    entry = config_entries.ConfigEntry(
        version=1,
        domain=DOMAIN,
        title=NAME,
        data={CONF_SELECTED_DEVICES: ["Naunhof_Nr1"], CONF_SELECTED_MEDIAN_ENTITIES: []},
        source=config_entries.SOURCE_USER,
        entry_id="test2",
    )
    hass.config_entries._entries.append(entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "device_selection"

    # Update Auswahl
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SELECTED_DEVICES: ["Naunhof_Nr1", "Naunhof_Nr2"],
            CONF_SELECTED_MEDIAN_ENTITIES: ["Median_Naunhof"],
        },
    )
    assert result2["type"] == FlowResultType.CREATE_ENTRY

    # Stelle sicher, dass Daten aktualisiert wurden
    updated = next(e for e in hass.config_entries._entries if e.entry_id == entry.entry_id)
    assert updated.data[CONF_SELECTED_DEVICES] == ["Naunhof_Nr1", "Naunhof_Nr2"]
    assert updated.data[CONF_SELECTED_MEDIAN_ENTITIES] == ["Median_Naunhof"]


async def test_http_config_flow_happy_path(hass: HomeAssistant, enable_custom_integrations, hass_client, mock_config_service):
    """HTTP-API: Start und Abschluss des Config Flows wie die UI es tut."""
    client = await hass_client()

    # Init Flow (POST /api/config/config_entries/flow)
    resp = await client.post(
        "/api/config/config_entries/flow",
        json={"handler": DOMAIN, "show_advanced_options": False},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["type"].lower() == "form"
    flow_id = data["flow_id"]

    # Proceed step (POST /api/config/config_entries/flow/{flow_id})
    resp2 = await client.post(
        f"/api/config/config_entries/flow/{flow_id}",
        json={
            "user_input": {
                CONF_SELECTED_DEVICES: ["Naunhof_Nr1"],
                CONF_SELECTED_MEDIAN_ENTITIES: ["Median_Naunhof"],
            }
        },
    )
    assert resp2.status == 200
    data2 = await resp2.json()
    assert data2["type"].lower() == "create_entry"
    assert data2["title"] == NAME


async def test_http_config_flow_validation_no_selection(hass: HomeAssistant, enable_custom_integrations, hass_client, mock_config_service):
    """HTTP-API: Validierung greift bei leerer Auswahl (Fehler im Formular)."""
    client = await hass_client()

    resp = await client.post(
        "/api/config/config_entries/flow",
        json={"handler": DOMAIN, "show_advanced_options": False},
    )
    data = await resp.json()
    flow_id = data["flow_id"]

    resp2 = await client.post(
        f"/api/config/config_entries/flow/{flow_id}", json={"user_input": {}}
    )
    assert resp2.status == 200
    data2 = await resp2.json()
    assert data2["type"].lower() == "form"
    assert data2.get("errors", {}).get("base")


async def test_http_options_flow_happy_path(hass: HomeAssistant, enable_custom_integrations, hass_client, mock_config_service):
    """HTTP-API: Start und Abschluss des Optionsflows (spiegelt UI)."""
    # Vorhandenen Entry anlegen
    entry = config_entries.ConfigEntry(
        version=1,
        domain=DOMAIN,
        title=NAME,
        data={CONF_SELECTED_DEVICES: ["Naunhof_Nr1"], CONF_SELECTED_MEDIAN_ENTITIES: []},
        source=config_entries.SOURCE_USER,
        entry_id="opt-http",
    )
    hass.config_entries._entries.append(entry)

    client = await hass_client()

    # Init Options Flow
    resp = await client.post(
        "/api/config/config_entries/options/flow",
        json={"handler": DOMAIN, "config_entry_id": entry.entry_id},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["type"].lower() == "form"
    flow_id = data["flow_id"]

    # Proceed Options step
    resp2 = await client.post(
        f"/api/config/config_entries/options/flow/{flow_id}",
        json={
            "user_input": {
                CONF_SELECTED_DEVICES: ["Naunhof_Nr1"],
                CONF_SELECTED_MEDIAN_ENTITIES: ["Median_Naunhof"],
            }
        },
    )
    assert resp2.status == 200
    data2 = await resp2.json()
    assert data2["type"].lower() == "create_entry"


