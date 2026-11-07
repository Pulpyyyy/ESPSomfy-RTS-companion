# Changelog

## 4.0.0

### Added
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
- The board, each shade and each group link to the matching page of the
  board's web interface.

### Changed
- **New name: ESPSomfy-RTS Companion**, the Home Assistant integration of the
  ESPSomfy-RTS v4 firmware. The domain is now `espsomfy_rts_companion` and the
  repository is `Pulpyyyy/ESPSomfy-RTS-companion`. Home Assistant sees it as a
  new integration: remove *ESPSomfy-RTS Enhanced*, install the Companion and
  add the board again (see *Coming from ESPSomfy-RTS Enhanced* in the README).
  Actions move from `espsomfy_rts_enhanced.*` to `espsomfy_rts_companion.*`;
  the `espsomfy-rts_event` events keep their name.
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
