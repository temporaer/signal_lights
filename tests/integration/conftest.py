"""Use a real Home Assistant instance for integration-level tests."""

import pytest
from pytest_homeassistant_custom_component.plugins import hass as hass


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Load the integration from this checkout."""
