from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import asdict

import voluptuous as vol
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .configuration import async_title_labels, entry_configuration, replace_entity, subentry_title
from .const import (
    CONF_KEY,
    CONF_LAMP_PROFILES,
    CONF_LIGHTS,
    CONF_NIGHT_MODE_ENTITY,
    CONF_RENDERERS,
    CONF_SIGNAL_RULES,
    DATA_MANAGER,
    DATA_TITLE_LABELS,
    DEFAULT_COLOR,
    DEFAULT_DURATION,
    DEFAULT_PRIORITY,
    DOMAIN,
    SERVICE_CLEAR_SIGNAL,
    SERVICE_DUMP_STATE,
    SERVICE_PUSH_SIGNAL,
    SERVICE_REFRESH_ON_LIGHTS,
    SERVICE_TEST_SIGNAL,
    TYPE_PROFILE,
)
from .manager import Manager, Signal

_LOGGER = logging.getLogger(__name__)

SIGNAL_RULE_SCHEMA = vol.Schema(
    {
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
    }
)

RENDERER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LIGHTS): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional("baseline"): dict,
        vol.Optional("time_window"): vol.Schema(
            {
                vol.Optional("start"): str,
                vol.Optional("end"): str,
            }
        ),
        vol.Optional("profile"): str,
        vol.Optional(CONF_NIGHT_MODE_ENTITY): cv.entity_id,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_RENDERERS, default={}): {str: RENDERER_SCHEMA},
                vol.Optional(CONF_LAMP_PROFILES, default={}): dict,
                vol.Optional(CONF_SIGNAL_RULES, default=[]): [SIGNAL_RULE_SCHEMA],
            }
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

PUSH_SIGNAL_SCHEMA = vol.Schema(
    {
        vol.Required("renderer_id"): str,
        vol.Required("signal_id"): str,
        vol.Optional("priority", default=DEFAULT_PRIORITY): vol.All(int, vol.Range(min=0, max=100)),
        vol.Optional("color", default=DEFAULT_COLOR): vol.All(list, vol.Length(min=3, max=3)),
        vol.Optional("duration", default=DEFAULT_DURATION): vol.All(int, vol.Range(min=1, max=300)),
        vol.Optional("show_only_on_turn_on", default=True): bool,
        vol.Optional("mode", default="transient"): vol.In(["transient", "persistent"]),
        vol.Optional("activate_when_off", default=False): bool,
    }
)

CLEAR_SIGNAL_SCHEMA = vol.Schema(
    {
        vol.Required("renderer_id"): str,
        vol.Required("signal_id"): str,
    }
)

REFRESH_SCHEMA = vol.Schema(
    {
        vol.Optional("entity_ids", default=[]): vol.All(cv.ensure_list, [cv.entity_id]),
    }
)

TEST_SIGNAL_SCHEMA = vol.Schema(
    {
        vol.Required("renderer_id"): str,
        vol.Optional("color", default=DEFAULT_COLOR): vol.All(list, vol.Length(min=3, max=3)),
        vol.Optional("duration", default=DEFAULT_DURATION): vol.All(int, vol.Range(min=1, max=300)),
        vol.Optional("activate_when_off", default=False): bool,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {})
    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data=deepcopy(config[DOMAIN]),
            )
        )

    def manager() -> Manager:
        current: Manager | None = hass.data[DOMAIN].get(DATA_MANAGER)
        if current is None:
            raise ServiceValidationError("Signal Lights is not loaded")
        return current

    async def handle_push(call: ServiceCall) -> None:
        await manager().push_signal(
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
        await manager().clear_signal(
            call.data["renderer_id"],
            call.data["signal_id"],
        )

    async def handle_refresh(call: ServiceCall) -> None:
        entity_ids = call.data.get("entity_ids", [])
        await manager().refresh_on_lights(entity_ids)

    async def handle_dump_state(call: ServiceCall) -> None:
        manager().dump_state()

    async def handle_test_signal(call: ServiceCall) -> None:
        await manager().test_signal(
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up native UI configuration and the same stable diagnostic entities."""
    data = hass.data.setdefault(DOMAIN, {})
    labels = await async_title_labels(hass)
    data[DATA_TITLE_LABELS] = labels
    # Update legacy titles before registering the reload listener. Only titles
    # change; subentry IDs, unique IDs and all configuration stay intact.
    for item in entry.subentries.values():
        title = subentry_title(item.subentry_type, item.data[CONF_KEY], labels)
        if item.title != title:
            hass.config_entries.async_update_subentry(entry, item, title=title)
    current = Manager(hass, entry_configuration(entry))
    data[DATA_MANAGER] = current
    # Service-created persistent signals survive a config-entry reload. Rules are
    # re-evaluated from their source state by Manager, never copied as stale rules.
    for renderer_id, signals in data.pop("saved_signals", {}).items():
        renderer = current.renderers.get(renderer_id)
        if renderer:
            renderer.signals.update({item["signal_id"]: Signal(**item) for item in signals})
    entry.async_on_unload(entry.add_update_listener(_async_configuration_updated))

    @callback
    def registry_updated(event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        _async_entity_registry_updated(hass, entry, event)

    entry.async_on_unload(hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, registry_updated))
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    return True


async def _async_configuration_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply options/subentry changes by reloading only this integration."""
    await hass.config_entries.async_reload(entry.entry_id)


@callback
def _async_entity_registry_updated(
    hass: HomeAssistant, entry: ConfigEntry, event: Event[er.EventEntityRegistryUpdatedData]
) -> None:
    """Persist entity renames and migrate the live manager before the next light event."""
    event_data = event.data
    if event_data["action"] != "update":
        return
    old = event_data["changes"].get("entity_id")
    new = event_data["entity_id"]
    if not isinstance(old, str) or not old or old == new:
        return
    # Calculate every replacement first: a collision must never leave half a rename.
    updates = []
    for item in entry.subentries.values():
        data = replace_entity(dict(item.data), old, new)
        if data != dict(item.data):
            key = data[CONF_KEY]
            unique_id = f"{TYPE_PROFILE}:{key}" if item.subentry_type == TYPE_PROFILE else item.unique_id
            if any(other is not item and other.unique_id == unique_id for other in entry.subentries.values()):
                _LOGGER.error("Cannot migrate entity %s to %s: profile identifier collision", old, new)
                return
            updates.append((item, data, unique_id))
    options = replace_entity(dict(entry.options), old, new)
    data = replace_entity(dict(entry.data), old, new)
    if not updates and options == dict(entry.options) and data == dict(entry.data):
        return
    current: Manager | None = hass.data[DOMAIN].get(DATA_MANAGER)
    if current:
        current.rename_entity(old, new)
    for item, data, unique_id in updates:
        title = subentry_title(item.subentry_type, data[CONF_KEY], hass.data[DOMAIN][DATA_TITLE_LABELS])
        hass.config_entries.async_update_subentry(entry, item, data=data, unique_id=unique_id, title=title)
    options = replace_entity(dict(entry.options), old, new)
    data = replace_entity(dict(entry.data), old, new)
    if options != dict(entry.options) or data != dict(entry.data):
        hass.config_entries.async_update_entry(entry, options=options, data=data)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove entities/listeners and prevent delayed old renders from writing to lights."""
    if not await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR]):
        return False
    data = hass.data[DOMAIN]
    current: Manager = data.pop(DATA_MANAGER)
    data["saved_signals"] = {
        renderer_id: [
            asdict(signal)
            for signal in renderer.signals.values()
            if signal.mode == "persistent" and not signal.source.startswith("rule:")
        ]
        for renderer_id, renderer in current.renderers.items()
    }
    await current.async_shutdown()
    return True
