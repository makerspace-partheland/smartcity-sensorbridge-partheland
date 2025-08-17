"""Pytest configuration for SmartCity SensorBridge Partheland."""
import sys
from pathlib import Path

# Add the project root to the Python path so custom_components can be imported
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest

# Import all fixtures from pytest-homeassistant-custom-component
pytest_plugins = "pytest_homeassistant_custom_component"

# Note: enable_custom_integrations will be used per test as needed
# No autouse fixture to avoid async_generator issues
