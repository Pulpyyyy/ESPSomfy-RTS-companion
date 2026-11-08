# Automation examples

Practical recipes built on the integration's triggers, events and entities.
Replace the entity ids, device ids and remote addresses with your own.

## React to a physical remote

Start when any shade is operated from a physical remote, present or future, and
use the readable `remote_name` the event carries. The integration trigger needs
no entity id; leave the target empty for every shade, or set it to shades, areas
or labels.

```yaml
triggers:
  - trigger: espsomfy_rts_companion.command_received
    options:
      source: remote
actions:
  - action: notify.notify
    data:
      message: >-
        {{ trigger.event.data.remote_name }} sent {{ trigger.event.data.command }}
        to {{ trigger.event.data.name }}
```

The event also carries `remote_type` (`remote`, `group` or `internal`),
`remote_slot` (the 1-based slot of a dedicated remote on the shade),
`remote_linked`, `source_address`, `device_id` and `area`.

## A specific remote button runs a scene

Filter the integration trigger by `remote_address`, then check the command. Use
this to turn a spare remote button into a scene or script trigger.

```yaml
triggers:
  - trigger: espsomfy_rts_companion.command_received
    options:
      source: remote
      remote_address: 123456
conditions:
  - "{{ trigger.event.data.command == 'My' }}"
actions:
  - action: scene.turn_on
    target:
      entity_id: scene.evening
```

## Only one shade, from the visual editor

For a single shade, the device trigger is the simplest: New automation, Add
trigger, Device, pick the shade, then **A shade received a command**. An optional
source or remote address filter narrows it.

```yaml
triggers:
  - trigger: device
    domain: espsomfy_rts_companion
    device_id: <your shade device>
    entity_id: <your cover entity>
    type: command_received
    source: remote
actions:
  - action: notify.notify
    data:
      message: "Living room shade: {{ trigger.event.data.command }}"
```

## Alert when a board stops answering

The per board **Connectivity** sensor turns `off` when the websocket drops or the
HTTP API stops answering. It stays available, so its state carries the alert.

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.espsomfyrts_connectivity
    to: "off"
    for: "00:02:00"
actions:
  - action: notify.notify
    data:
      message: The ESPSomfy-RTS board is no longer reachable.
```

## Nightly backup, only when the board is reachable

The backup action fails with an error when the board is offline, so guard it with
the Connectivity sensor. See [Services](Services.md#backup) for the action and
[Services](Services.md#restore) for restoring a backup.

```yaml
triggers:
  - trigger: time
    at: "03:00:00"
conditions:
  - condition: state
    entity_id: binary_sensor.espsomfyrts_connectivity
    state: "on"
actions:
  - action: espsomfy_rts_companion.backup
    target:
      entity_id: button.espsomfyrts_backup
```
