"""Event entities for ESPSomfy-RTS Companion.

One entity per physical remote, on a device of its own, so a remote press is a
selectable thing in automations, with a name, a room and a history, instead of
a raw address. Two kinds of remotes get one:

- the remotes linked to a shade on the board; a remote linked to several shades
  stays a single entity, the shades listed in its `linked_shades` attribute;
- the remotes adopted from Home Assistant ("Add remote" on the integration
  page): a spare remote that drives nothing on the board becomes a scene
  switch. Each lives in a subentry, removed with it.

A board that streams the button presses (firmware 4.3, `remoteEvents`) tells
when a button is pressed and when it is released, so the up, down and My
buttons also report a short or a long press. Older firmware only reports the
commands of linked remotes, as the shades see them; one press then fans out to
every shade the remote drives and the entity collapses that to a single event.
"""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import (
    COMMANDS,
    CONF_ADDRESS,
    DOMAIN,
    EVENT_REMOTE,
    EVT_CONNECTED,
    EVT_REMOTEHEARD,
    EVT_SHADECOMMAND,
    HOLD_COMMANDS,
    LONG_PRESS_SECONDS,
    MANUFACTURER,
    REMOTE_NAME_PREFIX,
    SUBENTRY_REMOTE,
)
from .controller import ESPSomfyController
from .entity import ESPSomfyEntity, board_link

EVENT_TYPES = sorted(
    {
        *COMMANDS.values(),
        "unknown",
        *(f"{command}_short" for command in HOLD_COMMANDS),
        *(f"{command}_long" for command in HOLD_COMMANDS),
    }
)

# One press reaches every shade the remote drives, as many near simultaneous
# events. Collapse the ones sharing a command within this window into one.
DEDUP_WINDOW = 0.5


def remote_device_identifier(controller: ESPSomfyController, address: int) -> str:
    """Device registry identifier of a remote."""
    return f"remote_{controller.unique_id}_{address}"


def linked_remotes(controller: ESPSomfyController) -> dict[int, dict[str, Any]]:
    """Every remote linked to a shade: its first shade, slot and every shade.

    Discovery order is the shade order the board returns.
    """
    remotes: dict[int, dict[str, Any]] = {}
    for shade in controller.api.shades:
        if "shadeId" not in shade:
            continue
        name = shade.get("name") or f"Shade {shade['shadeId']}"
        for slot, remote in enumerate(shade.get("linkedRemotes") or []):
            address = int(remote.get("remoteAddress", 0) or 0)
            if not address:
                continue
            if address in remotes:
                remotes[address]["shades"].append(name)
            else:
                remotes[address] = {
                    "shade": shade,
                    "slot": slot,
                    "count": len(shade.get("linkedRemotes") or []),
                    "shades": [name],
                }
    return remotes


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one event entity per linked or adopted remote."""
    controller: ESPSomfyController = config_entry.runtime_data
    linked = linked_remotes(controller)
    lang = (hass.config.language or "en").split("-")[0]
    prefix = REMOTE_NAME_PREFIX.get(lang, REMOTE_NAME_PREFIX["en"])

    # An adopted remote keeps its subentry even once linked on the board, so
    # removing the subentry still takes it away.
    adopted: set[int] = set()
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_REMOTE:
            continue
        address = int(subentry.data[CONF_ADDRESS])
        adopted.add(address)
        info = linked.get(address)
        async_add_entities(
            [
                ESPSomfyRemoteEvent(
                    controller,
                    address,
                    name=subentry.title,
                    shades=info["shades"] if info else [],
                    room_id=info["shade"].get("roomId") if info else None,
                )
            ],
            config_subentry_id=subentry.subentry_id,
        )

    entities = []
    for address, info in linked.items():
        if address in adopted:
            continue
        name = f"{prefix} {info['shades'][0]}"
        if info["count"] > 1:
            name = f"{name} #{info['slot'] + 1}"
        entities.append(
            ESPSomfyRemoteEvent(
                controller,
                address,
                name=name,
                shades=info["shades"],
                room_id=info["shade"].get("roomId"),
            )
        )
    async_add_entities(entities)


class ESPSomfyRemoteEvent(ESPSomfyEntity, EventEntity):
    """A physical remote; fires when the board hears one of its buttons."""

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = EVENT_TYPES
    _attr_has_entity_name = True
    # The remote is the device: the entity takes its name. The key only
    # translates the event types.
    _attr_name = None
    _attr_translation_key = "remote"

    def __init__(
        self,
        controller: ESPSomfyController,
        address: int,
        *,
        name: str,
        shades: list[str],
        room_id: int | None,
    ) -> None:
        """Initialize the event entity on its remote's device."""
        super().__init__(controller=controller, data=None)
        self._controller = controller
        self._address = address
        self._device_name = name
        self._shades = shades
        self._room_id = room_id
        self._attr_unique_id = f"remote_{controller.unique_id}_{address}"
        self._attr_available = True
        self._rssi: int | None = None
        self._last: tuple[str, float] | None = None
        # The button held down, whether its long press already fired, and the
        # timer that fires it.
        self._held: str | None = None
        self._long_fired = False
        self._cancel_long: CALLBACK_TYPE | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """A device of its own, under the board, renamable in Home Assistant."""
        return DeviceInfo(
            identifiers={(DOMAIN, remote_device_identifier(self._controller, self._address))},
            name=self._device_name,
            manufacturer=MANUFACTURER,
            model="RTS remote",
            **board_link(self._controller),
            suggested_area=self._controller.room_name(self._room_id),
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The remote address, the shades it drives and how well it is heard."""
        attrs: dict[str, Any] = {
            "remote_address": self._address,
            "linked_shades": self._shades,
        }
        if self._rssi is not None:
            attrs["rssi"] = self._rssi
        return attrs

    @property
    def available(self) -> bool:
        """Available while the board is connected."""
        return self._attr_available

    async def async_will_remove_from_hass(self) -> None:
        """Drop a pending long press timer."""
        self._stop_long_timer()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        if not self.enabled:
            return
        data = self._controller.data
        event = data.get("event")
        if event == EVT_CONNECTED and "connected" in data:
            if self._attr_available != bool(data["connected"]):
                self._attr_available = bool(data["connected"])
                if not self._attr_available:
                    # A release lost with the connection must not fire a
                    # long press later.
                    self._stop_long_timer()
                    self._held = None
                self.async_write_ha_state()
            return
        if event == EVT_REMOTEHEARD:
            if int(data.get("address", 0) or 0) == self._address:
                self._handle_heard(data)
            return
        if (
            event == EVT_SHADECOMMAND
            and not self._controller.api.remote_events
            and data.get("source") == "remote"
            and int(data.get("sourceAddress", 0) or 0) == self._address
        ):
            self._handle_legacy_command(data)

    @callback
    def _handle_heard(self, data: dict[str, Any]) -> None:
        """A press or a release reported by the board."""
        raw = data.get("cmd", "") or ""
        command = COMMANDS.get(raw, "unknown")
        if "rssi" in data:
            self._rssi = int(data["rssi"])
        if data.get("phase") == "press":
            self._stop_long_timer()
            self._held = command
            self._long_fired = False
            self._fire(command, raw)
            if command in HOLD_COMMANDS:
                self._cancel_long = async_call_later(
                    self.hass, LONG_PRESS_SECONDS, self._long_press_reached
                )
            return
        if data.get("phase") != "release" or self._held != command:
            return
        self._stop_long_timer()
        self._held = None
        if command in HOLD_COMMANDS and not self._long_fired:
            # The board measured the hold; it decides when the timer could
            # not, Home Assistant being busy when it should have fired.
            held = int(data.get("durationMs", 0) or 0) / 1000
            suffix = "long" if held >= LONG_PRESS_SECONDS else "short"
            self._fire(f"{command}_{suffix}", raw)

    @callback
    def _long_press_reached(self, _now: Any) -> None:
        """Still held after the threshold: a long press, fired while held."""
        self._cancel_long = None
        if self._held in HOLD_COMMANDS and not self._long_fired:
            self._long_fired = True
            self._fire(f"{self._held}_long", next(
                (raw for raw, norm in COMMANDS.items() if norm == self._held), ""
            ))

    @callback
    def _stop_long_timer(self) -> None:
        if self._cancel_long is not None:
            self._cancel_long()
            self._cancel_long = None

    @callback
    def _handle_legacy_command(self, data: dict[str, Any]) -> None:
        """A linked remote's command as a shade reported it (older firmware)."""
        command = data.get("cmd", "") or ""
        now = time.monotonic()
        # The fan-out of one press shares the command and lands within the
        # window; fire on the first, drop the rest. A real second press is a
        # new frame the firmware only emits after its repeat window, so it
        # falls outside and fires again.
        if self._last and self._last[0] == command and now - self._last[1] < DEDUP_WINDOW:
            return
        self._last = (command, now)
        self._fire(COMMANDS.get(command, "unknown"), command)

    @callback
    def _fire(self, event_type: str, raw: str) -> None:
        """Fire the entity event and the bus event the device triggers read."""
        self._trigger_event(
            event_type, {"command": raw, "remote_address": self._address}
        )
        self.async_write_ha_state()
        device_id = self.registry_entry.device_id if self.registry_entry else None
        self.hass.bus.async_fire(
            EVENT_REMOTE,
            {
                "device_id": device_id,
                "entity_id": self.entity_id,
                "remote_address": self._address,
                "type": event_type,
                "command": raw,
            },
        )
