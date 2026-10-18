"""Exercise the same native flows used by HA's UI and MCP clients."""

from copy import deepcopy

import pytest
from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_RECONFIGURE, SOURCE_USER, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.signal_lights.configuration import entry_configuration
from custom_components.signal_lights.const import DATA_MANAGER, DOMAIN

YAML = {
    "renderers": {"living": {"lights": ["light.old"], "baseline": {"mode": "template"}, "profile": "warm"}},
    "lamp_profiles": {"warm": {"brightness_day": 75}, "light.old": {"brightness_night": 20}},
    "signal_rules": [
        {
            "rule_id": "mail",
            "source_entity": "input_boolean.mail",
            "renderers": ["living"],
            "signal_id": "mail",
            "mode": "persistent",
        }
    ],
}


async def setup_yaml(hass: HomeAssistant) -> ConfigEntry:
    hass.states.async_set("light.old", "off")
    hass.states.async_set("input_boolean.mail", "off")
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: deepcopy(YAML)})
    await hass.async_block_till_done()
    return hass.config_entries.async_entries(DOMAIN)[0]


async def test_yaml_import_and_restart_do_not_overwrite_ui(hass):
    entry = await setup_yaml(hass)
    assert len(entry.subentries) == 4
    assert entry_configuration(entry)["renderers"] == YAML["renderers"]
    renderer = next(item for item in entry.subentries.values() if item.subentry_type == "renderer")
    changed = {**renderer.data, "config": {"lights": ["light.new"]}}
    hass.config_entries.async_update_subentry(entry, renderer, data=changed)
    await hass.async_block_till_done()
    assert hass.data[DOMAIN][DATA_MANAGER].renderers["living"].lights == ["light.new"]
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_IMPORT}, data=YAML)
    assert result["type"] == FlowResultType.ABORT
    assert entry_configuration(entry)["renderers"]["living"]["lights"] == ["light.new"]


async def test_user_setup_and_native_subentry_create_edit_delete(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    entry = result["result"]
    await hass.async_block_till_done()
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "renderer"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"key": "desk", "lights": ["light.desk"], "baseline_mode": "fixed", "brightness_pct": 40}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    item = next(iter(entry.subentries.values()))
    assert item.title == "💡 Lamp group · desk"
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "renderer"), context={"source": SOURCE_RECONFIGURE, "subentry_id": item.subentry_id}
    )
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"lights": ["light.other"], "baseline_mode": "fixed", "brightness_pct": 60}
    )
    assert result["type"] == FlowResultType.ABORT
    await hass.async_block_till_done()
    assert hass.data[DOMAIN][DATA_MANAGER].renderers["desk"].lights == ["light.other"]
    assert item.title == "💡 Lamp group · desk"
    assert item.unique_id == "renderer:desk"
    hass.config_entries.async_remove_subentry(entry, item.subentry_id)
    await hass.async_block_till_done()
    assert not hass.data[DOMAIN][DATA_MANAGER].renderers


async def test_registry_rename_persists_lights_and_per_light_profiles(hass):
    registry = er.async_get(hass)
    entity = registry.async_get_or_create("light", "test", "lamp", suggested_object_id="old")
    entry = await setup_yaml(hass)
    registry.async_update_entity(entity.entity_id, new_entity_id="light.new")
    await hass.async_block_till_done()
    config = entry_configuration(entry)
    assert config["renderers"]["living"]["lights"] == ["light.new"]
    assert "light.new" in config["lamp_profiles"]
    assert "light.old" not in config["lamp_profiles"]
    profile = next(item for item in entry.subentries.values() if item.unique_id == "profile:light.new")
    assert profile.title == "🎨 Light profile · light.new"
    assert hass.data[DOMAIN][DATA_MANAGER].renderers["living"].lights == ["light.new"]
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry_configuration(entry) == config


async def test_invalid_rule_cannot_be_saved(hass):
    entry = await setup_yaml(hass)
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "rule"), context={"source": SOURCE_USER})
    with pytest.raises(InvalidData):
        await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {
                "key": "bad",
                "source_entity": "input_boolean.mail",
                "renderers": ["missing"],
                "active_state": "on",
                "signal_id": "bad",
                "color": [999, 0, 0],
            },
        )
    assert len(entry.subentries) == 4


async def test_sensor_unique_ids_survive_reload_and_persistent_service_signals(hass):
    entry = await setup_yaml(hass)
    registry = er.async_get(hass)
    sensor_id = registry.async_get_entity_id("sensor", DOMAIN, "signal_lights_living")
    assert sensor_id
    await hass.services.async_call(
        DOMAIN, "push_signal", {"renderer_id": "living", "signal_id": "manual", "mode": "persistent"}, blocking=True
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get_entity_id("sensor", DOMAIN, "signal_lights_living") == sensor_id
    assert "manual" in hass.data[DOMAIN][DATA_MANAGER].renderers["living"].signals
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert DATA_MANAGER not in hass.data[DOMAIN]


async def test_yaml_upgrade_reuses_existing_diagnostic_entity(hass):
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "sensor", DOMAIN, "signal_lights_living", suggested_object_id="my_existing_signal"
    )
    entry = await setup_yaml(hass)
    assert registry.async_get_entity_id("sensor", DOMAIN, "signal_lights_living") == old.entity_id
    migrated = registry.async_get(old.entity_id)
    assert migrated is not None
    assert migrated.config_entry_id == entry.entry_id


async def test_profile_rule_and_global_options_flows(hass):
    entry = await setup_yaml(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "profile"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"key": "evening", "brightness_day": 55, "brightness_night": 15, "kelvin_min": 2200, "kelvin_max": 3500},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "rule"), context={"source": SOURCE_USER})
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "key": "door",
            "source_entity": "binary_sensor.door",
            "active_state": "on",
            "renderers": ["living"],
            "signal_id": "door",
            "color": [255, 128, 0],
            "priority": 80,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    rule = next(item for item in entry.subentries.values() if item.unique_id == "rule:door")
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "rule"), context={"source": SOURCE_RECONFIGURE, "subentry_id": rule.subentry_id}
    )
    values = {**rule.data["config"], "enabled": False}
    values.pop("rule_id", None)
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], values)
    assert result["type"] == FlowResultType.ABORT
    await hass.async_block_till_done()
    assert all(rule.rule_id != "door" for rule in hass.data[DOMAIN][DATA_MANAGER].rules)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"night_mode_entity": "input_boolean.sleep"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.data[DOMAIN][DATA_MANAGER].renderers["living"].night_mode_entity == "input_boolean.sleep"


async def test_registry_rename_updates_rule_and_global_night_sources(hass):
    registry = er.async_get(hass)
    source = registry.async_get_or_create("input_boolean", "test", "mail", suggested_object_id="mail")
    night = registry.async_get_or_create("input_boolean", "test", "night", suggested_object_id="night_mode")
    entry = await setup_yaml(hass)
    registry.async_update_entity(source.entity_id, new_entity_id="input_boolean.post")
    registry.async_update_entity(night.entity_id, new_entity_id="input_boolean.sleep")
    await hass.async_block_till_done()
    config = entry_configuration(entry)
    assert config["signal_rules"][0]["source_entity"] == "input_boolean.post"
    assert config["lamp_profiles"]["night_mode_entity"] == "input_boolean.sleep"


async def test_partial_rule_edit_preserves_persistent_mode_and_color(hass):
    entry = await setup_yaml(hass)
    rule = next(item for item in entry.subentries.values() if item.unique_id == "rule:mail")
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "rule"), context={"source": SOURCE_RECONFIGURE, "subentry_id": rule.subentry_id}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"enabled": False}
    )
    assert result["type"] == FlowResultType.ABORT
    await hass.async_block_till_done()
    assert rule.data["config"]["mode"] == "persistent"
    assert rule.data["config"]["source_entity"] == "input_boolean.mail"
    assert rule.data["config"]["renderers"] == ["living"]
    assert rule.data["config"]["enabled"] is False


@pytest.mark.parametrize(
    ("language", "prefixes"),
    [
        ("en", {"renderer": "💡 Lamp group", "profile": "🎨 Light profile", "rule": "🔔 Signal rule"}),
        ("de", {"renderer": "💡 Lampengruppe", "profile": "🎨 Lichtprofil", "rule": "🔔 Signalregel"}),
    ],
)
async def test_typed_titles_localize_and_upgrade_without_changing_configuration(hass, language, prefixes):
    hass.config.language = language
    entry = await setup_yaml(hass)
    before = entry_configuration(entry)
    identities = {item.subentry_id: item.unique_id for item in entry.subentries.values()}
    for item in entry.subentries.values():
        assert item.title == f"{prefixes[item.subentry_type]} · {item.data['key']}"

    # Simulate the title-only state of an existing v1.1.0 installation.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    for item in entry.subentries.values():
        hass.config_entries.async_update_subentry(entry, item, title=item.data["key"])
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry_configuration(entry) == before
    assert {item.subentry_id: item.unique_id for item in entry.subentries.values()} == identities
    for item in entry.subentries.values():
        assert item.title == f"{prefixes[item.subentry_type]} · {item.data['key']}"

    # A further reload neither duplicates prefixes nor rewrites identifiers.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry_configuration(entry) == before
    for item in entry.subentries.values():
        assert item.title == f"{prefixes[item.subentry_type]} · {item.data['key']}"
