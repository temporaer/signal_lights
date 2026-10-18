"""Validated, serializable configuration shared by UI flows and runtime."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.translation import async_get_translations

from .const import (
    CONF_CONFIG,
    CONF_KEY,
    CONF_LAMP_PROFILES,
    CONF_LIGHTS,
    CONF_NIGHT_MODE_ENTITY,
    CONF_RENDERERS,
    CONF_SIGNAL_RULES,
    DOMAIN,
    SUBENTRY_ICONS,
    SUBENTRY_TYPE_NAMES,
    TYPE_PROFILE,
    TYPE_RENDERER,
    TYPE_RULE,
)

COLOR = vol.All(cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min=0, max=255))], vol.Length(min=3, max=3))
PROFILE_SCHEMA = vol.Schema(
    {
        vol.Optional("profile"): str,
        vol.Optional("brightness_day"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional("brightness_night"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional("kelvin_min"): vol.All(vol.Coerce(int), vol.Range(min=1000, max=12000)),
        vol.Optional("kelvin_max"): vol.All(vol.Coerce(int), vol.Range(min=1000, max=12000)),
        vol.Optional("exponent"): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional("gain"): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional("base"): vol.Coerce(float),
        vol.Optional("divisor"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    }
)
RULE_SCHEMA = vol.Schema(
    {
        vol.Optional("rule_id"): str,
        vol.Optional("enabled", default=True): bool,
        vol.Required("source_entity"): cv.entity_id,
        vol.Optional("active_state", default="on"): str,
        vol.Required("renderers"): vol.All(cv.ensure_list, [str], vol.Length(min=1)),
        vol.Required("signal_id"): str,
        vol.Optional("priority", default=50): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional("color", default=[0, 255, 0]): COLOR,
        vol.Optional("duration", default=3): vol.All(vol.Coerce(int), vol.Range(min=1, max=300)),
        vol.Optional("show_only_on_turn_on", default=True): bool,
        vol.Optional("mode", default="transient"): vol.In(["transient", "persistent"]),
        vol.Optional("activate_when_off", default=False): bool,
    }
)
RENDERER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LIGHTS): vol.All(cv.ensure_list, [cv.entity_id], vol.Length(min=1)),
        vol.Optional("baseline"): vol.Schema(
            {
                vol.Optional("mode"): vol.In(["template", "fixed"]),
                vol.Optional("brightness_pct"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                vol.Optional("color_temp_kelvin"): vol.All(vol.Coerce(int), vol.Range(min=1000, max=12000)),
            }
        ),
        vol.Optional("time_window"): vol.Schema({vol.Optional("start"): cv.time, vol.Optional("end"): cv.time}),
        vol.Optional("profile"): str,
        vol.Optional(CONF_NIGHT_MODE_ENTITY): cv.entity_id,
    }
)


def validate_item(kind: str, value: dict[str, Any]) -> dict[str, Any]:
    """Validate a single item without inserting unrelated defaults."""
    schema = {TYPE_RENDERER: RENDERER_SCHEMA, TYPE_RULE: RULE_SCHEMA, TYPE_PROFILE: PROFILE_SCHEMA}[kind]
    result: dict[str, Any] = schema(deepcopy(value))
    if "time_window" in result:
        result["time_window"] = {key: val.isoformat() for key, val in result["time_window"].items()}
    if result.get("kelvin_min", 0) > result.get("kelvin_max", 12000):
        raise vol.Invalid("kelvin_min must not exceed kelvin_max")
    return result


def import_subentries(config: dict[str, Any]) -> list[ConfigSubentryData]:
    """Convert YAML into native subentries, retaining identifiers and sensor unique IDs."""
    entries = []
    for kind, values in (
        (TYPE_PROFILE, config.get(CONF_LAMP_PROFILES, {})),
        (TYPE_RENDERER, config.get(CONF_RENDERERS, {})),
    ):
        for key, value in values.items():
            if key == CONF_NIGHT_MODE_ENTITY:
                continue
            entries.append(_subentry(kind, key, validate_item(kind, value)))
    for index, rule in enumerate(config.get(CONF_SIGNAL_RULES, []), 1):
        key = rule.get("rule_id", f"rule_{index}")
        entries.append(_subentry(TYPE_RULE, key, validate_item(TYPE_RULE, {**rule, "rule_id": key})))
    unique_ids = [item["unique_id"] for item in entries]
    if len(set(unique_ids)) != len(unique_ids):
        raise vol.Invalid("duplicate item identifiers")
    return entries


async def async_title_labels(hass: HomeAssistant) -> dict[str, str]:
    """Resolve type labels using HA's configured language and integration translations."""
    translations = await async_get_translations(hass, hass.config.language, "config_subentries", {DOMAIN})
    return {
        kind: translations.get(f"component.{DOMAIN}.config_subentries.{kind}.entry_type", fallback)
        for kind, fallback in SUBENTRY_TYPE_NAMES.items()
    }


def subentry_title(kind: str, key: str, labels: dict[str, str] | None = None) -> str:
    """Make entry types visible without changing identifiers or entity references."""
    label = (labels or SUBENTRY_TYPE_NAMES)[kind]
    return f"{SUBENTRY_ICONS[kind]} {label} · {key}"


def _subentry(kind: str, key: str, config: dict[str, Any]) -> ConfigSubentryData:
    return {
        "subentry_type": kind,
        "title": subentry_title(kind, key),
        "unique_id": f"{kind}:{key}",
        "data": {CONF_KEY: key, CONF_CONFIG: config},
    }


def entry_configuration(entry: Any) -> dict[str, Any]:
    """Build the Manager configuration from native config subentries."""
    result: dict[str, Any] = {CONF_RENDERERS: {}, CONF_LAMP_PROFILES: {}, CONF_SIGNAL_RULES: []}
    night_mode = entry.options.get(CONF_NIGHT_MODE_ENTITY) or entry.data.get(CONF_NIGHT_MODE_ENTITY)
    if night_mode:
        result[CONF_LAMP_PROFILES][CONF_NIGHT_MODE_ENTITY] = night_mode
    for item in entry.subentries.values():
        key = item.data[CONF_KEY]
        config = deepcopy(dict(item.data[CONF_CONFIG]))
        if item.subentry_type == TYPE_RENDERER:
            result[CONF_RENDERERS][key] = config
        elif item.subentry_type == TYPE_PROFILE:
            result[CONF_LAMP_PROFILES][key] = config
        elif item.subentry_type == TYPE_RULE and config.pop("enabled", True):
            result[CONF_SIGNAL_RULES].append({**config, "rule_id": key})
    return result


def replace_entity(value: Any, old: str, new: str) -> Any:
    """Replace actual entity references, including per-light profile keys, without substring edits."""
    if isinstance(value, str):
        return new if value == old else value
    if isinstance(value, list):
        return [replace_entity(item, old, new) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            renamed = new if key == old else key
            if renamed in result:
                raise ValueError(f"Entity rename collides with {renamed}")
            result[renamed] = replace_entity(item, old, new)
        return result
    return value
