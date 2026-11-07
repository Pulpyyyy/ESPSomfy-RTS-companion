"""Repairs offered by ESPSomfy-RTS Companion."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .health import ISSUE_REPEATS
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


class RepeatsFlow(RepairsFlow):
    """Raise the repeats of a shade to the advised value."""

    def __init__(self, issue_id: str, data: dict[str, Any]) -> None:
        """Remember the shade and the value to apply."""
        self._issue_id = issue_id
        self._entry_id = data.get("entry_id", "")
        self._shade_id = int(data.get("shade_id", 0))
        self._repeats = int(data.get("repeats", 0))

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Show what changes, then apply it."""
        if user_input is not None:
            entry = self.hass.config_entries.async_get_entry(self._entry_id)
            controller = getattr(entry, "runtime_data", None) if entry else None
            health = getattr(controller, "health", None)
            if health is None:
                return self.async_abort(reason="not_loaded")
            if not await health.async_apply_repeats(self._shade_id, self._repeats):
                return self.async_abort(reason="cannot_connect")
            return self.async_create_entry(data={})
        issue = ir.async_get(self.hass).async_get_issue(DOMAIN, self._issue_id)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({}),
            description_placeholders=(issue.translation_placeholders if issue else None) or {},
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    """Create the flow that fixes an issue of this integration."""
    data = data or {}
    if data.get("kind") == ISSUE_REPEATS:
        return RepeatsFlow(issue_id, data)
    return OrganizationConflictFlow(data.get("entry_id", ""))
