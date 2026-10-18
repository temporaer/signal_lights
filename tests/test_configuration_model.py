"""Configuration migration and validation independent of Home Assistant startup."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
import voluptuous as vol

from custom_components.signal_lights.configuration import (
    import_subentries,
    replace_entity,
    validate_item,
)
from custom_components.signal_lights.const import TYPE_PROFILE, TYPE_RENDERER


def test_import_preserves_named_and_per_light_profiles():
    config: dict[str, Any] = {
        "lamp_profiles": {
            "night_mode_entity": "input_boolean.night",
            "soft": {"brightness_day": 70},
            "light.desk": {"profile": "soft", "brightness_night": 12},
        },
        "renderers": {
            "desk": {"lights": ["light.desk"], "profile": "soft", "time_window": {"start": "22:00", "end": "06:00"}}
        },
        "signal_rules": [{"source_entity": "binary_sensor.mail", "renderers": ["desk"], "signal_id": "mail"}],
    }
    result = import_subentries(config)
    assert len(result) == 4
    assert result[-1]["data"]["key"] == "rule_1"
    assert result[1]["data"]["config"]["brightness_night"] == 12
    assert config["renderers"]["desk"]["time_window"]["start"] == "22:00"
    assert result[2]["data"]["config"]["time_window"]["start"] == "22:00:00"


def test_duplicate_import_rule_identifiers_are_rejected():
    rule = {"rule_id": "mail", "source_entity": "binary_sensor.mail", "renderers": ["room"], "signal_id": "mail"}
    with pytest.raises(vol.Invalid):
        import_subentries({"signal_rules": [rule, rule]})


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        (TYPE_PROFILE, {"kelvin_min": 4000, "kelvin_max": 2000}),
        (TYPE_PROFILE, {"brightness_day": 101}),
        (TYPE_RENDERER, {"lights": []}),
        (TYPE_RENDERER, {"lights": ["light.desk"], "time_window": {"start": "99:00"}}),
    ],
)
def test_invalid_settings_are_rejected(kind, value):
    with pytest.raises(vol.Invalid):
        validate_item(kind, value)


def test_entity_replacement_is_exact_and_rejects_collisions():
    value = {"light.old": {"lights": ["light.old", "light.old_backup"], "source_entity": "light.old"}}
    result = replace_entity(value, "light.old", "light.new")
    assert result["light.new"]["lights"] == ["light.new", "light.old_backup"]
    assert result["light.new"]["source_entity"] == "light.new"
    assert "light.old" in value
    with pytest.raises(ValueError):
        replace_entity({"light.old": {}, "light.new": {}}, "light.old", "light.new")


async def test_shutdown_restores_woken_lights_and_old_transient_cannot_write(manager, hass):
    sleeping = asyncio.Event()
    resume = asyncio.Event()

    async def sleep(_seconds):
        sleeping.set()
        await resume.wait()

    with patch("custom_components.signal_lights.manager.asyncio.sleep", side_effect=sleep):
        task = asyncio.create_task(
            manager.push_signal("kitchen", "flash", 50, [255, 0, 0], 3, False, "transient", True)
        )
        await sleeping.wait()
        await manager.async_shutdown()
        assert all(renderer._closed for renderer in manager.renderers.values())
        calls = hass.services.async_call.call_args_list
        assert any(call.args[1] == "turn_off" for call in calls)
        count = len(calls)
        resume.set()
        await task
        assert hass.services.async_call.call_count == count


async def test_entity_rename_during_transient_updates_routing_without_stale_restore(manager, hass):
    sleeping = asyncio.Event()
    resume = asyncio.Event()

    async def sleep(_seconds):
        sleeping.set()
        await resume.wait()

    with patch("custom_components.signal_lights.manager.asyncio.sleep", side_effect=sleep):
        task = asyncio.create_task(
            manager.push_signal("kitchen", "flash", 50, [255, 0, 0], 3, False, "transient", True)
        )
        await sleeping.wait()
        manager.rename_entity("light.kitchen_ceiling", "light.new")
        before = hass.services.async_call.call_count
        resume.set()
        await task
        calls = hass.services.async_call.call_args_list[before:]
        assert all(call.args[2].get("entity_id") != "light.kitchen_ceiling" for call in calls)
        assert "light.new" in manager.light_to_renderers
