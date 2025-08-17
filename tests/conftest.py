"""
pytest configuration for SmartCity SensorBridge Partheland.

This file sets up the necessary configuration for pytest to run
Home Assistant custom component tests using pytest-homeassistant-custom-component.
"""
import sys
from pathlib import Path

# Add the project root to the Python path so custom_components can be imported
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest

# Import from pytest-homeassistant-custom-component
pytest_plugins = "pytest_homeassistant_custom_component"

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests (required for HA >=2021.6.0b0)."""
    yield
