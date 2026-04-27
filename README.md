# Signal Lights

[![CI](https://github.com/temporaer/signal_lights/actions/workflows/ci.yml/badge.svg)](https://github.com/temporaer/signal_lights/actions/workflows/ci.yml)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![mypy](https://img.shields.io/badge/mypy-strict-blue.svg)](https://mypy-lang.org/)
[![ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A Home Assistant custom integration that turns your everyday lights into **context-aware notification channels**. Unlike simple "flash when event fires" automations, Signal Lights intercepts light state changes so signals appear at the right moment — when you actually walk into a room and flip the light on, not while you're asleep or away. Signals are priority-ranked, non-destructive, and automatically restore your normal lighting afterward.

## Features

- **Renderers** — group lights that should react together (e.g. "kitchen", "hallway").
- **Transient signals** — brief color flash, then back to baseline.
- **Persistent signals** — hold a color until cleared.
- **Priority system** — highest-priority signal wins when multiple are active.
- **Signal rules** — declarative YAML rules that push/clear signals based on entity state changes.
- **Time windows** — restrict signal rendering to specific hours. Signals with `activate_when_off: true` bypass the time window so they can wake sleeping lights anytime.
- **Lamp profiles** — per-light brightness/color-temperature curves driven by sun elevation and night mode.
- **Mermaid diagram sensor** — auto-generated live diagram of renderers, signals, and lights.

## Installation

### HACS (recommended)

1. Open HACS → **Integrations** → ⋮ menu → **Custom repositories**.
2. Add `https://github.com/temporaer/signal_lights` with category **Integration**.
3. Search for *Signal Lights* and install.
4. Restart Home Assistant.

### Manual

Copy `custom_components/signal_lights/` into your Home Assistant `config/custom_components/` directory and restart.

## Configuration

Add a `signal_lights:` block to your `configuration.yaml`:

```yaml
signal_lights:
  renderers:
    kitchen:
      lights:
        - light.kitchen_ceiling
        - light.kitchen_counter
      baseline:
        mode: template          # "template" | "fixed"
      time_window:
        start: "06:00"
        end: "23:00"

  lamp_profiles:
    default:
      brightness_day: 100
      brightness_night: 40
      kelvin_min: 2203
      kelvin_max: 4000

  signal_rules:
    - rule_id: doorbell
      source_entity: binary_sensor.doorbell
      active_state: "on"
      renderers: [kitchen]
      signal_id: doorbell_ring
      color: [255, 50, 0]
      duration: 5
      priority: 80
      mode: transient
```

## Services

| Service | Description |
|---|---|
| `signal_lights.push_signal` | Push a signal to a renderer (renderer_id, signal_id, color, priority, duration, mode, …) |
| `signal_lights.clear_signal` | Remove a signal from a renderer |
| `signal_lights.refresh_on_lights` | Re-apply current state to lights that are on |

## Examples

### "Washing machine done" — flash when you walk past

You want the hallway light to briefly flash green when the washing machine finishes, but only when somebody actually turns on or walks past the light (i.e. it transitions from off → on). The flash shouldn't wake up a dark hallway on its own.

**Setup:** You have a `binary_sensor.washing_machine` that turns `on` when a cycle completes (e.g. via a power-monitoring smart plug).

```yaml
signal_lights:
  renderers:
    hallway:
      lights:
        - light.hallway
      time_window:
        start: "06:00"
        end: "23:00"

  signal_rules:
    - rule_id: washing_done
      source_entity: binary_sensor.washing_machine
      active_state: "on"
      renderers: [hallway]
      signal_id: washing_done
      color: [0, 255, 50]       # green
      duration: 4                # flash for 4 seconds
      priority: 50
      mode: transient            # brief flash, then back to normal
      show_only_on_turn_on: true # only flash on the off→on edge
```

**What happens:**
1. The washing machine finishes → `binary_sensor.washing_machine` turns `on`.
2. The signal `washing_done` is registered on the `hallway` renderer, but nothing visible happens yet — the hallway light is off and `show_only_on_turn_on` is set.
3. Later, you walk past and a motion automation turns on `light.hallway`.
4. Signal Lights intercepts the turn-on, applies your normal baseline brightness/color-temp, then flashes green for 4 seconds, and restores the baseline.
5. When you mark the washing machine as unloaded (sensor goes `off`), the signal is automatically removed. Next time the light turns on, no flash.

---

### "Letterbox has mail" — persistent glow, even wake the light

You want a light to glow blue whenever there's mail in the letterbox, regardless of whether the light was on before. Even if the light is off, it should briefly turn on to show you the signal when motion is detected nearby.

**Setup:** You have a `binary_sensor.letterbox` (e.g. a contact sensor on the letterbox flap) and a `binary_sensor.front_door_motion`.

```yaml
signal_lights:
  renderers:
    entrance:
      lights:
        - light.entrance
      time_window:
        start: "07:00"
        end: "22:00"

  signal_rules:
    # Persistent blue glow while mail is present
    - rule_id: mail_persistent
      source_entity: binary_sensor.letterbox
      active_state: "on"
      renderers: [entrance]
      signal_id: mail_waiting
      color: [30, 100, 255]     # blue
      priority: 60
      mode: persistent           # hold this color, don't flash
      activate_when_off: false   # don't wake the light just for persistent

    # Also flash when motion is detected, even if light is off
    - rule_id: mail_motion_flash
      source_entity: binary_sensor.front_door_motion
      active_state: "on"
      renderers: [entrance]
      signal_id: mail_flash
      color: [30, 100, 255]     # same blue
      duration: 5
      priority: 70               # higher than persistent, so this wins
      mode: transient
      show_only_on_turn_on: false # flash immediately on motion event
      activate_when_off: true     # turn on the light even if it's off
```

**What happens:**
1. Mail arrives → `binary_sensor.letterbox` turns `on` → the persistent `mail_waiting` signal is registered.
2. If `light.entrance` is already on, it immediately switches to a blue glow at your configured brightness.
3. If the light is off, nothing visible happens yet (persistent + `activate_when_off: false`).
4. Motion detected at front door → the transient `mail_flash` rule fires with `activate_when_off: true`. The light turns on, flashes blue for 5 seconds, then turns off again (it was off before, so it goes back to off). The persistent signal will show next time you intentionally turn the light on.
5. When you turn the entrance light on normally (e.g. via a switch), it shows the persistent blue glow instead of the normal warm white — reminding you there's mail.
6. You collect the mail → `binary_sensor.letterbox` goes `off` → the persistent `mail_waiting` signal clears → the light returns to its normal baseline. (The motion flash signal clears separately when `binary_sensor.front_door_motion` goes `off`.)

---

### "Doorbell + washing machine at the same time" — priorities

When multiple signals are active, the highest priority wins. You can layer signals across the same renderer.

```yaml
signal_lights:
  renderers:
    kitchen:
      lights:
        - light.kitchen_ceiling
        - light.kitchen_counter

  signal_rules:
    - rule_id: washing_done
      source_entity: binary_sensor.washing_machine
      active_state: "on"
      renderers: [kitchen]
      signal_id: washing_done
      color: [0, 255, 50]
      duration: 4
      priority: 50
      mode: transient

    - rule_id: doorbell
      source_entity: binary_sensor.doorbell
      active_state: "on"
      renderers: [kitchen]
      signal_id: doorbell_ring
      color: [255, 50, 0]       # red-orange
      duration: 6
      priority: 80               # higher than washing
      mode: transient
      activate_when_off: true    # doorbell is urgent, wake lights
```

If both the washing machine and the doorbell fire at the same time, the doorbell signal (priority 80) wins and is the one rendered. The washing signal stays queued — if you turn the light on again after the doorbell clears, you'll still get the green flash for the washing machine.

### "Signal even when it's bright" — daytime flash-and-off

Some lights stay off during the day (it's bright enough), but you still want them to flash for signals. Use `activate_when_off: true` with `show_only_on_turn_on: false` — these signals bypass the `time_window` so they work 24/7:

```yaml
signal_lights:
  renderers:
    hallway:
      lights: [light.hallway_ceiling]
      baseline:
        mode: template
      time_window:
        start: "17:00"
        end: "08:00"         # only color lights at night
  signal_rules:
    - source_entity: binary_sensor.washing_machine
      signal_id: washing_done
      renderers: [hallway]
      color: [0, 255, 0]
      mode: transient
      show_only_on_turn_on: false   # flash immediately
      activate_when_off: true       # wake the light even if off
      duration: 5
```

**What happens at 2pm (light is off, outside time window):**

1. `binary_sensor.washing_machine` turns `on`.
2. Rule pushes `washing_done` (transient, `activate_when_off`).
3. Light wakes up, flashes green for 5 seconds.
4. Light turns back off (it was off before the signal).

The `time_window` still restricts baseline and persistent coloring to nighttime — only `activate_when_off` transients bypass it.

Use a separate HA automation to turn the light on/off based on brightness:

```yaml
automation:
  - alias: "Hallway on when dark"
    trigger:
      platform: numeric_state
      entity_id: sensor.hallway_lux
      below: 30
    action:
      service: light.turn_on
      target: { entity_id: light.hallway_ceiling }

  - alias: "Hallway off when bright"
    trigger:
      platform: numeric_state
      entity_id: sensor.hallway_lux
      above: 50
    action:
      service: light.turn_off
      target: { entity_id: light.hallway_ceiling }
```

## Transparency

This project was **vibe-coded** — designed and implemented with significant AI assistance (GitHub Copilot). To compensate for that, we invest heavily in automated quality gates:

- **Strict mypy** type checking on all source code
- **Ruff** linting with a broad rule set
- **60+ automated tests** covering signals, rendering, concurrency, time windows, and end-to-end scenarios
- **CI on every push and PR** (GitHub Actions)
- **Pre-commit hooks** to catch issues before they reach the repo

Read the tests — they're the best documentation of what the code actually does. If you find a discrepancy between the README and the code, [open an issue](https://github.com/temporaer/signal_lights/issues).

## License

[MIT](LICENSE)
