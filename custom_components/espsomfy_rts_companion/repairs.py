"""Repairs offered by ESPSomfy-RTS Companion."""

from __future__ import annotations

from typing import Any

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant

from .organization import RESOLVE_BOARD, RESOLVE_HOME_ASSISTANT


class OrganizationConflictFlow(RepairsFlow):
    """Choose which side wins when rooms and areas disagree."""

    def __init__(self, entry_id: str) -> None:
        """Remember the board the issue belongs to."""
        self._entry_id = entry_id

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Offer both directions."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[RESOLVE_BOARD, RESOLVE_HOME_ASSISTANT],
        )

    async def async_step_board(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Keep the rooms of the board."""
        return await self._resolve(RESOLVE_BOARD)

    async def async_step_home_assistant(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Keep the areas of Home Assistant."""
        return await self._resolve(RESOLVE_HOME_ASSISTANT)

    async def _resolve(self, keep: str) -> data_entry_flow.FlowResult:
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        controller = getattr(entry, "runtime_data", None) if entry else None
        organization = getattr(controller, "organization", None)
        if organization is None:
            return self.async_abort(reason="not_loaded")
        await organization.async_resolve_conflicts(keep)
        return self.async_create_entry(data={})


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    """Create the flow that fixes an issue of this integration."""
    return OrganizationConflictFlow((data or {}).get("entry_id", ""))
