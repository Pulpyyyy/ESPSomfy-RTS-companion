"""Device triggers for ESPSomfy-RTS Companion.

Two kinds of devices carry triggers:

- a shade: "received a command", whenever the board sees a command for it,
  including the ones sent from a physical remote, with optional filters on the
  command, the source (a remote, a group, the board, Home Assistant) and the
  remote, picked by name among the remotes linked to the shade;
- a remote: one trigger per button, "Up pressed", "My held down"..., the way
  remotes show up from other integrations.
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_DOMAIN,
    CONF_ENTITY_ID,
    CONF_PLATFORM,
    CONF_TYPE,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import (
    COMMAND_SOURCES,
    COMMANDS,
    DOMAIN,
    EVENT_REMOTE,
    EVENT_SHADE_COMMAND,
    EVT_SHADECOMMAND,
    HOLD_COMMANDS,
    REMOTE_NAME_PREFIX,
)

TRIGGER_COMMAND = "command_received"
# The buttons of a remote, as event types of its entity (see event.py).
REMOTE_PRESS_TYPES = ["up", "down", "my", "my_up", "my_down", "up_down", "prog"]
REMOTE_HOLD_TYPES = [
    f"{command}_{kind}" for command in HOLD_COMMANDS for kind in ("short", "long")
]
TRIGGER_TYPES = {TRIGGER_COMMAND, *REMOTE_PRESS_TYPES, *REMOTE_HOLD_TYPES}

CONF_SOURCE = "source"
CONF_COMMAND = "command"
CONF_REMOTE_ADDRESS = "remote_address"
# Filter values: the normalized commands, board spelling looked up on attach.
COMMAND_CHOICES = sorted(set(COMMANDS.values()))
_RAW_COMMANDS = {norm: raw for raw, norm in COMMANDS.items()}

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Optional(CONF_ENTITY_ID): cv.entity_id_or_uuid,
        vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES),
        vol.Optional(CONF_SOURCE): vol.In(COMMAND_SOURCES),
        vol.Optional(CONF_COMMAND): vol.In(COMMAND_CHOICES),
        vol.Optional(CONF_REMOTE_ADDRESS): cv.positive_int,
    }
)


def _is_remote_device(device: dr.DeviceEntry | None) -> bool:
    return device is not None and any(
        domain == DOMAIN and identifier.startswith("remote_")
        for domain, identifier in device.identifiers
    )


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, str]]:
    """List the triggers of a shade (one per cover) or of a remote (one per button)."""
    device = dr.async_get(hass).async_get(device_id)
    if _is_remote_device(device):
        types = list(REMOTE_PRESS_TYPES)
        if _board_streams_presses(hass, device):
            types += REMOTE_HOLD_TYPES
        return [
            {
                CONF_PLATFORM: "device",
                CONF_DEVICE_ID: device_id,
                CONF_DOMAIN: DOMAIN,
                CONF_TYPE: trigger_type,
            }
            for trigger_type in types
        ]
    registry = er.async_get(hass)
    triggers: list[dict[str, str]] = []
    for entry in er.async_entries_for_device(registry, device_id):
        if entry.domain != "cover":
            continue
        triggers.append(
            {
                CONF_PLATFORM: "device",
                CONF_DEVICE_ID: device_id,
                CONF_DOMAIN: DOMAIN,
                CONF_ENTITY_ID: entry.id,
                CONF_TYPE: TRIGGER_COMMAND,
            }
        )
    return triggers


def _board_streams_presses(hass: HomeAssistant, device: dr.DeviceEntry) -> bool:
    """Whether the board of this device reports presses and releases."""
    # config_entry_id since Home Assistant 2026.10, config_entries before.
    entry_ids = (
        [device.config_entry_id]
        if getattr(device, "config_entry_id", None)
        else list(device.config_entries)
    )
    for entry_id in entry_ids:
        entry = hass.config_entries.async_get_entry(entry_id)
        controller = getattr(entry, "runtime_data", None) if entry else None
        if controller is not None and controller.api.remote_events:
            return True
    return False


def _remote_choices(hass: HomeAssistant, entity_ref: str) -> dict[int, str]:
    """The remotes linked to the shade of a cover entity, by name."""
    registry = er.async_get(hass)
    entity_id = er.async_resolve_entity_id(registry, entity_ref) or entity_ref
    entry = registry.async_get(entity_id)
    if entry is None or entry.config_entry_id is None:
        return {}
    config_entry = hass.config_entries.async_get_entry(entry.config_entry_id)
    controller = getattr(config_entry, "runtime_data", None) if config_entry else None
    if controller is None:
        return {}
    lang = (hass.config.language or "en").split("-")[0]
    prefix = REMOTE_NAME_PREFIX.get(lang, REMOTE_NAME_PREFIX["en"])
    for shade in controller.api.shades:
        if f"{controller.unique_id}_{shade.get('shadeId')}" != entry.unique_id:
            continue
        name = shade.get("name") or ""
        choices: dict[int, str] = {}
        for slot, remote in enumerate(shade.get("linkedRemotes") or []):
            address = int(remote.get("remoteAddress", 0) or 0)
            if address:
                choices[address] = f"{prefix} {name} #{slot + 1} ({address})"
        return choices
    return {}


async def async_get_trigger_capabilities(
    hass: HomeAssistant, config: ConfigType
) -> dict[str, vol.Schema]:
    """The optional filters of a shade trigger; a remote button has none."""
    if config[CONF_TYPE] != TRIGGER_COMMAND:
        return {}
    remotes = _remote_choices(hass, config.get(CONF_ENTITY_ID, ""))
    return {
        "extra_fields": vol.Schema(
            {
                vol.Optional(CONF_COMMAND): vol.In(COMMAND_CHOICES),
                vol.Optional(CONF_SOURCE): vol.In(COMMAND_SOURCES),
                vol.Optional(CONF_REMOTE_ADDRESS): (
                    vol.In(remotes) if remotes else cv.positive_int
                ),
            }
        )
    }


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach a trigger: an event trigger on the shade's commands or the remote's buttons."""
    if config[CONF_TYPE] != TRIGGER_COMMAND:
        event_type = EVENT_REMOTE
        event_data: dict[str, object] = {
            "device_id": config[CONF_DEVICE_ID],
            "type": config[CONF_TYPE],
        }
    else:
        registry = er.async_get(hass)
        entity_id = (
            er.async_resolve_entity_id(registry, config[CONF_ENTITY_ID])
            or config[CONF_ENTITY_ID]
        )
        event_type = EVENT_SHADE_COMMAND
        event_data = {"entity_id": entity_id, "event_key": EVT_SHADECOMMAND}
        if CONF_SOURCE in config:
            event_data["source"] = config[CONF_SOURCE]
        if CONF_COMMAND in config:
            event_data["command"] = _RAW_COMMANDS[config[CONF_COMMAND]]
        if CONF_REMOTE_ADDRESS in config:
            event_data["source_address"] = config[CONF_REMOTE_ADDRESS]
    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: event_type,
            event_trigger.CONF_EVENT_DATA: event_data,
        }
    )
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )
