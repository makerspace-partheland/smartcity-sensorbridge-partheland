"""Pytest configuration for SmartCity SensorBridge Partheland."""
import sys
from pathlib import Path

# Add the project root to the Python path so custom_components can be imported
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Automatically enable custom integrations for all tests."""
    yield
