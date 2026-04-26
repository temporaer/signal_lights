"""Tests for debugging/diagnostics improvements."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from custom_components.signal_lights.const import (
    EVENT_SIGNAL_CLEARED,
    EVENT_SIGNAL_PUSHED,
    EVENT_SIGNAL_RENDERED,
)
from custom_components.signal_lights.manager import Manager

from .conftest import FakeHass

# ── Event firing ──


async def test_push_signal_fires_pushed_event(
    hass: FakeHass, manager: Manager,
) -> None:
    """push_signal should fire EVENT_SIGNAL_PUSHED."""
    await manager.push_signal("kitchen", "test1", 50, [255, 0, 0], 3, True, "transient")
    calls = [c for c in hass.bus.async_fire.call_args_list if c[0][0] == EVENT_SIGNAL_PUSHED]
    assert len(calls) == 1
    data = calls[0][0][1]
    assert data["renderer_id"] == "kitchen"
    assert data["signal_id"] == "test1"
    assert data["source"] == "manual"


async def test_clear_signal_fires_cleared_event(
    hass: FakeHass, manager: Manager,
) -> None:
    """clear_signal should fire EVENT_SIGNAL_CLEARED."""
    await manager.push_signal("kitchen", "test1", 50, [255, 0, 0], 3, True, "transient")
    hass.bus.async_fire.reset_mock()
    await manager.clear_signal("kitchen", "test1")
    calls = [c for c in hass.bus.async_fire.call_args_list if c[0][0] == EVENT_SIGNAL_CLEARED]
    assert len(calls) == 1
    assert calls[0][0][1]["signal_id"] == "test1"


async def test_persistent_render_fires_rendered_event(
    hass: FakeHass, manager: Manager,
) -> None:
    """Rendering a persistent signal fires EVENT_SIGNAL_RENDERED."""
    hass.set_state("light.kitchen_ceiling", "on")
    await manager.push_signal("kitchen", "mail", 50, [0, 255, 0], 3, True, "persistent")
    calls = [c for c in hass.bus.async_fire.call_args_list if c[0][0] == EVENT_SIGNAL_RENDERED]
    assert len(calls) >= 1
    data = calls[0][0][1]
    assert data["mode"] == "persistent"
    assert data["signal_id"] == "mail"


async def test_transient_render_fires_rendered_event(
    hass: FakeHass, manager: Manager,
) -> None:
    """Rendering a transient signal fires EVENT_SIGNAL_RENDERED."""
    hass.set_state("light.kitchen_ceiling", "on")
    with patch("custom_components.signal_lights.manager.asyncio.sleep"):
        await manager.push_signal(
            "kitchen", "flash", 50, [255, 0, 0], 1,
            show_only_on_turn_on=False, mode="transient",
        )
    calls = [c for c in hass.bus.async_fire.call_args_list if c[0][0] == EVENT_SIGNAL_RENDERED]
    assert len(calls) >= 1
    data = calls[0][0][1]
    assert data["mode"] == "transient"
    assert data["signal_id"] == "flash"


async def test_rule_fires_events(
    hass: FakeHass, manager_with_rules: Manager,
) -> None:
    """Rule activation/deactivation fires pushed/cleared events."""
    hass.bus.async_fire.reset_mock()
    # Activate rule
    hass.set_state("binary_sensor.doorbell", "on")
    for rule in manager_with_rules.source_entity_to_rules.get("binary_sensor.doorbell", []):
        await manager_with_rules._apply_rule_async(rule)
    pushed = [c for c in hass.bus.async_fire.call_args_list if c[0][0] == EVENT_SIGNAL_PUSHED]
    assert len(pushed) >= 1

    hass.bus.async_fire.reset_mock()
    # Deactivate rule
    hass.set_state("binary_sensor.doorbell", "off")
    for rule in manager_with_rules.source_entity_to_rules.get("binary_sensor.doorbell", []):
        await manager_with_rules._apply_rule_async(rule)
    cleared = [c for c in hass.bus.async_fire.call_args_list if c[0][0] == EVENT_SIGNAL_CLEARED]
    assert len(cleared) >= 1


# ── Last rendered tracking ──


async def test_last_rendered_attrs_initially_none(manager: Manager) -> None:
    renderer = manager.renderers["kitchen"]
    attrs = renderer.attributes
    assert attrs["last_rendered_signal_id"] is None
    assert attrs["last_rendered_at"] is None
    assert attrs["last_rendered_mode"] is None


async def test_last_rendered_attrs_after_persistent(
    hass: FakeHass, manager: Manager,
) -> None:
    hass.set_state("light.kitchen_ceiling", "on")
    await manager.push_signal("kitchen", "mail", 50, [0, 255, 0], 3, True, "persistent")
    renderer = manager.renderers["kitchen"]
    attrs = renderer.attributes
    assert attrs["last_rendered_signal_id"] == "mail"
    assert attrs["last_rendered_at"] is not None
    assert attrs["last_rendered_mode"] == "persistent"


async def test_last_rendered_attrs_after_transient(
    hass: FakeHass, manager: Manager,
) -> None:
    hass.set_state("light.kitchen_ceiling", "on")
    with patch("custom_components.signal_lights.manager.asyncio.sleep"):
        await manager.push_signal(
            "kitchen", "flash", 50, [255, 0, 0], 1,
            show_only_on_turn_on=False, mode="transient",
        )
    renderer = manager.renderers["kitchen"]
    attrs = renderer.attributes
    assert attrs["last_rendered_signal_id"] == "flash"
    assert attrs["last_rendered_mode"] == "transient"


# ── dump_state ──


async def test_dump_state_returns_all_renderers(
    hass: FakeHass, manager: Manager,
) -> None:
    await manager.push_signal("kitchen", "test1", 50, [255, 0, 0], 3, True, "transient")
    snapshot = manager.dump_state()
    assert "kitchen" in snapshot
    assert snapshot["kitchen"]["signal_count"] == 1
    assert "test1" in snapshot["kitchen"]["signals"]


async def test_dump_state_logs_at_info(
    hass: FakeHass, manager: Manager, caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        manager.dump_state()
    assert any("state dump" in r.message.lower() for r in caplog.records)


# ── test_signal ──


async def test_test_signal_flashes_and_restores(
    hass: FakeHass, manager: Manager,
) -> None:
    """test_signal should flash then restore, leaving no stored signal."""
    hass.set_state("light.kitchen_ceiling", "on")
    with patch("custom_components.signal_lights.manager.asyncio.sleep"):
        await manager.test_signal("kitchen", [255, 0, 0], 1)
    renderer = manager.renderers["kitchen"]
    # No signal should be stored after test
    assert "__test__" not in renderer.signals
    # But light service should have been called
    assert hass.services.async_call.call_count > 0


async def test_test_signal_activate_when_off(
    hass: FakeHass, manager: Manager,
) -> None:
    """test_signal with activate_when_off should wake lights."""
    with patch("custom_components.signal_lights.manager.asyncio.sleep"):
        await manager.test_signal("kitchen", [0, 255, 0], 1, activate_when_off=True)
    assert hass.services.async_call.call_count > 0


# ── Config validation warnings ──


def test_validate_config_warns_missing_source_entity(
    hass: FakeHass, caplog: pytest.LogCaptureFixture,
) -> None:
    """Warns when rule source_entity doesn't exist."""
    config = {
        "renderers": {"r1": {"lights": ["light.r1"]}},
        "signal_rules": [{
            "source_entity": "binary_sensor.nonexistent",
            "active_state": "on",
            "renderers": ["r1"],
            "signal_id": "test",
        }],
    }
    hass.set_state("light.r1", "off")
    with caplog.at_level(logging.WARNING):
        Manager(hass, config)  # type: ignore[arg-type]
    assert any("does not exist" in r.message and "nonexistent" in r.message for r in caplog.records)


def test_validate_config_warns_missing_light(
    hass: FakeHass, caplog: pytest.LogCaptureFixture,
) -> None:
    """Warns when renderer light doesn't exist."""
    config = {"renderers": {"r1": {"lights": ["light.missing"]}}}
    with caplog.at_level(logging.WARNING):
        Manager(hass, config)  # type: ignore[arg-type]
    assert any("does not exist" in r.message and "light.missing" in r.message for r in caplog.records)


def test_validate_config_warns_duplicate_signal_ids(
    hass: FakeHass, caplog: pytest.LogCaptureFixture,
) -> None:
    """Warns when multiple rules target same signal_id on same renderer."""
    config = {
        "renderers": {"r1": {"lights": ["light.r1"]}},
        "signal_rules": [
            {
                "rule_id": "rule_a",
                "source_entity": "binary_sensor.a",
                "active_state": "on",
                "renderers": ["r1"],
                "signal_id": "dup_signal",
            },
            {
                "rule_id": "rule_b",
                "source_entity": "binary_sensor.b",
                "active_state": "on",
                "renderers": ["r1"],
                "signal_id": "dup_signal",
            },
        ],
    }
    hass.set_state("light.r1", "off")
    hass.set_state("binary_sensor.a", "off")
    hass.set_state("binary_sensor.b", "off")
    with caplog.at_level(logging.WARNING):
        Manager(hass, config)  # type: ignore[arg-type]
    assert any("multiple rules" in r.message and "dup_signal" in r.message for r in caplog.records)
