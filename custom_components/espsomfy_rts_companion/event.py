"""Event entities for ESPSomfy-RTS Companion.

One entity per physical remote linked to a shade, so a remote press is a
selectable thing in automations, with a name and history, instead of a raw
address. The entity lives on its shade's device and its name carries the slot
(`Remote #1`, `#2`, ...), so a shade with several remotes shows several of them.
A remote linked to several shades stays a single entity, on the first shade,
the others listed in its `linked_shades` attribute. One press fans out to every
shade the remote drives; the entity collapses that to a single event.
"""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import EVT_CONNECTED, EVT_SHADECOMMAND
from .controller import ESPSomfyController
from .entity import ESPSomfyEntity

# Commands the board reports (translateSomfyCommand), normalized to event types.
_COMMANDS = {
    "Up": "up",
    "Down": "down",
    "My": "my",
    "My+Up": "my_up",
    "Up+Down": "up_down",
    "My+Down": "my_down",
    "My+Up+Down": "my_up_down",
    "Prog": "prog",
    "Sun Flag": "sun_flag",
    "Flag": "flag",
    "Step Up": "step_up",
    "Step Down": "step_down",
    "Sensor": "sensor",
    "Toggle": "toggle",
    "Favorite": "favorite",
    "Stop": "stop",
}
EVENT_TYPES = sorted({*_COMMANDS.values(), "unknown"})

# One press reaches every shade the remote drives, as many near simultaneous
# events. Collapse the ones sharing a command within this window into one.
DEDUP_WINDOW = 0.5


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one event entity per linked remote."""
    controller: ESPSomfyController = config_entry.runtime_data
    # address -> the first shade it is linked to, its slot there, and every
    # shade it drives. Discovery order is the shade order the board returns.
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
                remotes[address] = {"shade": shade, "slot": slot, "shades": [name]}

    async_add_entities(
        ESPSomfyRemoteEvent(controller, info, address)
        for address, info in remotes.items()
    )


class ESPSomfyRemoteEvent(ESPSomfyEntity, EventEntity):
    """A remote linked to a shade; fires when the board hears it."""

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = EVENT_TYPES

    def __init__(
        self, controller: ESPSomfyController, info: dict[str, Any], address: int
    ) -> None:
        """Initialize the event entity on its shade's device."""
        super().__init__(controller=controller, data=info["shade"])
        self._controller = controller
        self._address = address
        self._shades = info["shades"]
        self._attr_unique_id = f"remote_{controller.unique_id}_{address}"
        self._attr_has_entity_name = True
        self._attr_translation_key = "remote"
        self._attr_translation_placeholders = {"slot": str(info["slot"] + 1)}
        self._attr_available = True
        self._last: tuple[str, float] | None = None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The remote address and every shade it drives."""
        return {"remote_address": self._address, "linked_shades": self._shades}

    @property
    def available(self) -> bool:
        """Available while the board is connected."""
        return self._attr_available

    @callback
    def _handle_coordinator_update(self) -> None:
        if not self.enabled:
            return
        data = self._controller.data
        event = data.get("event")
        if event == EVT_CONNECTED and "connected" in data:
            if self._attr_available != bool(data["connected"]):
                self._attr_available = bool(data["connected"])
                self.async_write_ha_state()
            return
        if (
            event != EVT_SHADECOMMAND
            or data.get("source") != "remote"
            or int(data.get("sourceAddress", 0) or 0) != self._address
        ):
            return
        command = data.get("cmd", "") or ""
        now = time.monotonic()
        # The fan-out of one press shares the command and lands within the
        # window; fire on the first, drop the rest. A real second press is a
        # new frame the firmware only emits after its repeat window, so it
        # falls outside and fires again.
        if self._last and self._last[0] == command and now - self._last[1] < DEDUP_WINDOW:
            return
        self._last = (command, now)
        self._trigger_event(
            _COMMANDS.get(command, "unknown"),
            {"command": command, "remote_address": self._address},
        )
        self.async_write_ha_state()
