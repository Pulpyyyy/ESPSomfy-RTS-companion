"""Favorite (My) position of the shades.

Home Assistant covers have no favorite position, while it is the button a
Somfy remote is used for most. The button platform sends a shade there; this
number shows where it is and changes it. Somfy keeps the favorite in the
motor: setting it moves the shade to the new position, then stores it there,
as holding My on a remote does.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import EVT_CONNECTED, EVT_SHADESTATE
from .controller import ESPSomfyController
from .entity import ESPSomfyEntity

# Shade types with a position worth a favorite: rollers, blinds, curtains,
# awnings and shutters. Gates, garage doors and dry contacts are left out.
FAVORITE_SHADE_TYPES = (0, 1, 2, 3, 4, 7, 8)
AWNING = 3
TILT_ONLY = 3


def ha_position(board_position: int, flip: bool, shade_type: int) -> int:
    """A position the board displays, in the open percentage of Home Assistant.

    The same conversion as the cover entity; it is its own inverse.
    """
    awning = shade_type == AWNING
    if flip:
        return 100 - board_position if awning else board_position
    return board_position if awning else 100 - board_position


def has_favorite(shade: dict[str, Any]) -> bool:
    """Whether a shade gets a favorite position entity."""
    return (
        int(shade.get("shadeType", -1)) in FAVORITE_SHADE_TYPES
        and int(shade.get("tiltType", 0) or 0) != TILT_ONLY
    )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """One favorite position per shade that has a position."""
    controller: ESPSomfyController = config_entry.runtime_data
    async_add_entities(
        ESPSomfyMyPosition(controller, shade)
        for shade in controller.api.shades
        if "shadeId" in shade and has_favorite(shade)
    )


class ESPSomfyMyPosition(ESPSomfyEntity, NumberEntity):
    """The favorite position of a shade, as Home Assistant counts it (open %)."""

    _attr_has_entity_name = True
    _attr_translation_key = "my_position"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:star-outline"

    def __init__(self, controller: ESPSomfyController, shade: dict[str, Any]) -> None:
        """Initialize from the shade the board reported."""
        super().__init__(controller=controller, data=shade)
        self._controller = controller
        self._shade_id = int(shade["shadeId"])
        self._shade_type = int(shade.get("shadeType", 0))
        self._flip = bool(shade.get("flipPosition", False))
        self._attr_unique_id = f"my_position_{controller.unique_id}_{self._shade_id}"
        self._board_value = self._read(shade.get("myPos"))
        self._attr_available = True

    @staticmethod
    def _read(value: Any) -> int | None:
        try:
            position = int(value)
        except (TypeError, ValueError):
            return None
        return position if 0 <= position <= 100 else None

    @property
    def native_value(self) -> int | None:
        """The favorite in the open percentage, None when the motor has none."""
        if self._board_value is None:
            return None
        return ha_position(self._board_value, self._flip, self._shade_type)

    @property
    def available(self) -> bool:
        """Available while the board is connected."""
        return self._attr_available

    @callback
    def async_set_context(self, context: Context) -> None:
        """The shade moves for Home Assistant when the favorite changes."""
        super().async_set_context(context)
        self._controller.note_own_command([self._shade_id], context)

    async def async_set_native_value(self, value: float) -> None:
        """Move the shade to the new favorite and store it in the motor."""
        if self.native_value is not None and int(value) == self.native_value:
            # The board clears the favorite when asked for the one it holds.
            return
        target = ha_position(int(value), self._flip, self._shade_type)
        if await self._controller.api.set_my_position(self._shade_id, target) is None:
            raise HomeAssistantError(
                f"The board did not accept the favorite position of {self._data.get('name', self._shade_id)}"
            )

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
        if event != EVT_SHADESTATE or data.get("shadeId") != self._shade_id:
            return
        if "flipPosition" in data:
            self._flip = bool(data["flipPosition"])
        if "myPos" in data:
            value = self._read(data["myPos"])
            if value != self._board_value:
                self._board_value = value
                self.async_write_ha_state()
