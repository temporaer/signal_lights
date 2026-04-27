# Copilot Instructions for signal_lights

## Build, test, and lint

```bash
# Environment (conda)
conda activate signal_lights

# Full suite
pytest
ruff check
mypy custom_components/signal_lights/ tests/

# Single test file or test
pytest tests/test_rendering.py
pytest tests/test_scenarios.py::test_scenario_washing_machine -xvs

# Auto-fix lint
ruff check --fix
```

All config is in `pyproject.toml`. Tests use `asyncio_mode = "auto"` — no need for `@pytest.mark.asyncio`.

## Architecture

This is a **YAML-configured Home Assistant custom integration** (no config flow). The domain is `signal_lights`.

**Core data flow:** `Manager` → `Renderer` → lights. `SignalRule`s watch HA entity states and push/clear `Signal`s on renderers.

- **Manager** (`manager.py`): Owns all renderers and rules. Listens for HA state changes on lights and rule source entities. Routes changes to the appropriate renderer.
- **Renderer** (`manager.py`): A group of lights that react together. Holds active signals, resolves priority (highest wins per mode), and calls `light.turn_on`/`turn_off` services.
- **Signal** (`manager.py`): A dataclass with `signal_id`, `priority`, `color`, `mode` (transient/persistent), `duration`, `activate_when_off`, `show_only_on_turn_on`.
- **SignalRule** (`manager.py`): Declarative YAML rule that auto-pushes/clears a signal when a source entity matches `active_state`.

**Two signal modes:**
- *Transient*: flash color → sleep(duration) → restore. The lock is released during sleep with a generation token (`_transient_gen`) to prevent stale restores from clobbering newer transients.
- *Persistent*: hold color until explicitly cleared. Only renders on lights that are already on.

**Key concurrency pattern in `_render_transient`:** The method runs under `self._lock` but releases it during `asyncio.sleep`, then re-acquires. The `_transient_gen` counter detects if a newer transient superseded this one during sleep — if so, the restore phase is skipped.

**`activate_when_off` bypasses `time_window`:** Signals with `activate_when_off: true` skip the `in_time_window()` check in both `maybe_render_immediately` and `handle_light_change`, since the user explicitly asked to wake sleeping lights.

## Testing conventions

Tests use `FakeHass` (in `tests/conftest.py`), not the real HA test harness. FakeHass provides:
- `_states` dict with `set_state()` / `states.get()`
- `services.async_call` as `AsyncMock`
- `bus.async_fire` as `MagicMock`
- `data` dict, `async_create_task()`

When testing transient signals, patch `asyncio.sleep` to avoid real delays:
```python
with patch("custom_components.signal_lights.manager.asyncio.sleep"):
    await manager.push_signal(...)
```

When testing time_window behavior, use a window like `{"start": "00:00", "end": "00:01"}` to simulate "outside window" without mocking time.

Always set light states before creating a Manager — the constructor calls `_apply_all_rules_initial()` which reads state immediately.

## Key conventions

- All constants live in `const.py` and are imported by name — never use string literals for service names, config keys, or event types in source code.
- `Signal.color` is `tuple[int, int, int]`, but service calls and configs use `list[int]`. Convert with `(color[0], color[1], color[2])` (not `tuple(color)` — mypy rejects the latter).
- Mypy is strict on source, relaxed on tests (see `[[tool.mypy.overrides]]`).
- `sensor.py` imports `Renderer`, `Manager`, `SignalRule` from `manager.py` for type annotations.
- The `LIGHT_DOMAIN = "light"` constant is defined locally in `manager.py` (not imported from HA) to avoid a mypy re-export error.
