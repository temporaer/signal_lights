from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_LAMP_PROFILES,
    CONF_LIGHTS,
    CONF_NIGHT_MODE_ENTITY,
    CONF_RENDERERS,
    CONF_SIGNAL_RULES,
    DATA_MANAGER,
    DEFAULT_COLOR,
    DEFAULT_DURATION,
    DEFAULT_PRIORITY,
    DOMAIN,
    SERVICE_CLEAR_SIGNAL,
    SERVICE_DUMP_STATE,
    SERVICE_PUSH_SIGNAL,
    SERVICE_REFRESH_ON_LIGHTS,
    SERVICE_TEST_SIGNAL,
)
from .manager import Manager

_LOGGER = logging.getLogger(__name__)

SIGNAL_RULE_SCHEMA = vol.Schema({
    vol.Optional("rule_id"): str,
    vol.Required("source_entity"): cv.entity_id,
    vol.Optional("active_state", default="on"): str,
    vol.Required("renderers"): vol.All(cv.ensure_list, [str]),
    vol.Required("signal_id"): str,
    vol.Optional("priority", default=DEFAULT_PRIORITY): vol.All(int, vol.Range(min=0, max=100)),
    vol.Optional("color", default=DEFAULT_COLOR): vol.All(list, vol.Length(min=3, max=3)),
    vol.Optional("duration", default=DEFAULT_DURATION): vol.All(int, vol.Range(min=1, max=300)),
    vol.Optional("show_only_on_turn_on", default=True): bool,
    vol.Optional("mode", default="transient"): vol.In(["transient", "persistent"]),
    vol.Optional("activate_when_off", default=False): bool,
})

RENDERER_SCHEMA = vol.Schema({
    vol.Required(CONF_LIGHTS): vol.All(cv.ensure_list, [cv.entity_id]),
    vol.Optional("baseline"): dict,
    vol.Optional("time_window"): vol.Schema({
        vol.Optional("start"): str,
        vol.Optional("end"): str,
    }),
    vol.Optional("profile"): str,
    vol.Optional(CONF_NIGHT_MODE_ENTITY): cv.entity_id,
})

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema({
            vol.Optional(CONF_RENDERERS, default={}): {str: RENDERER_SCHEMA},
            vol.Optional(CONF_LAMP_PROFILES, default={}): dict,
            vol.Optional(CONF_SIGNAL_RULES, default=[]): [SIGNAL_RULE_SCHEMA],
        }),
    },
    extra=vol.ALLOW_EXTRA,
)

PUSH_SIGNAL_SCHEMA = vol.Schema({
    vol.Required("renderer_id"): str,
    vol.Required("signal_id"): str,
    vol.Optional("priority", default=DEFAULT_PRIORITY): vol.All(int, vol.Range(min=0, max=100)),
    vol.Optional("color", default=DEFAULT_COLOR): vol.All(list, vol.Length(min=3, max=3)),
    vol.Optional("duration", default=DEFAULT_DURATION): vol.All(int, vol.Range(min=1, max=300)),
    vol.Optional("show_only_on_turn_on", default=True): bool,
    vol.Optional("mode", default="transient"): vol.In(["transient", "persistent"]),
    vol.Optional("activate_when_off", default=False): bool,
})

CLEAR_SIGNAL_SCHEMA = vol.Schema({
    vol.Required("renderer_id"): str,
    vol.Required("signal_id"): str,
})

REFRESH_SCHEMA = vol.Schema({
    vol.Optional("entity_ids", default=[]): vol.All(cv.ensure_list, [cv.entity_id]),
})

TEST_SIGNAL_SCHEMA = vol.Schema({
    vol.Required("renderer_id"): str,
    vol.Optional("color", default=DEFAULT_COLOR): vol.All(list, vol.Length(min=3, max=3)),
    vol.Optional("duration", default=DEFAULT_DURATION): vol.All(int, vol.Range(min=1, max=300)),
    vol.Optional("activate_when_off", default=False): bool,
})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    conf = config.get(DOMAIN, {})

    manager = Manager(hass, conf)
    hass.data.setdefault(DOMAIN, {})[DATA_MANAGER] = manager

    hass.async_create_task(
        async_load_platform(hass, "sensor", DOMAIN, {}, config)
    )

    async def handle_push(call: ServiceCall) -> None:
        await manager.push_signal(
            call.data["renderer_id"],
            call.data["signal_id"],
            call.data.get("priority", DEFAULT_PRIORITY),
            call.data.get("color", DEFAULT_COLOR),
            call.data.get("duration", DEFAULT_DURATION),
            call.data.get("show_only_on_turn_on", True),
            call.data.get("mode", "transient"),
            call.data.get("activate_when_off", False),
        )

    async def handle_clear(call: ServiceCall) -> None:
        await manager.clear_signal(
            call.data["renderer_id"],
            call.data["signal_id"],
        )

    async def handle_refresh(call: ServiceCall) -> None:
        entity_ids = call.data.get("entity_ids", [])
        await manager.refresh_on_lights(entity_ids)

    async def handle_dump_state(call: ServiceCall) -> None:
        manager.dump_state()

    async def handle_test_signal(call: ServiceCall) -> None:
        await manager.test_signal(
            call.data["renderer_id"],
            call.data.get("color", DEFAULT_COLOR),
            call.data.get("duration", DEFAULT_DURATION),
            call.data.get("activate_when_off", False),
        )

    hass.services.async_register(DOMAIN, SERVICE_PUSH_SIGNAL, handle_push, schema=PUSH_SIGNAL_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CLEAR_SIGNAL, handle_clear, schema=CLEAR_SIGNAL_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REFRESH_ON_LIGHTS, handle_refresh, schema=REFRESH_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_DUMP_STATE, handle_dump_state)
    hass.services.async_register(DOMAIN, SERVICE_TEST_SIGNAL, handle_test_signal, schema=TEST_SIGNAL_SCHEMA)

    _LOGGER.info("Signal Lights setup complete")
    return True


async def async_unload(hass: HomeAssistant) -> bool:
    """Clean up on integration unload."""
    if DOMAIN not in hass.data:
        return True

    manager: Manager = hass.data[DOMAIN].get(DATA_MANAGER)
    if manager:
        manager.teardown()

    for service_name in (
        SERVICE_PUSH_SIGNAL, SERVICE_CLEAR_SIGNAL, SERVICE_REFRESH_ON_LIGHTS,
        SERVICE_DUMP_STATE, SERVICE_TEST_SIGNAL,
    ):
        hass.services.async_remove(DOMAIN, service_name)

    hass.data.pop(DOMAIN, None)
    _LOGGER.info("Signal Lights unloaded")
    return True
