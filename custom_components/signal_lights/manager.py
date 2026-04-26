from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Callable

from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_state_change_event


@dataclass
class Signal:
    signal_id: str
    priority: int = 50
    color: tuple[int, int, int] = (0, 255, 0)
    duration: int = 3
    show_only_on_turn_on: bool = True
    mode: str = "transient"  # transient | persistent
    source: str = "manual"   # manual | rule:<id>
    activate_when_off: bool = False


@dataclass
class SignalRule:
    rule_id: str
    source_entity: str
    active_state: str
    renderers: list[str]
    signal_id: str
    priority: int = 50
    color: tuple[int, int, int] = (0, 255, 0)
    duration: int = 3
    show_only_on_turn_on: bool = True
    mode: str = "transient"
    activate_when_off: bool = False

    @classmethod
    def from_config(cls, idx: int, data: dict[str, Any]) -> "SignalRule":
        return cls(
            rule_id=str(data.get("rule_id", f"rule_{idx}")),
            source_entity=data["source_entity"],
            active_state=str(data.get("active_state", "on")),
            renderers=list(data["renderers"]),
            signal_id=str(data["signal_id"]),
            priority=int(data.get("priority", 50)),
            color=tuple(data.get("color", [0, 255, 0])),
            duration=int(data.get("duration", 3)),
            show_only_on_turn_on=bool(data.get("show_only_on_turn_on", True)),
            mode=str(data.get("mode", "transient")),
            activate_when_off=bool(data.get("activate_when_off", False)),
        )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class Renderer:
    def __init__(self, hass: HomeAssistant, renderer_id: str, config: dict, lamp_profiles: dict):
        self.hass = hass
        self.id = renderer_id
        self.lights = config["lights"]
        self.baseline_conf = config.get("baseline", {})
        self.time_window = config.get("time_window", {})
        self.renderer_profile = config.get("profile")
        self.lamp_profiles = lamp_profiles or {}
        self.signals: dict[str, Signal] = {}

        self._lock = asyncio.Lock()
        self._last_on = False
        self._listeners: list[Callable[[], None]] = []
        self._last_notify_key: tuple | None = None

    def add_listener(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def _notify_key(self) -> tuple:
        transient = self.get_effective_signal("transient")
        persistent = self.get_effective_signal("persistent")
        return (
            self.any_on(),
            self.in_time_window(),
            transient.signal_id if transient else None,
            transient.priority if transient else None,
            persistent.signal_id if persistent else None,
            persistent.priority if persistent else None,
            tuple(sorted(self.signals.keys())),
        )

    def notify(self, force: bool = False) -> None:
        key = self._notify_key()
        if not force and key == self._last_notify_key:
            return
        self._last_notify_key = key
        for listener in self._listeners:
            listener()

    def is_on(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        return state is not None and state.state == STATE_ON

    def any_on(self) -> bool:
        return any(self.is_on(e) for e in self.lights)

    def _parse_time(self, value: str | None) -> time | None:
        if not value:
            return None
        try:
            parts = [int(p) for p in value.split(":")]
            if len(parts) == 2:
                return time(parts[0], parts[1], 0)
            if len(parts) == 3:
                return time(parts[0], parts[1], parts[2])
        except Exception:
            return None
        return None

    def in_time_window(self) -> bool:
        start = self._parse_time(self.time_window.get("start"))
        end = self._parse_time(self.time_window.get("end"))

        if start is None or end is None:
            return True

        now = datetime.now().time()

        if start <= end:
            return start <= now <= end

        return now >= start or now <= end

    def _expand_profile_reference(self, profile_ref: str | None) -> dict[str, Any]:
        if not profile_ref:
            return {}
        return dict(self.lamp_profiles.get(profile_ref, {}))

    def _get_profile_for_light(self, light_entity_id: str) -> dict[str, Any]:
        profile: dict[str, Any] = {}
        profile.update(self._expand_profile_reference(self.renderer_profile))

        lamp_entry = self.lamp_profiles.get(light_entity_id, {})
        if isinstance(lamp_entry, dict):
            if "profile" in lamp_entry:
                profile.update(self._expand_profile_reference(lamp_entry.get("profile")))
            profile.update({k: v for k, v in lamp_entry.items() if k != "profile"})

        return profile

    def _compute_template_baseline_for_light(self, light_entity_id: str) -> dict[str, Any]:
        profile = self._get_profile_for_light(light_entity_id)

        sun_state = self.hass.states.get("sun.sun")
        elevation = sun_state.attributes.get("elevation", 0) if sun_state else 0

        night = self.hass.states.get("input_boolean.night_mode")
        is_night = night is not None and night.state == "on"

        brightness_day = int(profile.get("brightness_day", 100))
        brightness_night = int(profile.get("brightness_night", 40))

        kelvin_min = int(profile.get("kelvin_min", 2203))
        kelvin_max = int(profile.get("kelvin_max", 4000))
        exponent = float(profile.get("exponent", 0.81))
        gain = float(profile.get("gain", 0.222))
        base = float(profile.get("base", 4791.67))
        divisor = float(profile.get("divisor", 3290.66))

        brightness = brightness_night if is_night else brightness_day

        elevation_clamped = _clamp(elevation, 0, 90)

        if elevation_clamped <= 0:
            raw_kelvin = kelvin_min
        else:
            raw_kelvin = base - divisor / (1 + gain * (elevation_clamped ** exponent))

        kelvin = int(_clamp(raw_kelvin, kelvin_min, kelvin_max))

        return {
            "brightness_pct": brightness,
            "color_temp_kelvin": kelvin,
        }

    def get_baseline_for_light(self, light_entity_id: str) -> dict[str, Any]:
        mode = self.baseline_conf.get("mode")

        if mode == "template":
            return self._compute_template_baseline_for_light(light_entity_id)

        if mode == "fixed":
            return {k: v for k, v in self.baseline_conf.items() if k != "mode"} or {
                "brightness_pct": 100,
                "color_temp_kelvin": 3200,
            }

        return {
            "brightness_pct": 100,
            "color_temp_kelvin": 3200,
        }

    def get_baselines(self) -> dict[str, dict[str, Any]]:
        return {light: self.get_baseline_for_light(light) for light in self.lights}

    def get_signals_by_mode(self, mode: str) -> list[Signal]:
        return [s for s in self.signals.values() if s.mode == mode]

    def get_effective_signal(self, mode: str | None = None) -> Signal | None:
        signals = list(self.signals.values()) if mode is None else self.get_signals_by_mode(mode)
        if not signals:
            return None
        return max(signals, key=lambda s: s.priority)

    async def apply_baseline(self) -> None:
        for light in self.lights:
            baseline = self.get_baseline_for_light(light)
            await self.hass.services.async_call(
                LIGHT_DOMAIN,
                "turn_on",
                {"entity_id": light, **baseline},
                blocking=True,
            )

    async def apply_persistent_signal(self, signal: Signal) -> None:
        baselines = self.get_baselines()
        for light in self.lights:
            baseline = baselines[light]
            await self.hass.services.async_call(
                LIGHT_DOMAIN,
                "turn_on",
                {
                    "entity_id": light,
                    "rgb_color": list(signal.color),
                    "brightness_pct": baseline.get("brightness_pct", 100),
                },
                blocking=True,
            )

    async def _render_transient_locked(self, signal: Signal, previous_on: dict[str, bool] | None = None) -> None:
        baselines = self.get_baselines()

        if previous_on is None:
            previous_on = {light: self.is_on(light) for light in self.lights}

        for light in self.lights:
            if signal.activate_when_off and not previous_on[light]:
                baseline = baselines[light]
                await self.hass.services.async_call(
                    LIGHT_DOMAIN,
                    "turn_on",
                    {
                        "entity_id": light,
                        "brightness_pct": baseline.get("brightness_pct", 100),
                    },
                    blocking=True,
                )

        for light in self.lights:
            baseline = baselines[light]
            await self.hass.services.async_call(
                LIGHT_DOMAIN,
                "turn_on",
                {
                    "entity_id": light,
                    "rgb_color": list(signal.color),
                    "brightness_pct": baseline.get("brightness_pct", 100),
                },
                blocking=True,
            )

        await asyncio.sleep(signal.duration)

        persistent = self.get_effective_signal("persistent")
        for light in self.lights:
            if signal.activate_when_off and not previous_on[light]:
                if persistent is not None and self.in_time_window():
                    baseline = baselines[light]
                    await self.hass.services.async_call(
                        LIGHT_DOMAIN,
                        "turn_on",
                        {
                            "entity_id": light,
                            "rgb_color": list(persistent.color),
                            "brightness_pct": baseline.get("brightness_pct", 100),
                        },
                        blocking=True,
                    )
                else:
                    await self.hass.services.async_call(
                        LIGHT_DOMAIN,
                        "turn_off",
                        {"entity_id": light},
                        blocking=True,
                    )

    async def _apply_final_state_locked(self) -> None:
        persistent = self.get_effective_signal("persistent")
        if persistent is not None and self.in_time_window():
            await self.apply_persistent_signal(persistent)
        else:
            await self.apply_baseline()

    async def handle_light_change(self) -> None:
        any_on = self.any_on()
        turned_on = any_on and not self._last_on
        self._last_on = any_on

        if not turned_on:
            self.notify()
            return

        async with self._lock:
            await self._apply_final_state_locked()

            transient = self.get_effective_signal("transient")
            if transient is not None and self.in_time_window() and transient.show_only_on_turn_on:
                previous_on = {light: self.is_on(light) for light in self.lights}
                await self._render_transient_locked(transient, previous_on)
                await self._apply_final_state_locked()

        self.notify(force=True)

    async def maybe_render_immediately(self, signal: Signal) -> None:
        if not self.in_time_window():
            return

        previous_on = {light: self.is_on(light) for light in self.lights}
        any_on = any(previous_on.values())
        did_work = False

        async with self._lock:
            if signal.mode == "persistent":
                if any_on:
                    await self._apply_final_state_locked()
                    did_work = True
            elif signal.mode == "transient":
                if signal.show_only_on_turn_on:
                    if signal.activate_when_off:
                        await self._render_transient_locked(signal, previous_on)
                        did_work = True
                    else:
                        return
                else:
                    if any_on or signal.activate_when_off:
                        await self._render_transient_locked(signal, previous_on)
                        if any_on:
                            await self._apply_final_state_locked()
                        did_work = True

        if did_work:
            self.notify(force=True)

    @property
    def state(self) -> str:
        transient = self.get_effective_signal("transient")
        persistent = self.get_effective_signal("persistent")

        if transient:
            return f"transient:{transient.signal_id}"
        if persistent:
            return f"persistent:{persistent.signal_id}"
        return "idle"

    @property
    def attributes(self) -> dict[str, Any]:
        transient = self.get_effective_signal("transient")
        persistent = self.get_effective_signal("persistent")

        return {
            "renderer_id": self.id,
            "lights": self.lights,
            "any_on": self.any_on(),
            "in_time_window": self.in_time_window(),
            "active_signal_ids": sorted(self.signals.keys()),
            "signals": {
                signal_id: {
                    "priority": s.priority,
                    "color": list(s.color),
                    "duration": s.duration,
                    "show_only_on_turn_on": s.show_only_on_turn_on,
                    "mode": s.mode,
                    "source": s.source,
                    "activate_when_off": s.activate_when_off,
                }
                for signal_id, s in self.signals.items()
            },
            "effective_transient_signal_id": transient.signal_id if transient else None,
            "effective_transient_priority": transient.priority if transient else None,
            "effective_persistent_signal_id": persistent.signal_id if persistent else None,
            "effective_persistent_priority": persistent.priority if persistent else None,
            "baselines": self.get_baselines(),
            "renderer_profile": self.renderer_profile,
        }


class Manager:
    def __init__(self, hass: HomeAssistant, config: dict):
        self.hass = hass
        self.renderers: dict[str, Renderer] = {}
        self.unsubs = []
        self.rules: list[SignalRule] = []

        self.light_to_renderers: dict[str, list[Renderer]] = {}
        self.source_entity_to_rules: dict[str, list[SignalRule]] = {}

        lamp_profiles = config.get("lamp_profiles", {})

        for rid, rconf in config.get("renderers", {}).items():
            renderer = Renderer(hass, rid, rconf, lamp_profiles)
            self.renderers[rid] = renderer
            for light in renderer.lights:
                self.light_to_renderers.setdefault(light, []).append(renderer)

        for idx, rule_conf in enumerate(config.get("signal_rules", []), start=1):
            rule = SignalRule.from_config(idx, rule_conf)
            self.rules.append(rule)
            self.source_entity_to_rules.setdefault(rule.source_entity, []).append(rule)

        self._setup_listeners()
        self._apply_all_rules_initial()

    def _setup_listeners(self) -> None:
        lights = sorted(self.light_to_renderers.keys())
        if lights:
            self.unsubs.append(
                async_track_state_change_event(
                    self.hass,
                    lights,
                    self._on_light_change,
                )
            )

        source_entities = sorted(self.source_entity_to_rules.keys())
        if source_entities:
            self.unsubs.append(
                async_track_state_change_event(
                    self.hass,
                    source_entities,
                    self._on_rule_source_change,
                )
            )

    def _apply_all_rules_initial(self) -> None:
        affected_renderers: set[Renderer] = set()
        for rule in self.rules:
            affected_renderers.update(self._apply_rule(rule))
        for renderer in affected_renderers:
            renderer.notify(force=True)

    async def _on_light_change(self, event) -> None:
        entity_id = event.data["entity_id"]
        for renderer in self.light_to_renderers.get(entity_id, []):
            self.hass.async_create_task(renderer.handle_light_change())

    async def _on_rule_source_change(self, event) -> None:
        entity_id = event.data["entity_id"]
        for rule in self.source_entity_to_rules.get(entity_id, []):
            await self._apply_rule_async(rule)

    def _is_rule_active(self, rule: SignalRule) -> bool:
        state = self.hass.states.get(rule.source_entity)
        return state is not None and state.state == rule.active_state

    def _apply_rule(self, rule: SignalRule) -> set[Renderer]:
        active = self._is_rule_active(rule)
        changed_renderers: set[Renderer] = set()

        for renderer_id in rule.renderers:
            renderer = self.renderers.get(renderer_id)
            if renderer is None:
                continue

            before = renderer._notify_key()

            if active:
                renderer.signals[rule.signal_id] = Signal(
                    signal_id=rule.signal_id,
                    priority=rule.priority,
                    color=rule.color,
                    duration=rule.duration,
                    show_only_on_turn_on=rule.show_only_on_turn_on,
                    mode=rule.mode,
                    source=f"rule:{rule.rule_id}",
                    activate_when_off=rule.activate_when_off,
                )
            else:
                existing = renderer.signals.get(rule.signal_id)
                if existing and existing.source == f"rule:{rule.rule_id}":
                    renderer.signals.pop(rule.signal_id, None)

            if renderer._notify_key() != before:
                changed_renderers.add(renderer)

        return changed_renderers

    async def _apply_rule_async(self, rule: SignalRule) -> None:
        active = self._is_rule_active(rule)

        for renderer_id in rule.renderers:
            renderer = self.renderers.get(renderer_id)
            if renderer is None:
                continue

            before = renderer._notify_key()

            if active:
                signal = Signal(
                    signal_id=rule.signal_id,
                    priority=rule.priority,
                    color=rule.color,
                    duration=rule.duration,
                    show_only_on_turn_on=rule.show_only_on_turn_on,
                    mode=rule.mode,
                    source=f"rule:{rule.rule_id}",
                    activate_when_off=rule.activate_when_off,
                )
                renderer.signals[rule.signal_id] = signal
                await renderer.maybe_render_immediately(signal)
            else:
                existing = renderer.signals.get(rule.signal_id)
                if existing and existing.source == f"rule:{rule.rule_id}":
                    renderer.signals.pop(rule.signal_id, None)
                    if renderer.any_on():
                        async with renderer._lock:
                            await renderer._apply_final_state_locked()

            if renderer._notify_key() != before:
                renderer.notify(force=True)

    async def push_signal(
        self,
        renderer_id: str,
        signal_id: str,
        priority: int,
        color,
        duration: int,
        show_only_on_turn_on: bool,
        mode: str,
        activate_when_off: bool = False,
    ) -> None:
        renderer = self.renderers[renderer_id]
        renderer.signals[signal_id] = Signal(
            signal_id=signal_id,
            priority=priority,
            color=tuple(color),
            duration=duration,
            show_only_on_turn_on=show_only_on_turn_on,
            mode=mode,
            source="manual",
            activate_when_off=activate_when_off,
        )
        await renderer.maybe_render_immediately(renderer.signals[signal_id])
        renderer.notify(force=True)

    async def clear_signal(self, renderer_id: str, signal_id: str) -> None:
        renderer = self.renderers[renderer_id]
        existed = signal_id in renderer.signals
        renderer.signals.pop(signal_id, None)
        if existed and renderer.any_on():
            async with renderer._lock:
                await renderer._apply_final_state_locked()
        if existed:
            renderer.notify(force=True)

    async def refresh_on_lights(self, entity_ids: list[str]) -> None:
        """Re-apply final state (signals or baseline) to lights that are currently ON."""
        touched: set[Renderer] = set()

        for entity_id in entity_ids:
            for renderer in self.light_to_renderers.get(entity_id, []):
                touched.add(renderer)

        for renderer in touched:
            relevant = [e for e in entity_ids if e in renderer.lights]
            if not relevant:
                continue

            if not any(
                self.hass.states.get(e) is not None
                and self.hass.states.get(e).state == STATE_ON
                for e in relevant
            ):
                continue

            async with renderer._lock:
                await renderer._apply_final_state_locked()

            renderer.notify(force=True)
