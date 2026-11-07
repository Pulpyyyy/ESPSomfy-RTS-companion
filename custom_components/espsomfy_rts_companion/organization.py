"""Keep the board's rooms and groups in step with Home Assistant.

Rooms and areas are synchronised both ways. A room is only a label on the
board, so moving a shade to another area, or renaming an area, is written back
to the board, and the board's own changes come back to Home Assistant.

Groups only go from the board to Home Assistant, as labels on the member
shades: a group is a radio address learnt by each motor during a pairing, so a
label added in Home Assistant cannot make a motor join a group.

When a shade is seen for the first time in a room of the board and in another
area of Home Assistant, neither side is changed: a repair asks the user which
one to keep.

The board does not report room renames or room moves on its websocket, so its
side is read again when the integration starts, on the add and remove events
it does report, and every few minutes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
    label_registry as lr,
)
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store

from .const import DOMAIN, ROOM_NAME_MAX
from .cover import _linked_shade_ids

if TYPE_CHECKING:
    from .controller import ESPSomfyController

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
# Board events often come in bursts (a shade and its room): wait for the last.
REFRESH_DELAY = 2
ISSUE_ROOM_LIMIT = "room_limit"
ISSUE_CONFLICT = "organization_conflict"
RESOLVE_BOARD = "board"
RESOLVE_HOME_ASSISTANT = "home_assistant"


def room_name_for_board(name: str) -> str:
    """Return an area name as the board can store it.

    The board keeps 20 characters and turns commas into spaces (they separate
    the fields of its configuration file).
    """
    return name.replace(",", " ").strip()[:ROOM_NAME_MAX].strip()


class OrganizationSync:
    """Synchronise one board's rooms and groups with Home Assistant."""

    def __init__(self, hass: HomeAssistant, controller: ESPSomfyController) -> None:
        """Prepare the synchronisation; nothing runs before async_start()."""
        self.hass = hass
        self.controller = controller
        self.api = controller.api
        self._store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, f"{DOMAIN}.{controller.config_entry.entry_id}.organization"
        )
        # roomId -> area_id, groupId -> label_id, and the room each shade had
        # the last time both sides agreed (to tell which side changed).
        self._room_area: dict[str, str] = {}
        self._group_label: dict[str, str] = {}
        self._shade_room: dict[str, int] = {}
        self._unsubs: list[Callable[[], None]] = []
        self._lock = asyncio.Lock()
        # Devices and areas this module is changing right now: their registry
        # events are its own echo, not a user change.
        self._echo_devices: set[str] = set()
        self._echo_areas: set[str] = set()
        self._cancel_refresh: Callable[[], None] | None = None
        # Shades seen for the first time with a room on the board and another
        # area in Home Assistant: nothing is changed until the user chooses.
        self._conflicts: dict[str, tuple[str, int]] = {}

    async def async_start(self) -> None:
        """Load the saved state, align both sides and listen to changes."""
        saved = await self._store.async_load() or {}
        self._room_area = dict(saved.get("room_area", {}))
        self._group_label = dict(saved.get("group_label", {}))
        self._shade_room = {k: int(v) for k, v in saved.get("shade_room", {}).items()}
        # Shades and groups are loaded by the setup; rooms are not part of
        # /discovery once the board requires a login.
        await self.api.load_rooms()
        await self.async_refresh(reload=False)
        self._unsubs.append(
            self.hass.bus.async_listen(
                dr.EVENT_DEVICE_REGISTRY_UPDATED, self._on_device_updated
            )
        )
        self._unsubs.append(
            self.hass.bus.async_listen(ar.EVENT_AREA_REGISTRY_UPDATED, self._on_area_updated)
        )

    @callback
    def async_stop(self) -> None:
        """Stop listening."""
        while self._unsubs:
            self._unsubs.pop()()
        if self._cancel_refresh is not None:
            self._cancel_refresh()
            self._cancel_refresh = None

    @callback
    def schedule_refresh(self) -> None:
        """Read the board again shortly, once for a burst of events."""
        if self._cancel_refresh is not None:
            self._cancel_refresh()
        self._cancel_refresh = async_call_later(self.hass, REFRESH_DELAY, self._refresh_later)

    async def _refresh_later(self, _now: datetime) -> None:
        self._cancel_refresh = None
        await self.async_try_refresh()

    async def async_try_refresh(self) -> None:
        """Refresh, logging instead of raising when the board does not answer."""
        try:
            await self.async_refresh()
        except Exception as ex:  # noqa: BLE001
            _LOGGER.debug("ESPSomfy-RTS rooms and groups not refreshed: %s", ex)

    def _save(self) -> None:
        self._store.async_delay_save(
            lambda: {
                "room_area": self._room_area,
                "group_label": self._group_label,
                "shade_room": self._shade_room,
            },
            2,
        )

    # ------------------------------------------------------------------
    # Board -> Home Assistant
    # ------------------------------------------------------------------

    async def async_refresh(self, reload: bool = True) -> None:
        """Read the board again and apply its rooms and groups."""
        async with self._lock:
            if reload:
                await self.api.load_rooms()
                await self.api.load_shades()
                await self.api.load_groups()
            self._apply_rooms()
            self._apply_shade_rooms()
            self._apply_groups()
            self._save()

    def _apply_rooms(self) -> None:
        """Make sure every room has its area, named like it."""
        areas = ar.async_get(self.hass)
        rooms = self.api.rooms
        for room in rooms:
            room_id = str(room.get("roomId"))
            name = (room.get("name") or "").strip()
            if not name or room_id == "0":
                continue
            area = areas.async_get_area(self._room_area.get(room_id, ""))
            if area is None:
                area = areas.async_get_area_by_name(name) or areas.async_create(name)
                self._room_area[room_id] = area.id
            elif room_name_for_board(area.name) != name:
                # Renamed on the board: follow it.
                self._echo_areas.add(area.id)
                try:
                    areas.async_update(area.id, name=name)
                except ValueError:
                    # Another area already has that name: use it instead.
                    other = areas.async_get_area_by_name(name)
                    if other is not None:
                        self._room_area[room_id] = other.id
                finally:
                    self._echo_areas.discard(area.id)
        known = {str(room.get("roomId")) for room in rooms}
        for room_id in list(self._room_area):
            if room_id not in known:
                # Deleted on the board: forget the link, keep the area.
                del self._room_area[room_id]

    def _apply_shade_rooms(self) -> None:
        """Put each shade device in the area of its room when the board moved it."""
        devices = dr.async_get(self.hass)
        conflicts: dict[str, tuple[str, int]] = {}
        for shade in self.api.shades:
            shade_id = str(shade.get("shadeId"))
            room_id = int(shade.get("roomId") or 0)
            device = devices.async_get_device(identifiers={self._shade_identifier(shade_id)})
            if device is None:
                continue
            target = self._room_area.get(str(room_id)) if room_id else None
            previous = self._shade_room.get(shade_id)
            if device.area_id == target:
                self._shade_room[shade_id] = room_id
                continue
            if previous is None and device.area_id is not None:
                # First sight of this shade, with a room on the board and another
                # area in Home Assistant: the user picks the side to keep.
                conflicts[shade_id] = (device.area_id, room_id)
                continue
            if previous is not None and previous == room_id:
                # The board did not move it: the area was chosen in Home
                # Assistant. _on_device_updated writes such changes back; a
                # change made while the integration was stopped is sent now.
                self.hass.async_create_task(self._async_push_shade_area(shade_id, device.area_id))
                continue
            self._echo_devices.add(device.id)
            try:
                devices.async_update_device(device.id, area_id=target)
            finally:
                self._echo_devices.discard(device.id)
            self._shade_room[shade_id] = room_id
        self._conflicts = conflicts
        self._update_conflict_issue()

    def _update_conflict_issue(self) -> None:
        issue_id = f"{ISSUE_CONFLICT}_{self.controller.unique_id}"
        if not self._conflicts:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_CONFLICT,
            translation_placeholders={
                "device": self.controller.device_name,
                "count": str(len(self._conflicts)),
            },
            data={"entry_id": self.controller.config_entry.entry_id},
        )

    async def async_resolve_conflicts(self, keep: str) -> None:
        """Align the shades in conflict on the side the user chose to keep."""
        async with self._lock:
            devices = dr.async_get(self.hass)
            for shade_id, (area_id, room_id) in list(self._conflicts.items()):
                if keep == RESOLVE_HOME_ASSISTANT:
                    await self._push_shade_area(shade_id, area_id)
                    continue
                device = devices.async_get_device(identifiers={self._shade_identifier(shade_id)})
                if device is not None:
                    self._echo_devices.add(device.id)
                    try:
                        devices.async_update_device(
                            device.id, area_id=self._room_area.get(str(room_id)) if room_id else None
                        )
                    finally:
                        self._echo_devices.discard(device.id)
                self._shade_room[shade_id] = room_id
            self._conflicts = {}
            self._update_conflict_issue()
            self._save()

    def _apply_groups(self) -> None:
        """Mirror the board's groups as labels on their member shades."""
        labels = lr.async_get(self.hass)
        entities = er.async_get(self.hass)
        wanted: dict[str, set[str]] = {}  # entity_id -> labels it must carry
        known_groups: set[str] = set()
        for group in self.api.groups:
            group_id = str(group.get("groupId"))
            name = (group.get("name") or "").strip()
            if not name:
                continue
            known_groups.add(group_id)
            label = labels.async_get_label(self._group_label.get(group_id, ""))
            if label is None:
                label = labels.async_get_label_by_name(name) or labels.async_create(
                    name, icon="mdi:window-shutter-settings"
                )
                self._group_label[group_id] = label.label_id
            elif label.name != name:
                try:
                    labels.async_update(label.label_id, name=name)
                except ValueError:
                    pass
            for shade_id in _linked_shade_ids(group) or []:
                entity_id = entities.async_get_entity_id(
                    "cover", DOMAIN, f"{self.controller.unique_id}_{shade_id}"
                )
                if entity_id:
                    wanted.setdefault(entity_id, set()).add(label.label_id)
        # A group deleted on the board takes its label off the shades: the label
        # still counts as ours for this pass, otherwise it stayed on them forever.
        dropped = {
            label_id
            for group_id, label_id in self._group_label.items()
            if group_id not in known_groups
        }
        for group_id in list(self._group_label):
            if group_id not in known_groups:
                del self._group_label[group_id]
        ours = set(self._group_label.values()) | dropped
        for entry in er.async_entries_for_config_entry(
            entities, self.controller.config_entry.entry_id
        ):
            if entry.domain != "cover":
                continue
            keep = {lbl for lbl in entry.labels if lbl not in ours}
            new = keep | wanted.get(entry.entity_id, set())
            if new != set(entry.labels):
                entities.async_update_entity(entry.entity_id, labels=new)

    # ------------------------------------------------------------------
    # Home Assistant -> board
    # ------------------------------------------------------------------

    @callback
    def _on_device_updated(self, event: Event) -> None:
        if event.data.get("action") != "update" or "area_id" not in event.data.get("changes", {}):
            return
        device_id = event.data["device_id"]
        if device_id in self._echo_devices:
            return
        device = dr.async_get(self.hass).async_get(device_id)
        if device is None:
            return
        shade_id = self._shade_id_of(device)
        if shade_id is None:
            return
        self.hass.async_create_task(self._async_push_shade_area(shade_id, device.area_id))

    @callback
    def _on_area_updated(self, event: Event) -> None:
        if event.data.get("action") != "update":
            return
        area_id = event.data["area_id"]
        if area_id in self._echo_areas:
            return
        room_id = self._room_of_area(area_id)
        area = ar.async_get(self.hass).async_get_area(area_id)
        if room_id is None or area is None:
            return
        self.hass.async_create_task(self._async_rename_room(room_id, area.name))

    async def _async_push_shade_area(self, shade_id: str, area_id: str | None) -> None:
        """Move a shade to the room of its new area on the board."""
        async with self._lock:
            await self._push_shade_area(shade_id, area_id)
            if self._conflicts.pop(shade_id, None) is not None:
                self._update_conflict_issue()

    async def _push_shade_area(self, shade_id: str, area_id: str | None) -> None:
        """Write a shade's area to the board; the caller holds the lock."""
        room_id: int | None = 0
        if area_id:
            room_id = self._room_of_area(area_id) or await self._async_room_for_area(area_id)
            if room_id is None:
                return
        if await self.api.save_shade_room(int(shade_id), room_id) is not None:
            self._shade_room[shade_id] = room_id
            self._save()

    async def _async_room_for_area(self, area_id: str) -> int | None:
        """Find or create the board room that matches an area."""
        area = ar.async_get(self.hass).async_get_area(area_id)
        if area is None:
            return None
        name = room_name_for_board(area.name)
        for room in self.api.rooms:
            if (room.get("name") or "").strip().casefold() == name.casefold():
                self._room_area[str(room["roomId"])] = area_id
                return int(room["roomId"])
        room = await self.api.add_room(name)
        if room is None:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"{ISSUE_ROOM_LIMIT}_{self.controller.unique_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_ROOM_LIMIT,
                translation_placeholders={"device": self.controller.device_name, "area": area.name},
            )
            return None
        ir.async_delete_issue(self.hass, DOMAIN, f"{ISSUE_ROOM_LIMIT}_{self.controller.unique_id}")
        self._room_area[str(room["roomId"])] = area_id
        await self.api.load_rooms()
        return int(room["roomId"])

    async def _async_rename_room(self, room_id: int, area_name: str) -> None:
        """Rename the board room linked to a renamed area."""
        name = room_name_for_board(area_name)
        if not name:
            return
        async with self._lock:
            current = next(
                (r for r in self.api.rooms if int(r.get("roomId", -1)) == room_id), None
            )
            if current is not None and (current.get("name") or "").strip() == name:
                return
            if await self.api.save_room(room_id, name) is not None:
                await self.api.load_rooms()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _shade_identifier(self, shade_id: str) -> tuple[str, str]:
        return (DOMAIN, f"shade_{self.controller.unique_id}_{shade_id}")

    def _shade_id_of(self, device: dr.DeviceEntry) -> str | None:
        prefix = f"shade_{self.controller.unique_id}_"
        for domain, ident in device.identifiers:
            if domain == DOMAIN and ident.startswith(prefix):
                return ident[len(prefix) :]
        return None

    def _room_of_area(self, area_id: str) -> int | None:
        for room_id, linked in self._room_area.items():
            if linked == area_id:
                return int(room_id)
        return None
