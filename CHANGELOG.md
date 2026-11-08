# Changelog

## 4.2.1

### Fixed
- The **integration command trigger** now accepts the `remote_address`
  filter its documentation and the device trigger already offered; it was
  rejected before.

## 4.2.0

### Added
- **Richer command events.** Every `espsomfy-rts_event` now also carries
  `remote_type` (`remote`, `group` or `internal`), `remote_slot`,
  `remote_linked`, a readable `remote_name` (`Remote <shade> #<slot>` for a
  dedicated remote, the group name for a group), `device_id` and `area`.
- **Integration trigger: a shade received a command.** Starts an automation
  from any shade, present or future, with an optional target (shades, areas
  or labels) and an optional source filter. No entity to name.
- **Source and remote filters on the device trigger**, to narrow it to a
  source or one remote address.

### Changed
- **Home Assistant 2026.10 or later is now required**, for the integration
  command trigger, which uses the trigger API added in that release.

## 4.1.0

### Added
- **Diagnostics.** The config entry can download diagnostics, with the login
  details, the API key and the radio addresses and rolling codes taken out.
- **Restore a backup to the board.** A `restore` action sends a stored backup
  back to the board and brings back the chosen sections (shades by default,
  and optionally the general settings, network, radio, repeaters or MQTT).
  The board reboots once it is done. It fails with an error when the board is
  unreachable or rejects the restore.
- **Device trigger: a shade received a command.** An automation can start when
  the board sees a command for a shade, including one sent from a physical
  remote, and read the command, its source and the remote address.

## 4.0.1

### Fixed
- A group deleted on the board now takes its label off the shades. The
  label was left on them for good.

## 4.0.0

### Added
- **Takes over an earlier ESPSomfy-RTS integration.** A board still set up
  under an earlier ESPSomfy-RTS integration (`espsomfy_rts` or
  `espsomfy_rts_enhanced`) is taken over when it is added: every entity keeps
  its entity id, every device its area and name, history carries on, and the
  PIN code or password and the options are reused.
- **Rooms and areas, both ways.** Each room of the board is linked to a Home
  Assistant area (created when missing), and each shade device sits in the
  area of its room. Moving a shade to another area, or renaming a linked area,
  is written to the board (a missing room is created there); changes made on
  the board come back to Home Assistant, at once for added or removed rooms
  and shades, within five minutes for renames and moves.
- **Repair when rooms differ.** A shade first seen in a room of the board and
  in another area of Home Assistant is left alone on both sides, and a repair
  asks which side to keep.
- **Repair when the board is full.** An area that cannot become a room because
  the board already has its 16 rooms raises a repair instead of failing
  silently.
- **Groups as labels.** Each group of the board becomes a label on its member
  shades. Labels only go from the board to Home Assistant: joining a group
  takes a pairing on the motor.
- **Synchronise rooms and groups** option, on by default.
- **Radio health.** The radio statistics of the board (`/rfStats`) are read
  at startup and every five minutes. A shade with fewer repeats than its
  measured margin calls for (never fewer than 2) gets a repair that sets the
  advised value on the board. A guided measurement under 8 dB above the
  noise raises a warning: more repeats rarely save such a link.
- **Radio noise**, **Lost radio orders** and per shade **Radio margin**
  diagnostic sensors, on boards that publish radio statistics. The margin is
  measured on the remotes linked to a shade, so a shade without one gets no
  margin sensor; while it is unknown, its `unknown_reason` attribute says why
  (linked remote not heard yet, background noise not measured yet).
- **Repair for firmware 2.x and 3.x**, with a link to the browser installer
  of the ESPSomfy-RTS v4 firmware.
- **A fresh copy of each board in every Home Assistant backup**, unless the
  newest one is less than an hour old. A board that does not answer is
  logged and never makes the Home Assistant backup fail.
- **Shades and groups follow the board.** A shade or group added on the
  board reloads the integration, so it shows up by itself. A shade deleted
  on the board loses its device at once, and devices deleted on the board
  while Home Assistant was stopped are removed at startup (only from lists
  the board actually returned). A device still on the board can no longer
  be deleted by hand, since it would come back at the next reload.
- The board, each shade and each group link to the matching page of the
  board's web interface.

### Changed
- **New name: ESPSomfy-RTS Companion**, the Home Assistant integration of the
  ESPSomfy-RTS v4 firmware. The domain is now `espsomfy_rts_companion` and the
  repository is `Pulpyyyy/ESPSomfy-RTS-companion`. Actions move to
  `espsomfy_rts_companion.*`; entity ids and the `espsomfy-rts_event` events
  do not change (see *Coming from an earlier ESPSomfy-RTS integration* in the
  README).
- New icon, banner and README.

## 3.5.0

### Added
- **Connectivity** diagnostic binary sensor per device. It is `on` while the
  websocket is connected and the HTTP API answers a light probe (`GET /rooms`,
  5 s timeout, every 60 s; `/discovery` on firmware without `/rooms`), and
  turns `off` as soon as either fails. The entity itself stays available, its
  state carries the information. Attributes: `last_probe_ok`,
  `websocket_connected`, `ws_reconnects`. Transitions are logged once
  (WARNING when the device goes offline, INFO when it comes back), not every
  failed probe. No external Ping entry is needed any more to condition an
  automation on the device being reachable.
- **Last backup** diagnostic timestamp sensor, read from the newest `.backup`
  file on disk at startup and after each successful backup, with a
  `backup_count` attribute. Nothing extra is written, neither on the device
  nor on the host.
- **Number of backups to keep** option (1 to 50). Entries without the option
  keep 5 backups as before.

### Changed
- The `espsomfy_rts_enhanced.backup` service (and the Backup button) now fails
  with an error when the backup could not be written, or right away, without
  any request, when the Connectivity sensor is `off`. A failed backup is
  therefore visible in automation traces instead of reporting success.
- Old backups are only rotated after a new one has been written.
- The Backup button no longer turns unavailable when the websocket drops:
  Home Assistant skips unavailable entities in service calls, which made a
  backup of an offline device a silent no-op instead of an error.
