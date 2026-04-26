from __future__ import annotations

import base64
import re

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_MANAGER, DOMAIN


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", value)


def _b64_url(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode()


class SignalLightsRendererSensor(SensorEntity):
    _attr_should_poll = False

    def __init__(self, renderer):
        self.renderer = renderer
        self._attr_unique_id = f"signal_lights_{renderer.id}"
        self._attr_name = f"Signal Lights {renderer.id}"

    async def async_added_to_hass(self) -> None:
        self.renderer.add_listener(self._handle_renderer_update)

    def _handle_renderer_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self):
        return self.renderer.state

    @property
    def extra_state_attributes(self):
        return self.renderer.attributes


class SignalLightsDiagramSensor(SensorEntity):
    _attr_should_poll = False

    def __init__(self, manager):
        self.manager = manager
        self._attr_unique_id = "signal_lights_diagram"
        self._attr_name = "Signal Lights Diagram"
        self._cache_key: tuple | None = None
        self._cache_full: str | None = None
        self._cache_active: str | None = None

    async def async_added_to_hass(self) -> None:
        for renderer in self.manager.renderers.values():
            renderer.add_listener(self._handle_update)

    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self):
        return "ready"

    def _make_cache_key(self) -> tuple:
        parts = []
        for renderer_id in sorted(self.manager.renderers):
            renderer = self.manager.renderers[renderer_id]
            transient = renderer.get_effective_signal("transient")
            persistent = renderer.get_effective_signal("persistent")
            parts.append(
                (
                    renderer_id,
                    renderer.any_on(),
                    transient.signal_id if transient else None,
                    persistent.signal_id if persistent else None,
                    tuple(sorted(renderer.signals.keys())),
                )
            )
        return tuple(parts)

    def _ensure_cache(self) -> None:
        key = self._make_cache_key()
        if key == self._cache_key and self._cache_full is not None and self._cache_active is not None:
            return
        self._cache_key = key
        self._cache_full = self._build_mermaid(active_only=False)
        self._cache_active = self._build_mermaid(active_only=True)

    @property
    def extra_state_attributes(self):
        self._ensure_cache()
        mermaid = self._cache_full or "flowchart LR\n  empty[empty]"
        active_mermaid = self._cache_active or "flowchart LR\n  empty[empty]"

        png_url = f"https://mermaid.ink/img/{_b64_url(mermaid)}"
        svg_url = f"https://mermaid.ink/svg/{_b64_url(mermaid)}"
        active_png_url = f"https://mermaid.ink/img/{_b64_url(active_mermaid)}"
        active_svg_url = f"https://mermaid.ink/svg/{_b64_url(active_mermaid)}"

        active_renderer_count = 0
        active_signal_count = 0
        for renderer in self.manager.renderers.values():
            if renderer.any_on() or renderer.get_effective_signal() is not None:
                active_renderer_count += 1
            active_signal_count += len(renderer.signals)

        return {
            "mermaid": mermaid,
            "active_mermaid": active_mermaid,
            "png_url": png_url,
            "svg_url": svg_url,
            "active_png_url": active_png_url,
            "active_svg_url": active_svg_url,
            "renderers": sorted(self.manager.renderers.keys()),
            "rules": [rule.rule_id for rule in self.manager.rules],
            "active_renderer_count": active_renderer_count,
            "active_signal_count": active_signal_count,
        }

    def _build_mermaid(self, active_only: bool = False) -> str:
        lines: list[str] = [
            "flowchart LR",
            "classDef sourceOn fill:#dcfce7,stroke:#16a34a,color:#052e16,stroke-width:2px;",
            "classDef sourceOff fill:#f1f5f9,stroke:#94a3b8,color:#334155,stroke-dasharray: 4 4;",
            "classDef rendererActive fill:#dbeafe,stroke:#2563eb,color:#172554,stroke-width:2px;",
            "classDef rendererIdle fill:#f8fafc,stroke:#94a3b8,color:#334155;",
            "classDef lightOn fill:#fef3c7,stroke:#d97706,color:#451a03,stroke-width:2px;",
            "classDef lightOff fill:#ffffff,stroke:#94a3b8,color:#334155;",
        ]

        included_renderers: dict[str, object] = {}
        included_rules = []

        for rule in self.manager.rules:
            rule_is_active_anywhere = False
            for renderer_id in rule.renderers:
                renderer = self.manager.renderers.get(renderer_id)
                if renderer is None:
                    continue
                if rule.signal_id in renderer.signals:
                    rule_is_active_anywhere = True
                    break

            if active_only and not rule_is_active_anywhere:
                continue

            included_rules.append(rule)
            for renderer_id in rule.renderers:
                renderer = self.manager.renderers.get(renderer_id)
                if renderer is not None:
                    included_renderers[renderer_id] = renderer

        if active_only:
            for renderer_id, renderer in self.manager.renderers.items():
                if renderer.any_on() or renderer.get_effective_signal() is not None:
                    included_renderers[renderer_id] = renderer
        else:
            included_renderers = dict(self.manager.renderers)

        if active_only and not included_renderers:
            lines.append('  idle["No active renderers or signals"]')
            return "\n".join(lines)

        seen_sources: set[str] = set()
        for rule in included_rules:
            src_id = _safe_id(f"src_{rule.source_entity}")
            if src_id in seen_sources:
                continue
            seen_sources.add(src_id)

            state = self.manager.hass.states.get(rule.source_entity)
            is_active = state is not None and state.state == rule.active_state
            state_text = state.state if state is not None else "missing"
            label = f"{rule.source_entity}<br/><small>{state_text}</small>"
            klass = "sourceOn" if is_active else "sourceOff"
            lines.append(f'  {src_id}["{label}"]:::{klass}')

        for renderer_id, renderer in included_renderers.items():
            sub_id = _safe_id(f"renderer_{renderer_id}")
            renderer_active = renderer.any_on() or renderer.get_effective_signal() is not None
            winner_t = renderer.get_effective_signal("transient")
            winner_p = renderer.get_effective_signal("persistent")

            title_bits = [renderer_id]
            if winner_t is not None:
                title_bits.append(f"T:{winner_t.signal_id}")
            if winner_p is not None:
                title_bits.append(f"P:{winner_p.signal_id}")
            title = " | ".join(title_bits)

            lines.append(f'  subgraph {sub_id}["{title}"]')
            lines.append("    direction TB")
            for light in renderer.lights:
                light_id = _safe_id(f"light_{light}")
                light_on = renderer.is_on(light)
                klass = "lightOn" if light_on else "lightOff"
                baseline = renderer.get_baseline_for_light(light)
                b = baseline.get("brightness_pct", "?")
                k = baseline.get("color_temp_kelvin", "?")
                label = f"{light}<br/><small>{'on' if light_on else 'off'} · {b}% · {k}K</small>"
                lines.append(f'    {light_id}["{label}"]:::{klass}')
            lines.append("  end")
            lines.append(f"  class {sub_id} {'rendererActive' if renderer_active else 'rendererIdle'};")

        for rule in included_rules:
            src_id = _safe_id(f"src_{rule.source_entity}")

            for renderer_id in rule.renderers:
                renderer = included_renderers.get(renderer_id)
                if renderer is None:
                    continue

                winner_t = renderer.get_effective_signal("transient")
                winner_p = renderer.get_effective_signal("persistent")
                is_winner = (
                    (winner_t is not None and winner_t.signal_id == rule.signal_id)
                    or (winner_p is not None and winner_p.signal_id == rule.signal_id)
                )
                is_active_here = rule.signal_id in renderer.signals

                label_parts = [rule.signal_id, rule.mode, f"p{rule.priority}"]
                if getattr(rule, "activate_when_off", False):
                    label_parts.append("wake")
                if is_active_here:
                    label_parts.append("active")
                if is_winner:
                    label_parts.append("WIN")

                label = ", ".join(label_parts)

                for light in renderer.lights:
                    light_id = _safe_id(f"light_{light}")
                    lines.append(f'  {src_id} -->|{label}| {light_id}')

        return "\n".join(lines)


async def async_setup_platform(
    hass: HomeAssistant,
    config,
    async_add_entities: AddEntitiesCallback,
    discovery_info=None,
) -> None:
    manager = hass.data[DOMAIN][DATA_MANAGER]
    entities = [SignalLightsRendererSensor(renderer) for renderer in manager.renderers.values()]
    entities.append(SignalLightsDiagramSensor(manager))
    async_add_entities(entities)
