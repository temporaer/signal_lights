"""Shared test fixtures for signal_lights tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.signal_lights.manager import Manager


class FakeState:
    """Minimal stand-in for homeassistant.core.State."""

    def __init__(self, state: str, attributes: dict[str, Any] | None = None) -> None:
        self.state = state
        self.attributes = attributes or {}


class _StatesAccessor:
    def __init__(self, hass: FakeHass) -> None:
        self._hass = hass

    def get(self, entity_id: str) -> FakeState | None:
        return self._hass._states.get(entity_id)


class FakeHass:
    """Minimal hass mock for unit testing without full HA bootstrap."""

    def __init__(self) -> None:
        self._states: dict[str, FakeState] = {}
        self.services = MagicMock()
        self.services.async_call = AsyncMock()
        self.states = _StatesAccessor(self)
        self.data: dict[str, Any] = {}
        self.bus = MagicMock()
        self.bus.async_listen = MagicMock(return_value=lambda: None)
        self._tasks: list[Any] = []

    def set_state(self, entity_id: str, state: str, attributes: dict[str, Any] | None = None) -> None:
        self._states[entity_id] = FakeState(state, attributes)

    def async_create_task(self, coro: Any) -> None:
        self._tasks.append(coro)


@pytest.fixture
def hass() -> FakeHass:
    return FakeHass()


@pytest.fixture
def basic_config() -> dict[str, Any]:
    return {
        "renderers": {
            "kitchen": {
                "lights": ["light.kitchen_ceiling", "light.kitchen_counter"],
            },
        },
    }


@pytest.fixture
def config_with_rules() -> dict[str, Any]:
    return {
        "renderers": {
            "kitchen": {
                "lights": ["light.kitchen_ceiling"],
            },
            "hallway": {
                "lights": ["light.hallway"],
            },
        },
        "signal_rules": [
            {
                "rule_id": "doorbell",
                "source_entity": "binary_sensor.doorbell",
                "active_state": "on",
                "renderers": ["kitchen", "hallway"],
                "signal_id": "doorbell_ring",
                "color": [255, 50, 0],
                "duration": 5,
                "priority": 80,
                "mode": "transient",
            },
        ],
    }


@pytest.fixture
def manager(hass: FakeHass, basic_config: dict[str, Any]) -> Manager:
    """Create a Manager with basic config and lights initially off."""
    for rconf in basic_config["renderers"].values():
        for light in rconf["lights"]:
            hass.set_state(light, "off")
    return Manager(hass, basic_config)  # type: ignore[arg-type]


@pytest.fixture
def manager_with_rules(hass: FakeHass, config_with_rules: dict[str, Any]) -> Manager:
    """Create a Manager with rules. Source entities start as 'off'."""
    for rconf in config_with_rules["renderers"].values():
        for light in rconf["lights"]:
            hass.set_state(light, "off")
    for rule_conf in config_with_rules.get("signal_rules", []):
        hass.set_state(rule_conf["source_entity"], "off")
    return Manager(hass, config_with_rules)  # type: ignore[arg-type]
