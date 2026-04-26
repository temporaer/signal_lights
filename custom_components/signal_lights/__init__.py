from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers.discovery import async_load_platform

from .const import DOMAIN, DATA_MANAGER
from .manager import Manager


async def async_setup(hass: HomeAssistant, config):
    conf = config.get(DOMAIN, {})

    manager = Manager(hass, conf)
    hass.data.setdefault(DOMAIN, {})[DATA_MANAGER] = manager

    hass.async_create_task(
        async_load_platform(hass, "sensor", DOMAIN, {}, config)
    )

    async def push(call):
        await manager.push_signal(
            call.data["renderer_id"],
            call.data["signal_id"],
            call.data.get("priority", 50),
            call.data.get("color", [0, 255, 0]),
            call.data.get("duration", 3),
            call.data.get("show_only_on_turn_on", True),
            call.data.get("mode", "transient"),
            call.data.get("activate_when_off", False),
        )

    async def clear(call):
        await manager.clear_signal(
            call.data["renderer_id"],
            call.data["signal_id"],
        )

    async def async_refresh_on_lights(call):
        entity_ids = call.data.get("entity_ids", [])
        await manager.refresh_on_lights(entity_ids)

    hass.services.async_register(
        DOMAIN,
        "push_signal",
        push,
        schema=vol.Schema({
            vol.Required("renderer_id"): str,
            vol.Required("signal_id"): str,
            vol.Optional("priority"): int,
            vol.Optional("color"): list,
            vol.Optional("duration"): int,
            vol.Optional("show_only_on_turn_on"): bool,
            vol.Optional("mode"): vol.In(["transient", "persistent"]),
            vol.Optional("activate_when_off"): bool,
        }),
    )

    hass.services.async_register(
        DOMAIN,
        "clear_signal",
        clear,
        schema=vol.Schema({
            vol.Required("renderer_id"): str,
            vol.Required("signal_id"): str,
        }),
    )

    hass.services.async_register(
        DOMAIN,
        "refresh_on_lights",
        async_refresh_on_lights,
    )

    return True
