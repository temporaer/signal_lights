# Signal Lights

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant custom integration that overlays priority-based **signal colors** onto your smart lights. Lights briefly flash or hold a color to communicate events (doorbell rang, washing machine done, etc.) and then return to their normal baseline.

## Features

- **Renderers** — group lights that should react together (e.g. "kitchen", "hallway").
- **Transient signals** — brief color flash, then back to baseline.
- **Persistent signals** — hold a color until cleared.
- **Priority system** — highest-priority signal wins when multiple are active.
- **Signal rules** — declarative YAML rules that push/clear signals based on entity state changes.
- **Time windows** — restrict signal rendering to specific hours.
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

## License

[MIT](LICENSE)
