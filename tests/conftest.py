"""Pytest configuration for SmartCity SensorBridge Partheland."""
import sys
from pathlib import Path

# Add the project root to the Python path so custom_components can be imported
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest

# Import all fixtures from pytest-homeassistant-custom-component
pytest_plugins = "pytest_homeassistant_custom_component"

# Ensure custom_components path is available
custom_components_path = project_root / "custom_components"
if custom_components_path.exists() and str(custom_components_path.parent) not in sys.path:
    sys.path.insert(0, str(custom_components_path.parent))
