"""Pytest configuration for SmartCity SensorBridge Partheland."""
import pytest

# Import all fixtures from pytest-homeassistant-custom-component
pytest_plugins = "pytest_homeassistant_custom_component"

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests."""
    return enable_custom_integrations
