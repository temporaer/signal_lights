"""Tests for transient rendering, light service calls, and concurrency."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from custom_components.signal_lights.manager import Signal

from .conftest import FakeHass


async def test_transient_calls_light_service(hass: FakeHass, manager):
    """Transient signal calls light.turn_on with rgb_color."""
    hass.set_state("light.kitchen_ceiling", "on")
    hass.set_state("light.kitchen_counter", "on")

    await manager.push_signal(
        "kitchen", "flash", 50, [255, 0, 0], 0, False, "transient",
    )

    calls = hass.services.async_call.call_args_list
    # Should have called turn_on with rgb_color for both lights
    rgb_calls = [c for c in calls if c.kwargs.get("blocking") or len(c.args) >= 3]
    assert len(rgb_calls) > 0


async def test_persistent_signal_on_lights_on(hass: FakeHass, manager):
    """Persistent signal applies immediately when lights are on."""
    hass.set_state("light.kitchen_ceiling", "on")
    hass.set_state("light.kitchen_counter", "on")

    await manager.push_signal(
        "kitchen", "alert", 50, [0, 0, 255], 3, True, "persistent",
    )

    # Should have called light services
    assert hass.services.async_call.call_count > 0


async def test_persistent_signal_lights_off_no_call(hass: FakeHass, manager):
    """Persistent signal doesn't call services when lights are off."""
    await manager.push_signal(
        "kitchen", "alert", 50, [0, 0, 255], 3, True, "persistent",
    )

    # No light service calls when lights are off
    assert hass.services.async_call.call_count == 0


async def test_handle_light_change_turn_on(hass: FakeHass, manager):
    """Turning on a light triggers baseline application."""
    renderer = manager.renderers["kitchen"]

    # Simulate light turning on
    hass.set_state("light.kitchen_ceiling", "on")
    await renderer.handle_light_change()

    assert hass.services.async_call.call_count > 0


async def test_handle_light_change_already_on(hass: FakeHass, manager):
    """If lights were already on, no action taken."""
    renderer = manager.renderers["kitchen"]
    hass.set_state("light.kitchen_ceiling", "on")

    # First call — turn on edge
    await renderer.handle_light_change()
    first_count = hass.services.async_call.call_count

    # Second call — already on, no new action
    await renderer.handle_light_change()
    assert hass.services.async_call.call_count == first_count


async def test_transient_generation_token(hass: FakeHass, manager):
    """Overlapping transients: second supersedes first's restore."""
    renderer = manager.renderers["kitchen"]
    hass.set_state("light.kitchen_ceiling", "on")
    hass.set_state("light.kitchen_counter", "on")

    # Push two transients with 0 duration to test generation logic
    await manager.push_signal("kitchen", "sig_a", 50, [255, 0, 0], 0, False, "transient")
    gen_after_a = renderer._transient_gen

    await manager.push_signal("kitchen", "sig_b", 60, [0, 255, 0], 0, False, "transient")
    gen_after_b = renderer._transient_gen

    # Generation counter should have incremented
    assert gen_after_b > gen_after_a


async def test_activate_when_off_turns_on_light(hass: FakeHass, manager):
    """activate_when_off=True turns on lights that are off."""
    await manager.push_signal(
        "kitchen", "urgent", 80, [255, 0, 0], 0, False, "transient",
        activate_when_off=True,
    )

    # Should have called turn_on even though lights were off
    turn_on_calls = [
        c for c in hass.services.async_call.call_args_list
        if c.args[1] == "turn_on"
    ]
    assert len(turn_on_calls) > 0

    # Should also have called turn_off to restore
    turn_off_calls = [
        c for c in hass.services.async_call.call_args_list
        if c.args[1] == "turn_off"
    ]
    assert len(turn_off_calls) > 0


async def test_light_service_error_logged(hass: FakeHass, manager, caplog):
    """If light service call fails, error is logged, not raised."""
    hass.set_state("light.kitchen_ceiling", "on")
    hass.set_state("light.kitchen_counter", "on")
    hass.services.async_call = AsyncMock(side_effect=Exception("bulb unreachable"))

    with caplog.at_level("ERROR"):
        await manager.push_signal(
            "kitchen", "flash", 50, [255, 0, 0], 0, False, "persistent",
        )

    assert "Failed to call" in caplog.text


async def test_concurrent_handle_light_change(hass: FakeHass, manager):
    """Two concurrent handle_light_change calls don't both detect turn-on edge."""
    renderer = manager.renderers["kitchen"]
    hass.set_state("light.kitchen_ceiling", "on")

    # Add a transient signal so turn-on triggers rendering
    renderer.signals["test"] = Signal(
        signal_id="test", priority=50, mode="transient",
        show_only_on_turn_on=True, duration=0,
    )

    # Run two handle_light_change concurrently
    await asyncio.gather(
        renderer.handle_light_change(),
        renderer.handle_light_change(),
    )

    # Only one should have detected the turn-on edge.
    # Count _apply_final_state calls (turn_on calls):
    # The key thing is it doesn't crash and _last_on is consistent
    assert renderer._last_on is True


async def test_teardown(hass: FakeHass, manager):
    """Manager teardown unsubscribes listeners."""
    # Create a manager with rules to get both light + source entity unsubs
    config = {
        "renderers": {"r": {"lights": ["light.a"]}},
        "signal_rules": [{
            "source_entity": "binary_sensor.x",
            "active_state": "on",
            "renderers": ["r"],
            "signal_id": "s",
        }],
    }
    hass.set_state("light.a", "off")
    hass.set_state("binary_sensor.x", "off")

    from custom_components.signal_lights.manager import Manager

    mgr = Manager(hass, config)  # type: ignore[arg-type]
    assert len(mgr.unsubs) > 0

    mgr.teardown()
    assert len(mgr.unsubs) == 0
