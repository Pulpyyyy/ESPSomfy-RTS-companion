"""Provides device actions for ESPSomfy-RTS."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.device_automation import (
    async_validate_entity_schema,
    toggle_entity,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_DEVICE_ID,
    CONF_DOMAIN,
    CONF_ENTITY_ID,
    CONF_TYPE,
)
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import entity_registry as er
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType, TemplateVarsType

from .const import DOMAIN

# NOTE: l'action "restore" de l'amont rstrouse n'a jamais été terminée (schéma
# jamais enregistré, branche d'exécution commentée là-bas aussi) — retirée ici.

ONOFF_SCHEMA = toggle_entity.ACTION_SCHEMA.extend({vol.Required(CONF_DOMAIN): DOMAIN})

_ACTION_SCHEMA = cv.DEVICE_ACTION_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): vol.In({"Reboot", "Backup"}),
        vol.Required(CONF_ENTITY_ID): cv.entity_id_or_uuid,
    }
)


async def async_validate_action_config(
    hass: HomeAssistant, config: ConfigType
) -> ConfigType:
    """Validate config."""
    return async_validate_entity_schema(hass, config, _ACTION_SCHEMA)


async def async_get_actions(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, str]]:
    """List device actions for ESPSomfy-RTS devices."""
    actions = await toggle_entity.async_get_actions(hass, device_id, DOMAIN)
    registry = er.async_get(hass)
    for entry in er.async_entries_for_device(registry, device_id):
        # The unique id, not the entity id: the entity id follows the language
        # Home Assistant runs in (button.espsomfyrts_sauvegarder in French) and
        # whatever the user renames it to.
        if entry.domain != "button" or not entry.unique_id:
            continue
        action_type = None
        if entry.unique_id.startswith("reboot_"):
            action_type = "Reboot"
        elif entry.unique_id.startswith("backup_"):
            action_type = "Backup"
        if action_type is not None:
            actions.append(
                {
                    CONF_DEVICE_ID: device_id,
                    CONF_DOMAIN: DOMAIN,
                    CONF_ENTITY_ID: entry.entity_id,
                    CONF_TYPE: action_type,
                }
            )

    return actions


async def async_call_action_from_config(
    hass: HomeAssistant,
    config: ConfigType,
    variables: TemplateVarsType,
    context: Context | None,
) -> None:
    """Execute a device action."""
    if config[CONF_TYPE] == "Backup":
        await hass.services.async_call(
            DOMAIN,
            "backup",
            {
                ATTR_ENTITY_ID: config[CONF_ENTITY_ID],
            },
            blocking=True,
            context=context,
        )
    elif config[CONF_TYPE] == "Reboot":
        await hass.services.async_call(
            DOMAIN,
            "reboot",
            {
                ATTR_ENTITY_ID: config[CONF_ENTITY_ID],
            },
            blocking=True,
            context=context,
        )
    else:
        return await toggle_entity.async_call_action_from_config(
            hass, config, variables, context, DOMAIN
        )


async def async_get_action_capabilities(
    hass: HomeAssistant, config: ConfigType
) -> dict[str, vol.Schema]:
    """List action capabilities."""
    return {}
