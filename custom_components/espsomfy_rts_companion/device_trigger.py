"""Device triggers for ESPSomfy-RTS Companion.

A shade fires `espsomfy-rts_event` whenever the board sees a command for it,
including the ones sent from a physical remote. This exposes that as a device
trigger, so an automation can start on "this shade received a command" and
read the command, its type, slot, source and the remote from the trigger data.
An optional filter narrows it to a source (a physical remote, a group or the
board) or to one remote address.
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
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, EVENT_SHADE_COMMAND
from .cover import EVT_SHADECOMMAND

TRIGGER_COMMAND = "command_received"
TRIGGER_TYPES = {TRIGGER_COMMAND}

CONF_SOURCE = "source"
CONF_REMOTE_ADDRESS = "remote_address"
SOURCES = ["remote", "group", "internal"]

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_ENTITY_ID): cv.entity_id_or_uuid,
        vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES),
        vol.Optional(CONF_SOURCE): vol.In(SOURCES),
        vol.Optional(CONF_REMOTE_ADDRESS): cv.positive_int,
    }
)


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, str]]:
    """List the triggers of a shade device, one per cover entity."""
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


async def async_get_trigger_capabilities(
    hass: HomeAssistant, config: ConfigType
) -> dict[str, vol.Schema]:
    """The optional source and remote address filters shown in the editor."""
    return {
        "extra_fields": vol.Schema(
            {
                vol.Optional(CONF_SOURCE): vol.In(SOURCES),
                vol.Optional(CONF_REMOTE_ADDRESS): cv.positive_int,
            }
        )
    }


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach a trigger: an event trigger filtered to this shade's commands."""
    registry = er.async_get(hass)
    entity_id = (
        er.async_resolve_entity_id(registry, config[CONF_ENTITY_ID])
        or config[CONF_ENTITY_ID]
    )
    event_data: dict[str, object] = {
        "entity_id": entity_id,
        "event_key": EVT_SHADECOMMAND,
    }
    if CONF_SOURCE in config:
        event_data["source"] = config[CONF_SOURCE]
    if CONF_REMOTE_ADDRESS in config:
        event_data["source_address"] = config[CONF_REMOTE_ADDRESS]
    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: EVENT_SHADE_COMMAND,
            event_trigger.CONF_EVENT_DATA: event_data,
        }
    )
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )
