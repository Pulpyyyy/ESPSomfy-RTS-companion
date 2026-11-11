"""Integration trigger: a shade received a command.

Unlike the per shade device trigger, this one takes an optional target (shades,
areas or labels, or nothing for every shade, present and future) and optional
filters on the command, the source and the remote, and starts an automation
from the board's command events without naming an entity. It reads the same
enriched `espsomfy-rts_event` the covers fire, so the action gets the command,
its type, slot, source and remote.

One press of a remote reaches every shade it drives, each reporting it: with
`once_per_press`, the automation runs once for the press, not once per shade.
"""

from __future__ import annotations

import time

import voluptuous as vol

from homeassistant.const import CONF_OPTIONS
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.target import (
    TargetSelection,
    async_extract_referenced_entity_ids,
)
from homeassistant.helpers.trigger import (
    Trigger,
    TriggerActionRunner,
    TriggerConfig,
    TriggerNotTriggeredReporter,
)
from homeassistant.helpers.typing import ConfigType

from .const import COMMAND_SOURCES, COMMANDS, EVENT_SHADE_COMMAND, EVT_SHADECOMMAND

CONF_SOURCE = "source"
CONF_COMMAND = "command"
CONF_REMOTE_ADDRESS = "remote_address"
CONF_ONCE_PER_PRESS = "once_per_press"
COMMAND_CHOICES = sorted(set(COMMANDS.values()))
# The shades of one press report it within this window.
PRESS_WINDOW = 0.5

_OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_SOURCE): vol.In(COMMAND_SOURCES),
        vol.Optional(CONF_COMMAND): vol.In(COMMAND_CHOICES),
        vol.Optional(CONF_REMOTE_ADDRESS): cv.positive_int,
        vol.Optional(CONF_ONCE_PER_PRESS, default=False): cv.boolean,
    }
)


class CommandReceivedTrigger(Trigger):
    """Fires when the board reports a command for a targeted shade."""

    @classmethod
    async def async_validate_config(
        cls, hass: HomeAssistant, config: ConfigType
    ) -> ConfigType:
        """Validate the options; the base already validated the target."""
        if config.get(CONF_OPTIONS) is not None:
            config[CONF_OPTIONS] = _OPTIONS_SCHEMA(config[CONF_OPTIONS])
        return config

    def __init__(self, hass: HomeAssistant, config: TriggerConfig) -> None:
        """Initialize the trigger from its target and options."""
        super().__init__(hass, config)
        self._hass = hass
        self._target = config.target
        options = config.options or {}
        self._source = options.get(CONF_SOURCE)
        self._command = options.get(CONF_COMMAND)
        self._remote_address = options.get(CONF_REMOTE_ADDRESS)
        self._once_per_press = bool(options.get(CONF_ONCE_PER_PRESS, False))

    async def async_attach_runner(
        self,
        run_action: TriggerActionRunner,
        did_not_trigger: TriggerNotTriggeredReporter | None = None,
    ) -> CALLBACK_TYPE:
        """Listen for command events and run the action on a match."""
        # A target is resolved once, here. Without one, every shade matches,
        # including shades added later.
        entity_ids: set[str] | None = None
        if self._target:
            selection = TargetSelection(self._target)
            if selection.has_any_target:
                selected = async_extract_referenced_entity_ids(self._hass, selection)
                entity_ids = selected.referenced | selected.indirectly_referenced
        last_press: dict[tuple, float] = {}

        @callback
        def handle_event(event: Event) -> None:
            data = event.data
            if data.get("event_key") != EVT_SHADECOMMAND:
                return
            if entity_ids is not None and data.get("entity_id") not in entity_ids:
                return
            if self._source is not None and data.get("source") != self._source:
                return
            if (
                self._command is not None
                and COMMANDS.get(data.get("command", "")) != self._command
            ):
                return
            if (
                self._remote_address is not None
                and data.get("source_address") != self._remote_address
            ):
                return
            if self._once_per_press:
                key = (data.get("source"), data.get("source_address"), data.get("command"))
                now = time.monotonic()
                if now - last_press.get(key, -PRESS_WINDOW) < PRESS_WINDOW:
                    return
                last_press.clear()
                last_press[key] = now
            run_action({"event": event}, "command received", event.context)

        return self._hass.bus.async_listen(EVENT_SHADE_COMMAND, handle_event)


async def async_get_triggers(hass: HomeAssistant) -> dict[str, type[Trigger]]:
    """Return the integration triggers."""
    return {"command_received": CommandReceivedTrigger}
