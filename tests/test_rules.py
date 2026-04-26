"""Tests for signal rules: initial application and state changes."""

from __future__ import annotations

from .conftest import FakeHass


async def test_rule_initial_inactive(hass: FakeHass, manager_with_rules):
    """When source entity is off, rule doesn't apply signals."""
    renderer = manager_with_rules.renderers["kitchen"]
    assert "doorbell_ring" not in renderer.signals


async def test_rule_initial_active(hass: FakeHass, config_with_rules):
    """When source entity is already on at init, rule applies signal."""
    for rconf in config_with_rules["renderers"].values():
        for light in rconf["lights"]:
            hass.set_state(light, "off")
    hass.set_state("binary_sensor.doorbell", "on")

    from custom_components.signal_lights.manager import Manager

    mgr = Manager(hass, config_with_rules)  # type: ignore[arg-type]
    assert "doorbell_ring" in mgr.renderers["kitchen"].signals
    assert "doorbell_ring" in mgr.renderers["hallway"].signals
    sig = mgr.renderers["kitchen"].signals["doorbell_ring"]
    assert sig.source == "rule:doorbell"
    assert sig.priority == 80
    assert sig.color == (255, 50, 0)


async def test_rule_applies_to_all_renderers(hass: FakeHass, config_with_rules):
    """Rule targets multiple renderers."""
    for rconf in config_with_rules["renderers"].values():
        for light in rconf["lights"]:
            hass.set_state(light, "off")
    hass.set_state("binary_sensor.doorbell", "on")

    from custom_components.signal_lights.manager import Manager

    mgr = Manager(hass, config_with_rules)  # type: ignore[arg-type]
    for rid in ["kitchen", "hallway"]:
        assert "doorbell_ring" in mgr.renderers[rid].signals


async def test_rule_unknown_renderer_warning(hass: FakeHass, caplog):
    """Rule referencing unknown renderer logs warning, doesn't crash."""
    config = {
        "renderers": {
            "kitchen": {"lights": ["light.kitchen"]},
        },
        "signal_rules": [
            {
                "source_entity": "binary_sensor.x",
                "active_state": "on",
                "renderers": ["kitchen", "nonexistent"],
                "signal_id": "test",
            },
        ],
    }
    hass.set_state("light.kitchen", "off")
    hass.set_state("binary_sensor.x", "off")

    from custom_components.signal_lights.manager import Manager

    with caplog.at_level("WARNING"):
        mgr = Manager(hass, config)  # type: ignore[arg-type]

    assert "nonexistent" in caplog.text
    # The valid renderer is still included
    rule = mgr.rules[0]
    assert "kitchen" in rule.renderers
    assert "nonexistent" not in rule.renderers


async def test_to_signal_method():
    """SignalRule.to_signal produces correct Signal."""
    from custom_components.signal_lights.manager import SignalRule

    rule = SignalRule(
        rule_id="r1",
        source_entity="binary_sensor.x",
        active_state="on",
        renderers=["kitchen"],
        signal_id="sig1",
        priority=70,
        color=(100, 200, 50),
        duration=5,
        mode="persistent",
    )
    sig = rule.to_signal()
    assert sig.signal_id == "sig1"
    assert sig.priority == 70
    assert sig.color == (100, 200, 50)
    assert sig.source == "rule:r1"
    assert sig.mode == "persistent"
