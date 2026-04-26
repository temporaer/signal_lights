"""Tests for time window, baseline computation, and timezone handling."""

from __future__ import annotations

from datetime import UTC, datetime, time
from unittest.mock import patch

from custom_components.signal_lights.manager import Renderer, _clamp

from .conftest import FakeHass


def test_clamp():
    assert _clamp(5, 0, 10) == 5
    assert _clamp(-1, 0, 10) == 0
    assert _clamp(15, 0, 10) == 10
    assert _clamp(0, 0, 10) == 0


def test_parse_time():
    assert Renderer._parse_time("08:30") == time(8, 30, 0)
    assert Renderer._parse_time("23:59:59") == time(23, 59, 59)
    assert Renderer._parse_time("") is None
    assert Renderer._parse_time(None) is None
    assert Renderer._parse_time("not_a_time") is None


async def test_time_window_no_config(hass: FakeHass, manager):
    """No time_window config means always in window."""
    renderer = manager.renderers["kitchen"]
    assert renderer.in_time_window() is True


async def test_time_window_within(hass: FakeHass):
    """Test time within normal window (start < end)."""
    config = {
        "lights": ["light.test"],
        "time_window": {"start": "06:00", "end": "22:00"},
    }
    hass.set_state("light.test", "off")
    renderer = Renderer(hass, "test", config, {})  # type: ignore[arg-type]

    fake_now = datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC)
    with patch("custom_components.signal_lights.manager.dt_util") as mock_dt:
        mock_dt.now.return_value = fake_now
        assert renderer.in_time_window() is True


async def test_time_window_outside(hass: FakeHass):
    """Test time outside normal window."""
    config = {
        "lights": ["light.test"],
        "time_window": {"start": "06:00", "end": "22:00"},
    }
    hass.set_state("light.test", "off")
    renderer = Renderer(hass, "test", config, {})  # type: ignore[arg-type]

    fake_now = datetime(2026, 4, 26, 23, 30, 0, tzinfo=UTC)
    with patch("custom_components.signal_lights.manager.dt_util") as mock_dt:
        mock_dt.now.return_value = fake_now
        assert renderer.in_time_window() is False


async def test_time_window_overnight(hass: FakeHass):
    """Test overnight window (start > end, e.g. 22:00-06:00)."""
    config = {
        "lights": ["light.test"],
        "time_window": {"start": "22:00", "end": "06:00"},
    }
    hass.set_state("light.test", "off")
    renderer = Renderer(hass, "test", config, {})  # type: ignore[arg-type]

    # 23:00 should be in window
    with patch("custom_components.signal_lights.manager.dt_util") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 4, 26, 23, 0, 0, tzinfo=UTC)
        assert renderer.in_time_window() is True

    # 03:00 should be in window
    with patch("custom_components.signal_lights.manager.dt_util") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 4, 27, 3, 0, 0, tzinfo=UTC)
        assert renderer.in_time_window() is True

    # 12:00 should be outside window
    with patch("custom_components.signal_lights.manager.dt_util") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)
        assert renderer.in_time_window() is False


async def test_baseline_default(hass: FakeHass, manager):
    """Default baseline when no mode configured."""
    renderer = manager.renderers["kitchen"]
    baseline = renderer.get_baseline_for_light("light.kitchen_ceiling")
    assert baseline == {"brightness_pct": 100, "color_temp_kelvin": 3200}


async def test_baseline_fixed(hass: FakeHass):
    """Fixed baseline returns configured values."""
    config = {
        "lights": ["light.test"],
        "baseline": {"mode": "fixed", "brightness_pct": 80, "color_temp_kelvin": 2700},
    }
    hass.set_state("light.test", "off")
    renderer = Renderer(hass, "test", config, {})  # type: ignore[arg-type]
    baseline = renderer.get_baseline_for_light("light.test")
    assert baseline == {"brightness_pct": 80, "color_temp_kelvin": 2700}


async def test_baseline_template_night_mode(hass: FakeHass):
    """Template baseline uses configurable night_mode_entity."""
    custom_entity = "input_boolean.my_night_mode"
    config = {
        "lights": ["light.test"],
        "baseline": {"mode": "template"},
        "night_mode_entity": custom_entity,
    }
    hass.set_state("light.test", "off")
    hass.set_state("sun.sun", "above_horizon", {"elevation": 30})
    hass.set_state(custom_entity, "on")

    renderer = Renderer(hass, "test", config, {})  # type: ignore[arg-type]
    baseline = renderer.get_baseline_for_light("light.test")
    # Night mode on → should use brightness_night (default 40)
    assert baseline["brightness_pct"] == 40


async def test_baseline_template_day_mode(hass: FakeHass):
    """Template baseline in day mode."""
    config = {
        "lights": ["light.test"],
        "baseline": {"mode": "template"},
    }
    hass.set_state("light.test", "off")
    hass.set_state("sun.sun", "above_horizon", {"elevation": 30})
    hass.set_state("input_boolean.night_mode", "off")

    renderer = Renderer(hass, "test", config, {})  # type: ignore[arg-type]
    baseline = renderer.get_baseline_for_light("light.test")
    assert baseline["brightness_pct"] == 100
    assert 2203 <= baseline["color_temp_kelvin"] <= 4000
