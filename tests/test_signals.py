"""Tests for signal push/clear, priority resolution, and renderer state."""

from __future__ import annotations

import pytest

from custom_components.signal_lights.manager import Signal

from .conftest import FakeHass


async def test_push_signal_basic(hass: FakeHass, manager):
    """Pushing a signal stores it on the renderer."""
    await manager.push_signal("kitchen", "test_sig", 50, [255, 0, 0], 3, True, "transient")
    renderer = manager.renderers["kitchen"]
    assert "test_sig" in renderer.signals
    assert renderer.signals["test_sig"].color == (255, 0, 0)


async def test_clear_signal(hass: FakeHass, manager):
    """Clearing a signal removes it."""
    await manager.push_signal("kitchen", "test_sig", 50, [255, 0, 0], 3, True, "persistent")
    await manager.clear_signal("kitchen", "test_sig")
    renderer = manager.renderers["kitchen"]
    assert "test_sig" not in renderer.signals


async def test_clear_nonexistent_signal(hass: FakeHass, manager):
    """Clearing a signal that doesn't exist is a no-op."""
    await manager.clear_signal("kitchen", "no_such_signal")


async def test_unknown_renderer_push(hass: FakeHass, manager):
    """Pushing to unknown renderer raises ServiceValidationError."""
    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises(ServiceValidationError, match="Unknown renderer_id"):
        await manager.push_signal("nonexistent", "sig", 50, [0, 0, 0], 1, True, "transient")


async def test_unknown_renderer_clear(hass: FakeHass, manager):
    """Clearing from unknown renderer raises ServiceValidationError."""
    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises(ServiceValidationError, match="Unknown renderer_id"):
        await manager.clear_signal("nonexistent", "sig")


async def test_priority_resolution(hass: FakeHass, manager):
    """Higher priority signal wins effective signal."""
    renderer = manager.renderers["kitchen"]
    renderer.signals["low"] = Signal(signal_id="low", priority=10, mode="transient")
    renderer.signals["high"] = Signal(signal_id="high", priority=90, mode="transient")
    renderer.signals["med"] = Signal(signal_id="med", priority=50, mode="transient")

    eff = renderer.get_effective_signal("transient")
    assert eff is not None
    assert eff.signal_id == "high"


async def test_priority_separate_modes(hass: FakeHass, manager):
    """Effective signal is resolved per mode."""
    renderer = manager.renderers["kitchen"]
    renderer.signals["t1"] = Signal(signal_id="t1", priority=80, mode="transient")
    renderer.signals["p1"] = Signal(signal_id="p1", priority=90, mode="persistent")

    assert renderer.get_effective_signal("transient").signal_id == "t1"
    assert renderer.get_effective_signal("persistent").signal_id == "p1"


async def test_renderer_state_idle(hass: FakeHass, manager):
    renderer = manager.renderers["kitchen"]
    assert renderer.state == "idle"


async def test_renderer_state_with_signals(hass: FakeHass, manager):
    renderer = manager.renderers["kitchen"]
    renderer.signals["p1"] = Signal(signal_id="p1", priority=50, mode="persistent")
    assert renderer.state == "persistent:p1"

    renderer.signals["t1"] = Signal(signal_id="t1", priority=50, mode="transient")
    assert renderer.state == "transient:t1"


async def test_renderer_attributes(hass: FakeHass, manager):
    renderer = manager.renderers["kitchen"]
    attrs = renderer.attributes
    assert attrs["renderer_id"] == "kitchen"
    assert "light.kitchen_ceiling" in attrs["lights"]
    assert attrs["any_on"] is False


async def test_notify_dedup(hass: FakeHass, manager):
    """Notify without force deduplicates by key."""
    renderer = manager.renderers["kitchen"]
    calls = []
    renderer.add_listener(lambda: calls.append(1))

    renderer.notify(force=True)
    renderer.notify()  # same key, should be deduped
    renderer.notify()
    assert len(calls) == 1

    renderer.notify(force=True)
    assert len(calls) == 2


async def test_remove_listener(hass: FakeHass, manager):
    """Remove listener stops notifications."""
    renderer = manager.renderers["kitchen"]
    calls = []
    listener = lambda: calls.append(1)  # noqa: E731
    renderer.add_listener(listener)
    renderer.notify(force=True)
    assert len(calls) == 1

    renderer.remove_listener(listener)
    renderer.notify(force=True)
    assert len(calls) == 1  # no new call


async def test_remove_listener_not_found(hass: FakeHass, manager):
    """Removing a listener that was never added is safe."""
    renderer = manager.renderers["kitchen"]
    renderer.remove_listener(lambda: None)  # should not raise
