"""
pytest configuration for SmartCity SensorBridge Partheland.

This file sets up the necessary configuration for pytest to run
Home Assistant custom component tests.
"""
import sys
import os
from pathlib import Path

# Add the project root to the Python path so custom_components can be imported
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Ensure custom_components path is available
custom_components_path = project_root / "custom_components"
if custom_components_path.exists():
    sys.path.insert(0, str(custom_components_path.parent))

import pytest
from unittest.mock import AsyncMock, patch

# Mock common Home Assistant components that might be needed
@pytest.fixture(autouse=True)
def mock_ha_components():
    """Auto-mock common HA components that might not be available in test environment."""
    with patch("homeassistant.helpers.entity_platform.async_get_current_platform"):
        with patch("homeassistant.helpers.device_registry.async_get"):
            with patch("homeassistant.helpers.entity_registry.async_get"):
                yield

@pytest.fixture
def hass_client():
    """Mock hass client for HTTP API testing."""
    return AsyncMock()
