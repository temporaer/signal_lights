"""Tests that verify the exact README walkthrough scenarios."""

from __future__ import annotations

from custom_components.signal_lights.manager import Manager

from .conftest import FakeHass


async def test_scenario_washing_machine(hass: FakeHass):
    """Scenario 1: transient flash only on light turn-on, nothing before."""
    config = {
        "renderers": {
            "hallway": {
                "lights": ["light.hallway"],
                "time_window": {"start": "06:00", "end": "23:00"},
            },
        },
        "signal_rules": [
            {
                "rule_id": "washing_done",
                "source_entity": "binary_sensor.washing_machine",
                "active_state": "on",
                "renderers": ["hallway"],
                "signal_id": "washing_done",
                "color": [0, 255, 50],
                "duration": 0,  # 0 for fast test
                "priority": 50,
                "mode": "transient",
                "show_only_on_turn_on": True,
            },
        ],
    }
    hass.set_state("light.hallway", "off")
    hass.set_state("binary_sensor.washing_machine", "off")
    mgr = Manager(hass, config)  # type: ignore[arg-type]
    renderer = mgr.renderers["hallway"]

    # Step 1: washing machine finishes — signal registered but no light calls
    hass.set_state("binary_sensor.washing_machine", "on")
    await mgr._apply_rule_async(mgr.rules[0])
    assert "washing_done" in renderer.signals
    assert hass.services.async_call.call_count == 0  # nothing visible

    # Step 2: light turns on — should flash then restore baseline
    hass.set_state("light.hallway", "on")
    hass.services.async_call.reset_mock()
    await renderer.handle_light_change()

    calls = hass.services.async_call.call_args_list
    # Should have turn_on calls (baseline + flash + restore)
    assert len(calls) > 0
    # Check that rgb_color was used in at least one call (the flash)
    rgb_calls = [c for c in calls if "rgb_color" in c.args[2]]
    assert len(rgb_calls) >= 1
    assert rgb_calls[0].args[2]["rgb_color"] == [0, 255, 50]

    # Step 3: washing machine cleared — signal removed
    hass.set_state("binary_sensor.washing_machine", "off")
    await mgr._apply_rule_async(mgr.rules[0])
    assert "washing_done" not in renderer.signals


async def test_scenario_letterbox_persistent_survives_transient(hass: FakeHass):
    """Scenario 2: after transient flash with activate_when_off, persistent keeps light on."""
    config = {
        "renderers": {
            "entrance": {
                "lights": ["light.entrance"],
                "time_window": {"start": "07:00", "end": "22:00"},
            },
        },
        "signal_rules": [
            {
                "rule_id": "mail_persistent",
                "source_entity": "binary_sensor.letterbox",
                "active_state": "on",
                "renderers": ["entrance"],
                "signal_id": "mail_waiting",
                "color": [30, 100, 255],
                "priority": 60,
                "mode": "persistent",
                "activate_when_off": False,
            },
            {
                "rule_id": "mail_motion_flash",
                "source_entity": "binary_sensor.front_door_motion",
                "active_state": "on",
                "renderers": ["entrance"],
                "signal_id": "mail_flash",
                "color": [30, 100, 255],
                "duration": 0,  # 0 for fast test
                "priority": 70,
                "mode": "transient",
                "show_only_on_turn_on": False,
                "activate_when_off": True,
            },
        ],
    }
    hass.set_state("light.entrance", "off")
    hass.set_state("binary_sensor.letterbox", "off")
    hass.set_state("binary_sensor.front_door_motion", "off")
    mgr = Manager(hass, config)  # type: ignore[arg-type]
    renderer = mgr.renderers["entrance"]

    # Step 1: mail arrives — persistent signal registered, light is off → no calls
    hass.set_state("binary_sensor.letterbox", "on")
    await mgr._apply_rule_async(mgr.rules[0])
    assert "mail_waiting" in renderer.signals
    assert hass.services.async_call.call_count == 0

    # Step 2: motion detected — transient with activate_when_off
    hass.set_state("binary_sensor.front_door_motion", "on")
    hass.services.async_call.reset_mock()
    await mgr._apply_rule_async(mgr.rules[1])

    calls = hass.services.async_call.call_args_list
    # Should have turned the light on (activate_when_off) and flashed
    turn_on_calls = [c for c in calls if c.args[1] == "turn_on"]
    assert len(turn_on_calls) >= 1

    # KEY ASSERTION: light should turn OFF after flash,
    # because it was off before we woke it. The persistent signal
    # will show next time the user intentionally turns the light on.
    turn_off_calls = [c for c in calls if c.args[1] == "turn_off"]
    assert len(turn_off_calls) >= 1, (
        "Light should turn off after transient flash (was off before)"
    )

    # Step 3: clearing letterbox only clears mail_persistent, not mail_flash
    hass.set_state("binary_sensor.letterbox", "off")
    await mgr._apply_rule_async(mgr.rules[0])
    assert "mail_waiting" not in renderer.signals
    # mail_flash should still be present (tied to motion sensor)
    assert "mail_flash" in renderer.signals

    # Step 4: clearing motion clears the transient
    hass.set_state("binary_sensor.front_door_motion", "off")
    await mgr._apply_rule_async(mgr.rules[1])
    assert "mail_flash" not in renderer.signals


async def test_scenario_letterbox_turn_on_shows_persistent(hass: FakeHass):
    """Scenario 2 continued: turning on the light normally shows persistent blue."""
    config = {
        "renderers": {
            "entrance": {
                "lights": ["light.entrance"],
            },
        },
        "signal_rules": [
            {
                "rule_id": "mail_persistent",
                "source_entity": "binary_sensor.letterbox",
                "active_state": "on",
                "renderers": ["entrance"],
                "signal_id": "mail_waiting",
                "color": [30, 100, 255],
                "priority": 60,
                "mode": "persistent",
            },
        ],
    }
    hass.set_state("light.entrance", "off")
    hass.set_state("binary_sensor.letterbox", "on")
    mgr = Manager(hass, config)  # type: ignore[arg-type]
    renderer = mgr.renderers["entrance"]
    assert "mail_waiting" in renderer.signals

    # Turn on the light
    hass.set_state("light.entrance", "on")
    hass.services.async_call.reset_mock()
    await renderer.handle_light_change()

    # Should apply persistent blue, not baseline
    calls = hass.services.async_call.call_args_list
    rgb_calls = [c for c in calls if "rgb_color" in c.args[2]]
    assert len(rgb_calls) >= 1
    assert rgb_calls[0].args[2]["rgb_color"] == [30, 100, 255]


async def test_scenario_priority_doorbell_wins(hass: FakeHass):
    """Scenario 3: doorbell (p80) beats washing (p50), washing survives after doorbell clears."""
    config = {
        "renderers": {
            "kitchen": {
                "lights": ["light.kitchen"],
            },
        },
        "signal_rules": [
            {
                "rule_id": "washing",
                "source_entity": "binary_sensor.washing_machine",
                "active_state": "on",
                "renderers": ["kitchen"],
                "signal_id": "washing_done",
                "color": [0, 255, 50],
                "duration": 0,
                "priority": 50,
                "mode": "transient",
                "show_only_on_turn_on": True,
            },
            {
                "rule_id": "doorbell",
                "source_entity": "binary_sensor.doorbell",
                "active_state": "on",
                "renderers": ["kitchen"],
                "signal_id": "doorbell_ring",
                "color": [255, 50, 0],
                "duration": 0,
                "priority": 80,
                "mode": "transient",
                "show_only_on_turn_on": True,
                "activate_when_off": True,
            },
        ],
    }
    hass.set_state("light.kitchen", "off")
    hass.set_state("binary_sensor.washing_machine", "off")
    hass.set_state("binary_sensor.doorbell", "off")
    mgr = Manager(hass, config)  # type: ignore[arg-type]
    renderer = mgr.renderers["kitchen"]

    # Both signals fire
    hass.set_state("binary_sensor.washing_machine", "on")
    await mgr._apply_rule_async(mgr.rules[0])
    hass.set_state("binary_sensor.doorbell", "on")
    await mgr._apply_rule_async(mgr.rules[1])

    # Effective transient should be doorbell (higher priority)
    eff = renderer.get_effective_signal("transient")
    assert eff is not None
    assert eff.signal_id == "doorbell_ring"

    # Light turns on — doorbell signal rendered (highest priority)
    hass.set_state("light.kitchen", "on")
    hass.services.async_call.reset_mock()
    await renderer.handle_light_change()

    calls = hass.services.async_call.call_args_list
    rgb_calls = [c for c in calls if "rgb_color" in c.args[2]]
    assert any(c.args[2]["rgb_color"] == [255, 50, 0] for c in rgb_calls), (
        "Doorbell color should be rendered"
    )

    # Doorbell clears — washing is still queued
    hass.set_state("binary_sensor.doorbell", "off")
    await mgr._apply_rule_async(mgr.rules[1])
    assert "doorbell_ring" not in renderer.signals
    assert "washing_done" in renderer.signals

    # Simulate light off then on — washing should now flash
    hass.set_state("light.kitchen", "off")
    await renderer.handle_light_change()
    hass.set_state("light.kitchen", "on")
    hass.services.async_call.reset_mock()
    await renderer.handle_light_change()

    calls = hass.services.async_call.call_args_list
    rgb_calls = [c for c in calls if "rgb_color" in c.args[2]]
    assert any(c.args[2]["rgb_color"] == [0, 255, 50] for c in rgb_calls), (
        "Washing color should be rendered after doorbell cleared"
    )
