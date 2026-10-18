"""Home Assistant configuration flows; also usable through standard MCP config-flow tools."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .configuration import entry_configuration, import_subentries, validate_item
from .const import (
    CONF_CONFIG,
    CONF_KEY,
    CONF_LAMP_PROFILES,
    CONF_NIGHT_MODE_ENTITY,
    DEFAULT_NIGHT_MODE_ENTITY,
    DOMAIN,
    SINGLETON_ID,
    TYPE_PROFILE,
    TYPE_RENDERER,
    TYPE_RULE,
)


def _number(low: float, high: float, step: float = 1) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(min=low, max=high, step=step, mode=selector.NumberSelectorMode.BOX)
    )


class SignalLightsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create one integration, optionally importing the existing YAML configuration."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(SINGLETON_ID)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="Signal Lights", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_NIGHT_MODE_ENTITY, default=DEFAULT_NIGHT_MODE_ENTITY): selector.EntitySelector(),
                }
            ),
        )

    async def async_step_import(self, user_input: dict[str, Any]) -> ConfigFlowResult:
        await self.async_set_unique_id(SINGLETON_ID)
        self._abort_if_unique_id_configured()
        try:
            subentries = import_subentries(user_input)
        except (vol.Invalid, ValueError, TypeError):
            return self.async_abort(reason="invalid_yaml")
        night_mode = user_input.get(CONF_LAMP_PROFILES, {}).get(CONF_NIGHT_MODE_ENTITY, DEFAULT_NIGHT_MODE_ENTITY)
        return self.async_create_entry(
            title="Signal Lights", data={CONF_NIGHT_MODE_ENTITY: night_mode}, subentries=subentries
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SignalLightsOptionsFlow:
        return SignalLightsOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {TYPE_RENDERER: RendererFlow, TYPE_PROFILE: ProfileFlow, TYPE_RULE: RuleFlow}


class SignalLightsOptionsFlow(OptionsFlow):
    """Global settings; individual groups, profiles and rules have their own forms."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Optional(CONF_NIGHT_MODE_ENTITY): selector.EntitySelector(),
                    }
                ),
                {
                    CONF_NIGHT_MODE_ENTITY: self.config_entry.options.get(
                        CONF_NIGHT_MODE_ENTITY,
                        self.config_entry.data.get(CONF_NIGHT_MODE_ENTITY, DEFAULT_NIGHT_MODE_ENTITY),
                    )
                },
            ),
        )


class ItemFlow(ConfigSubentryFlow):
    """Shared create/reconfigure logic with stable, immutable item identifiers."""

    kind: str

    def _schema(self, current: dict[str, Any], *, editing: bool) -> vol.Schema:
        fields: dict[Any, Any] = {}
        if not editing:
            fields[vol.Required(CONF_KEY)] = selector.TextSelector()
        fields.update(self._fields())
        # Reconfiguration is a patch: omitted fields retain their persisted values,
        # rather than accidentally taking a create-form default (e.g. transient).
        if editing:
            for marker in fields:
                if isinstance(marker, (vol.Optional, vol.Required)) and marker.schema in current:
                    marker.default = vol.default_factory(current[marker.schema])
        return self.add_suggested_values_to_schema(vol.Schema(fields), current)

    def _fields(self) -> dict[Any, Any]:
        raise NotImplementedError

    def _decode(self, values: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
        return {**previous, **values}

    def _encode(self, config: dict[str, Any]) -> dict[str, Any]:
        return config

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return self._step(user_input, editing=False)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return self._step(user_input, editing=True)

    @callback
    def _step(self, user_input: dict[str, Any] | None, *, editing: bool) -> SubentryFlowResult:
        entry = self._get_entry()
        existing = self._get_reconfigure_subentry() if editing else None
        old = deepcopy(dict(existing.data[CONF_CONFIG])) if existing else {}
        key = str(existing.data[CONF_KEY]) if existing else ""
        step = "reconfigure" if editing else "user"
        errors = {}
        if user_input is not None:
            values = dict(user_input)
            key = key if editing else str(values.pop(CONF_KEY, "")).strip()
            if not key or (self.kind != TYPE_PROFILE and not key.replace("_", "").isalnum()):
                errors["base"] = "invalid_key"
            elif any(
                item.unique_id == f"{self.kind}:{key}" and item is not existing for item in entry.subentries.values()
            ):
                errors["base"] = "already_configured"
            else:
                try:
                    data = validate_item(self.kind, self._decode(values, old))
                    self._validate_references(data, entry)
                except (vol.Invalid, ValueError, TypeError):
                    errors["base"] = "invalid_config"
                else:
                    payload = {CONF_KEY: key, CONF_CONFIG: data}
                    if existing:
                        return self.async_update_and_abort(entry, existing, data=payload)
                    return self.async_create_entry(title=key, unique_id=f"{self.kind}:{key}", data=payload)
        defaults = self._encode(old)
        if user_input:
            defaults.update(user_input)
        return self.async_show_form(step_id=step, data_schema=self._schema(defaults, editing=editing), errors=errors)

    def _validate_references(self, data: dict[str, Any], entry: ConfigEntry) -> None:
        config = entry_configuration(entry)
        if self.kind == TYPE_RULE and any(key not in config["renderers"] for key in data["renderers"]):
            raise vol.Invalid("unknown renderer")
        if data.get("profile") and data["profile"] not in config[CONF_LAMP_PROFILES]:
            raise vol.Invalid("unknown profile")


class RendererFlow(ItemFlow):
    """Lights, baseline, profile, time window and night-mode source."""

    kind = TYPE_RENDERER

    def _fields(self) -> dict[Any, Any]:
        return {
            vol.Required("lights"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="light", multiple=True)
            ),
            vol.Optional("baseline_mode", default="template"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=["template", "fixed"])
            ),
            vol.Optional("brightness_pct"): _number(0, 100),
            vol.Optional("color_temp_kelvin"): _number(1000, 12000),
            vol.Optional("profile"): selector.TextSelector(),
            vol.Optional("start"): selector.TimeSelector(),
            vol.Optional("end"): selector.TimeSelector(),
            vol.Optional(CONF_NIGHT_MODE_ENTITY): selector.EntitySelector(),
        }

    def _encode(self, config: dict[str, Any]) -> dict[str, Any]:
        result = {key: value for key, value in config.items() if key not in ["baseline", "time_window"]}
        baseline = config.get("baseline", {})
        result.update({key: value for key, value in baseline.items() if key != "mode"})
        result["baseline_mode"] = baseline.get("mode", "fixed")
        result.update(config.get("time_window", {}))
        return result

    def _decode(self, values: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
        result = {**previous, **values}
        result["baseline"] = {**previous.get("baseline", {}), "mode": result.pop("baseline_mode", "template")}
        for key in ("brightness_pct", "color_temp_kelvin"):
            if key in result:
                result["baseline"][key] = result.pop(key)
        window = dict(previous.get("time_window", {}))
        for key in ("start", "end"):
            if key in result:
                value = result.pop(key)
                if value:
                    window[key] = value
                else:
                    window.pop(key, None)
        if bool(window.get("start")) != bool(window.get("end")):
            raise vol.Invalid("both time-window endpoints are required")
        result["time_window"] = window
        if not result.get("profile"):
            result.pop("profile", None)
        return result


class ProfileFlow(ItemFlow):
    """Reusable or per-entity sun and brightness profiles."""

    kind = TYPE_PROFILE

    def _fields(self) -> dict[Any, Any]:
        return {
            vol.Optional("profile"): selector.TextSelector(),
            vol.Optional("brightness_day"): _number(0, 100),
            vol.Optional("brightness_night"): _number(0, 100),
            vol.Optional("kelvin_min"): _number(1000, 12000),
            vol.Optional("kelvin_max"): _number(1000, 12000),
            vol.Optional("exponent"): _number(0, 10, 0.01),
            vol.Optional("gain"): _number(0, 100, 0.001),
            vol.Optional("base"): _number(-100000, 100000, 0.01),
            vol.Optional("divisor"): _number(0, 100000, 0.01),
        }

    def _decode(self, values: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
        result = super()._decode(values, previous)
        if not result.get("profile"):
            result.pop("profile", None)
        return result


class RuleFlow(ItemFlow):
    """Configure state-driven signal rules without YAML."""

    kind = TYPE_RULE

    def _fields(self) -> dict[Any, Any]:
        renderers = list(entry_configuration(self._get_entry())["renderers"])
        return {
            vol.Optional("enabled", default=True): selector.BooleanSelector(),
            vol.Required("source_entity"): selector.EntitySelector(),
            vol.Required("active_state", default="on"): selector.TextSelector(),
            vol.Required("renderers"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=renderers, multiple=True)
            ),
            vol.Required("signal_id"): selector.TextSelector(),
            vol.Optional("color", default=[0, 255, 0]): selector.ColorRGBSelector(),
            vol.Optional("priority", default=50): _number(0, 100),
            vol.Optional("duration", default=3): _number(1, 300),
            vol.Optional("mode", default="transient"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=["transient", "persistent"])
            ),
            vol.Optional("show_only_on_turn_on", default=True): selector.BooleanSelector(),
            vol.Optional("activate_when_off", default=False): selector.BooleanSelector(),
        }
