# Changelog

## 4.5.0

### Changed
- **A group shows what it moves.** Its class follows its members: a group
  that holds a gate or a garage door is a gate or a garage door for Home
  Assistant, so voice assistants ask before opening it, as they do for the
  device itself; otherwise it takes the class of its most numerous
  covering. A `make_up` attribute counts the members of each kind
  (`{"shutter": 4, "gate": 1}`).

- **Each remote is a device of its own**, under the board, named after its
  shade and renamable. A remote linked to several shades was only shown on
  the first one. Its event entity, its id and its history stay the same.
- **Commands sent by Home Assistant say so.** The board reports them as
  `internal`, like the ones from its own web page. The command event, the
  `cmd_source` attribute and the triggers now give `home_assistant` for
  those, and the event carries the context of the call, so the logbook
  shows which automation or user moved the shade. A shade Home Assistant
  set moving stays credited to it until it stops; a remote press takes it
  back. Automations that filtered on `internal` to catch Home Assistant's
  own commands must use `home_assistant` instead.

### Added
- **A repair warns about a group that mixes window coverings with a gate or
  a garage door**: one command moves them all.
- **Spare remotes become scene switches** (firmware 4.3.0). "Add remote" on the
  integration page listens for 30 seconds: press a button of a remote the
  board drives nothing with, name it, and it becomes a device with one
  trigger per button. Removing it from the integration page removes it.
- **Short and long presses** (firmware 4.3.0). The board now reports when a
  button is pressed and when it is released: up, down and My also fire
  `up_short` / `up_long` and so on, the long press as soon as the button is
  held for a second. On a remote device, each one is a device trigger.
- **Device triggers per button** on remote devices ("Up pressed", "My held
  down"...), and the shade trigger can be narrowed to one command and picks
  the remote by name instead of a number.
- **"Once per press"** for the integration trigger: a remote that drives
  several shades reports a press for each, the automation can run once.
- **"Go to favorite position"** button per shade and group, and a
  **"Favorite position"** setting per shade: setting it moves the shade there
  and stores it in the motor, as holding My on the remote does.
- **"Last start"** diagnostic sensor with the reason of the restart, and a
  repair when the board restarted after a crash or a watchdog (firmware 4.3.0).
- **A repair when the board also publishes its shades over MQTT discovery**,
  which shows every shade twice in Home Assistant (firmware 4.3.0).

### Fixed
- **The Restart and Backup device actions were missing** outside English:
  they were found by the end of the entity id, which follows the language
  of Home Assistant (`button.espsomfyrts_sauvegarder`).
- **"Check for updates" in Settings > Updates now asks the board.** It did
  nothing for the firmware entity, which only learned about a new release at
  the board's daily check. The board now fetches its releases from GitHub
  right away (not while a shade moves).
- **Ready for Home Assistant 2027.8.** Home Assistant 2026.10 deprecated
  two ways of reaching the device registry that stop working in 2027.8: a
  device placed under the board by its identifier (`via_device`), and
  `async_get_device`. The integration logged a warning for both on every
  start; it now uses `via_device_id` and `async_get_device_by_identifier`.

## 4.4.1

### Fixed
- **Restoring a backup from Home Assistant works.** The restore service sent
  the backup to the board's API port, which has no restore route, so it
  always failed. It now uses the web port and passes the chosen sections
  where the firmware reads them (passed the old way, only the shades would
  have been restored). Works with every firmware since v4.0.0.
- **Accented area names no longer multiply rooms on the board.** The board
  keeps 20 bytes per room name and an accented letter takes two. Names are
  now cut to that, on a whole letter, so the sync finds its room again
  instead of creating a new one each time, and no longer renames the area
  after the board's shorter name.
- **Two areas that only differ after their first 20 bytes no longer share a
  room**, which moved the shades of one into the other: a repair asks to
  rename one of them.

## 4.4.0

### Changed
- **Taking over an earlier ESPSomfy-RTS integration is now an explicit,
  confirmed step.** When you add a board that is already set up under an
  earlier ESPSomfy-RTS integration, the setup asks whether to move its
  entities and devices here (keeping their ids, areas and history) and
  remove the old integration. Nothing is touched unless you confirm; decline
  to add the board fresh. The credentials are no longer read from the other
  integration, the setup form asks for them.

### Fixed
- **Diagnostics no longer expose radio addresses.** Groups are now redacted
  like shades, so the group address and the addresses inside their linked
  shades stay out of the download.

## 4.3.1

### Changed
- **Relicensed under the MIT License**, so the integration can be listed in
  the default HACS catalog.

## 4.3.0

### Added
- **A remote is now an entity.** Each remote linked to a shade becomes an
  `event` entity on that shade's device, named by its slot (`Remote #1`,
  `#2`, ...), so you can select it in an automation, rename it and keep its
  history. A shade with several remotes shows several of them; a remote
  shared by several shades stays one entity, the others in its
  `linked_shades` attribute. It fires once per press (the command fans out
  to every shade the remote drives, but the entity collapses that), with the
  command as the event type.

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
