---
title: Home Assistant
description: Optional smart-home adapter for forecast-desk alerts.
sidebar_label: Home Assistant
sidebar_position: 5
---

# Home Assistant Integration

Superforecasting Agent can integrate with [Home Assistant](https://www.home-assistant.io/) as an optional inherited adapter. This is not part of the default forecast desk, but it can be useful for local operational alerts or environmental signals that support a forecast workflow.

1. **Gateway platform** — subscribes to real-time state changes via WebSocket and responds to events
2. **Smart home tools** — four LLM-callable tools for querying and controlling devices via the REST API

Home Assistant events and notifications are not durable forecast memory. If a state change matters to a forecast, attach it as timestamped evidence or a review alert in the forecast ledger before changing probability.

## Setup

### 1. Create a Long-Lived Access Token

1. Open your Home Assistant instance
2. Go to your **Profile** (click your name in the sidebar)
3. Scroll to **Long-Lived Access Tokens**
4. Click **Create Token**, give it a name like "Superforecasting Agent"
5. Copy the token

### 2. Configure Environment Variables

```bash
# Add to ~/.superforecasting-agent/.env

# Required: your Long-Lived Access Token
HASS_TOKEN=your-long-lived-access-token

# Optional: HA URL (default: http://homeassistant.local:8123)
HASS_URL=http://192.168.1.100:8123
```

:::info
The `homeassistant` toolset is automatically enabled when `HASS_TOKEN` is set. Both the gateway platform and the device control tools activate from this single token.
:::

### 3. Start the Gateway

```bash
superforecasting-agent gateway
```

Home Assistant will appear as a connected platform alongside any other enabled gateway platforms.

## Available Tools

Superforecasting Agent registers four optional tools for smart-home state and control:

### `ha_list_entities`

List Home Assistant entities, optionally filtered by domain or area.

**Parameters:**
- `domain` *(optional)* — Filter by entity domain: `light`, `switch`, `climate`, `sensor`, `binary_sensor`, `cover`, `fan`, `media_player`, etc.
- `area` *(optional)* — Filter by area/room name (matches against friendly names): `living room`, `kitchen`, `bedroom`, etc.

**Example:**
```
List all lights in the living room
```

Returns entity IDs, states, and friendly names.

### `ha_get_state`

Get detailed state of a single entity, including all attributes (brightness, color, temperature setpoint, sensor readings, etc.).

**Parameters:**
- `entity_id` *(required)* — The entity to query, e.g., `light.living_room`, `climate.thermostat`, `sensor.temperature`

**Example:**
```
What's the current state of climate.thermostat?
```

Returns: state, all attributes, last changed/updated timestamps.

### `ha_list_services`

List available services (actions) for device control. Shows what actions can be performed on each device type and what parameters they accept.

**Parameters:**
- `domain` *(optional)* — Filter by domain, e.g., `light`, `climate`, `switch`

**Example:**
```
What services are available for climate devices?
```

### `ha_call_service`

Call a Home Assistant service to control a device.

**Parameters:**
- `domain` *(required)* — Service domain: `light`, `switch`, `climate`, `cover`, `media_player`, `fan`, `scene`, `script`
- `service` *(required)* — Service name: `turn_on`, `turn_off`, `toggle`, `set_temperature`, `set_hvac_mode`, `open_cover`, `close_cover`, `set_volume_level`
- `entity_id` *(optional)* — Target entity, e.g., `light.living_room`
- `data` *(optional)* — Additional parameters as a JSON object

**Examples:**

```
Turn on the living room lights
→ ha_call_service(domain="light", service="turn_on", entity_id="light.living_room")
```

```
Set the thermostat to 22 degrees in heat mode
→ ha_call_service(domain="climate", service="set_temperature",
    entity_id="climate.thermostat", data={"temperature": 22, "hvac_mode": "heat"})
```

```
Set living room lights to blue at 50% brightness
→ ha_call_service(domain="light", service="turn_on",
    entity_id="light.living_room", data={"brightness": 128, "color_name": "blue"})
```

## Gateway Platform: Real-Time Events

The Home Assistant gateway adapter connects via WebSocket and subscribes to `state_changed` events. When a device state changes and matches your filters, it is forwarded to the forecast runtime as a message.

### Event Filtering

:::warning Required Configuration
By default, **no events are forwarded**. You must configure at least one of `watch_domains`, `watch_entities`, or `watch_all` to receive events. Without filters, a warning is logged at startup and all state changes are silently dropped.
:::

Configure which events the forecast runtime sees in `~/.superforecasting-agent/config.yaml` under the Home Assistant platform's `extra` section:

```yaml
platforms:
  homeassistant:
    enabled: true
    extra:
      watch_domains:
        - climate
        - binary_sensor
        - alarm_control_panel
        - light
      watch_entities:
        - sensor.front_door_battery
      ignore_entities:
        - sensor.uptime
        - sensor.cpu_usage
        - sensor.memory_usage
      cooldown_seconds: 30
```

| Setting | Default | Description |
|---------|---------|-------------|
| `watch_domains` | *(none)* | Only watch these entity domains (e.g., `climate`, `light`, `binary_sensor`) |
| `watch_entities` | *(none)* | Only watch these specific entity IDs |
| `watch_all` | `false` | Set to `true` to receive **all** state changes (not recommended for most setups) |
| `ignore_entities` | *(none)* | Always ignore these entities (applied before domain/entity filters) |
| `cooldown_seconds` | `30` | Minimum seconds between events for the same entity |

:::tip
Start with a focused set of domains — `climate`, `binary_sensor`, and `alarm_control_panel` cover the most useful automations. Add more as needed. Use `ignore_entities` to suppress noisy sensors like CPU temperature or uptime counters.
:::

### Event Formatting

State changes are formatted as human-readable messages based on domain:

| Domain | Format |
|--------|--------|
| `climate` | "HVAC mode changed from 'off' to 'heat' (current: 21, target: 23)" |
| `sensor` | "changed from 21°C to 22°C" |
| `binary_sensor` | "triggered" / "cleared" |
| `light`, `switch`, `fan` | "turned on" / "turned off" |
| `alarm_control_panel` | "alarm state changed from 'armed_away' to 'triggered'" |
| *(other)* | "changed from 'old' to 'new'" |

### Forecast Runtime Responses

Outbound messages from the forecast runtime are delivered as **Home Assistant persistent notifications** (via `persistent_notification.create`). These appear in the HA notification panel with the title "Superforecasting Agent".

### Connection Management

- **WebSocket** with 30-second heartbeat for real-time events
- **Automatic reconnection** with backoff: 5s → 10s → 30s → 60s
- **REST API** for outbound notifications (separate session to avoid WebSocket conflicts)
- **Authorization** — HA events are always authorized (no user allowlist needed, since the `HASS_TOKEN` authenticates the connection)

## Security

The Home Assistant tools enforce security restrictions:

:::warning Blocked Domains
The following service domains are **blocked** to prevent arbitrary code execution on the HA host:

- `shell_command` — arbitrary shell commands
- `command_line` — sensors/switches that execute commands
- `python_script` — scripted Python execution
- `pyscript` — broader scripting integration
- `hassio` — addon control, host shutdown/reboot
- `rest_command` — HTTP requests from HA server (SSRF vector)

Attempting to call services in these domains returns an error.
:::

Entity IDs are validated against the pattern `^[a-z_][a-z0-9_]*\.[a-z0-9_]+$` to prevent injection attacks.

## Example Automations

### Morning Routine

```
User: Run the lab-open checklist

Runtime:
1. ha_call_service(domain="light", service="turn_on",
     entity_id="light.bedroom", data={"brightness": 128})
2. ha_call_service(domain="climate", service="set_temperature",
     entity_id="climate.thermostat", data={"temperature": 22})
3. ha_call_service(domain="media_player", service="turn_on",
     entity_id="media_player.kitchen_speaker")
```

### Security Check

```
User: Is the lab secure?

Runtime:
1. ha_list_entities(domain="binary_sensor")
     → checks door/window sensors
2. ha_get_state(entity_id="alarm_control_panel.home")
     → checks alarm status
3. ha_list_entities(domain="lock")
     → checks lock states
4. Reports: "All doors closed, alarm is armed_away, all locks engaged."
```

### Reactive Automation (via Gateway Events)

When connected as a gateway platform, the runtime can react to events:

```
[Home Assistant] Front Door: triggered (was cleared)

Runtime:
1. ha_get_state(entity_id="binary_sensor.front_door")
2. ha_call_service(domain="light", service="turn_on",
     entity_id="light.hallway")
3. Sends notification: "Front door opened. Hallway lights turned on."
```
