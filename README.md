<div align="center">

[![GitHub Release](https://img.shields.io/github/release/Pulpyyyy/ESPSomfy-RTS-companion.svg?style=for-the-badge)](https://github.com/Pulpyyyy/ESPSomfy-RTS-companion/releases) [![License](https://img.shields.io/github/license/Pulpyyyy/ESPSomfy-RTS-companion.svg?style=for-the-badge)](LICENSE) [![Firmware](https://img.shields.io/github/release/Pulpyyyy/ESPSomfy-RTS.svg?style=for-the-badge&label=firmware)](https://github.com/Pulpyyyy/ESPSomfy-RTS/releases)

<img src="images/banner.png" alt="ESPSomfy-RTS Companion: the Home Assistant integration of the ESPSomfy-RTS v4 firmware" width="100%">

<a href="https://my.home-assistant.io/redirect/marketplace_repository/?owner=Pulpyyyy&repository=ESPSomfy-RTS-companion&category=integration">
  <img src="https://my.home-assistant.io/badges/marketplace_repository.svg" alt="Open this repository in the Marketplace of your Home Assistant">
</a>

**[Version française](README_fr.md)** · [Services](docs/Services.md) · [Report an issue](https://github.com/Pulpyyyy/ESPSomfy-RTS-companion/issues)

</div>

**ESPSomfy-RTS Companion** brings your Somfy RTS shades, blinds, awnings, gates and garage doors into Home Assistant, through an ESP32 board running the **[ESPSomfy-RTS v4 firmware](https://github.com/Pulpyyyy/ESPSomfy-RTS)**. It finds the board on its own, follows every move, including those made with your remotes, and installs firmware updates from Home Assistant.

## Start with the firmware

The integration talks to an ESP32 and a CC1101 radio module running **ESPSomfy-RTS v4**:

* **[Install it from your browser](https://pulpyyyy.github.io/ESPSomfy-RTS/)** (Chrome or Edge, USB cable), or with the files of the [latest release](https://github.com/Pulpyyyy/ESPSomfy-RTS/releases).
* **Every order gets through**: orders are queued, sent as one continuous train like a remote button press, and the board listens before it transmits.
* **Updates from GitHub in one click**, installed at boot, with an automatic return to the previous version if a new one does not start.
* **A modern interface** for phones and computers: Home page by room, position panel, guided calibration with your remote, RF diagnostics.
* **Secured**: PIN code or password, for the whole board or for its configuration only.

The [firmware wiki](https://github.com/Pulpyyyy/ESPSomfy-RTS/wiki) covers the hardware, the first start and every setting, in English and French.

## Installation

### From the Marketplace (Home Assistant 2026.11 or later)

Click the button above, or go to **Settings › Marketplace › Add from link** and enter `https://github.com/Pulpyyyy/ESPSomfy-RTS-companion`, then install **ESPSomfy-RTS Companion** and restart Home Assistant.

### With HACS (older versions of Home Assistant)

**HACS › Integrations › ⋮ › Custom repositories**, add `https://github.com/Pulpyyyy/ESPSomfy-RTS-companion` with the **Integration** category, install it, then restart Home Assistant.

### By hand

Copy `custom_components/espsomfy_rts_companion/` into the `config/custom_components/` folder of Home Assistant, then restart it.

### First setup

Home Assistant finds the board on its own (UPnP or mDNS): it shows up in **Settings › Devices & services**, ready to be added. Enter the PIN code or password if the board has one. If Home Assistant sits on another network segment, add the integration by hand with the address of the board.

## Coming from an earlier ESPSomfy-RTS integration

ESPSomfy-RTS Companion carries on the earlier ESPSomfy-RTS integrations for Home Assistant, under a new domain. It takes your board over as it is: every entity keeps its entity id, every device keeps its area and its name, and history carries on.

1. Remove the earlier integration from HACS, or delete its folder from `config/custom_components/`. **Leave it in Settings › Devices & services**: Companion takes over from there.
2. Install ESPSomfy-RTS Companion as above and restart Home Assistant.
3. Add the board when Home Assistant offers it, or by hand with its address. The PIN code or password of the earlier setup is reused, and so are its options.
4. In your automations and scripts, replace the actions of the earlier integration (`espsomfy_rts.*` or `espsomfy_rts_enhanced.*`) with `espsomfy_rts_companion.*`. Entity ids and the `espsomfy-rts_event` events do not change.

If the earlier integration was already removed from Devices & services, there is nothing left to take over: the entities get new ids, which you can rename back in their settings.

## Features

* **Full control**: open, close, stop and set positions in percent, tilt included, for shades and groups.
* **Always in sync**: positions follow the board in real time, whether the order came from Home Assistant, a remote or the board's own interface.
* **Rooms and groups in step**: the board's rooms are Home Assistant areas, both ways. Move a shade to another area, or rename an area, and the board follows; change a room on the board and Home Assistant follows. When a shade sits in a different room on each side, nothing is changed: a repair asks which side to keep. The board's groups show up as labels on their shades. It can be turned off in the integration options.
* **One click to the board**: the board, each shade and each group link to the matching page of the board's web interface (**Visit** on the device page).
* **Firmware updates**: an `update` entity shows when a new ESPSomfy-RTS release is out and installs it from Home Assistant.
* **Automations**: shades are standard `cover` entities, and the integration adds actions for steps, raw RTS commands, position correction without moving, sun and wind flags, restart and backup (see [Services](docs/Services.md)).
* **Device health**: a *Connectivity* diagnostic sensor per board is `on` while the websocket is connected and the HTTP API answers (checked every minute).
* **Radio health**: from the measurements of the board, the integration works out how many repeats each shade needs, the same way as the RF diagnostics page of the board. A shade that repeats too little gets a repair that sets the advised value in one click; a weak link measured with the guided session gets a warning with what to do. *Radio noise*, *Lost radio orders* and a *Radio margin* per shade are diagnostic sensors. A board still on firmware 2.x or 3.x gets a repair pointing at the browser installer.
* **Shades and groups follow the board**: one added on the board shows up in Home Assistant by itself, one deleted on the board leaves Home Assistant with its device, even when it was deleted while Home Assistant was stopped. A device still on the board cannot be deleted by hand, it would only come back.
* **Backups**: the *Backup* button (or the `espsomfy_rts_companion.backup` action) stores the board configuration on the Home Assistant host. A failed backup raises an error visible in automation traces, the *Last backup* sensor shows when the newest one was taken, and the number of backups kept (5 by default, 1 to 50) is set in the integration options. Every Home Assistant backup first takes a fresh copy of each board (unless one is less than an hour old), so restoring Home Assistant also brings back the configuration of your boards; a board that does not answer never makes the Home Assistant backup fail.
* **Restore**: the `espsomfy_rts_companion.restore` action sends a stored backup back to the board and brings back the sections you pick (shades by default). The board reboots when it is done.
* **Automations from your remotes**: a device trigger starts an automation when the board sees a command for a shade, including one pressed on a physical remote.
* **Diagnostics**: download the config entry diagnostics for a bug report, with the secrets removed.

## Events

Every command the board sees (from Home Assistant, a physical remote or its web interface) is sent on the Home Assistant event bus as an `espsomfy-rts_event` event.

| Key | Description |
| :--- | :--- |
| `entity_id` | The target entity in Home Assistant (e.g. `cover.living_room_shade`). |
| `event_key` | The event trigger (currently always `shadeCommand`). |
| `name` | The name of the device. |
| `remote_address` | The radio address of the motor in ESPSomfy-RTS. |
| `source_address` | The address of the source (remote channel or group). |
| `remote_type` | `remote` (a dedicated remote), `group` or `internal`. |
| `remote_slot` | The 1-based slot of a dedicated remote on this shade, else empty. |
| `remote_linked` | Whether the source remote is linked to this shade. |
| `remote_name` | A readable name: `Remote <shade> #<slot>` for a dedicated remote, the group name for a group, empty for internal. |
| `device_id` | The Home Assistant device of the shade. |
| `area` | The area of the shade, if any. |

`source` says where the command came from: `remote` (a physical remote), `internal` (the board's interface) or `group` (a group command). `command` is the action: `Up`, `Down`, `My`, `StepUp`, `StepDown`, `Prog`, or a key combination (`My+Up`, `My+Down`, `Up+Down`, `My+Up+Down`).

## Device triggers

To start an automation without listening for the raw event, use the device trigger **A shade received a command** (Settings > Automations > New automation > Add trigger > Device). It fires when the board sees a command for that shade, from Home Assistant or from a physical remote. The command and its source are on `trigger.event.data`.

```yaml
triggers:
  - trigger: device
    domain: espsomfy_rts_companion
    device_id: <your shade device>
    entity_id: <your cover entity>
    type: command_received
actions:
  - action: notify.notify
    data:
      message: >-
        {{ trigger.event.data.name }}: {{ trigger.event.data.command }}
        (from {{ trigger.event.data.source }})
```

## All shades at once

To start on a command from any shade, present or future, use the **A shade received a command** trigger of the integration (New automation > Add trigger > ESPSomfy-RTS Companion). Leave the target empty for every shade, or pick shades, areas or labels, and optionally filter by source.

```yaml
triggers:
  - trigger: espsomfy_rts_companion.command_received
    options:
      source: remote
actions:
  - action: notify.notify
    data:
      message: "{{ trigger.event.data.remote_name }} on {{ trigger.event.data.name }}"
```

## Credits

This integration started from xkain's [ESPSomfy-RTS Enhanced](https://github.com/xkain/ESPSomfy-RTS-enhanced), itself based on rstrouse's [ESPSomfy-RTS-HA](https://github.com/rstrouse/ESPSomfy-RTS-HA).
