"""Take over a board's entities and devices from an earlier ESPSomfy-RTS integration.

ESPSomfy-RTS Companion carries on the earlier ESPSomfy-RTS integrations under a
new domain. Without this, Home Assistant would see a brand new integration: new
entity ids, automations pointing at entities that no longer exist, history cut
in two, areas and names set by hand lost. The registry entries of the earlier
integration are moved here instead, so every entity keeps its entity id and
every device keeps its area, its name and its history. The unique ids and
device identifiers are the same, only the domain differs.
"""

from __future__ import annotations

import inspect
import logging

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Domains of the earlier ESPSomfy-RTS integrations, oldest first: when a board
# is still set up under several of them, the most recent one has the last word.
PREVIOUS_DOMAINS = ("espsomfy_rts", "espsomfy_rts_enhanced")


def previous_entry(hass: HomeAssistant, board_unique_id: str | None) -> ConfigEntry | None:
    """The board's entry under the most recent earlier integration, if any."""
    for old_domain in reversed(PREVIOUS_DOMAINS):
        for old in hass.config_entries.async_entries(old_domain):
            if old.unique_id == board_unique_id:
                return old
    return None


def _move_device(
    devices: dr.DeviceRegistry,
    device_id: str,
    identifiers: set[tuple[str, str]],
    new_entry_id: str,
    old_entry_id: str,
) -> None:
    """Give a device its new identifiers and move it to another config entry."""
    if "new_config_entry_id" in inspect.signature(devices.async_update_device).parameters:
        devices.async_update_device(
            device_id, new_identifiers=identifiers, new_config_entry_id=new_entry_id
        )
        return
    # Older releases move a device by adding the new entry, then removing the
    # old one. In two calls: in a single one, the removal starts again from the
    # device as it was and drops the entry just added.
    devices.async_update_device(
        device_id, new_identifiers=identifiers, add_config_entry_id=new_entry_id
    )
    devices.async_update_device(device_id, remove_config_entry_id=old_entry_id)


async def async_adopt_previous(
    hass: HomeAssistant, entry: ConfigEntry, board_unique_id: str
) -> None:
    """Move the registry entries of the same board from earlier integrations."""
    for old_domain in PREVIOUS_DOMAINS:
        for old in hass.config_entries.async_entries(old_domain):
            if old.unique_id == board_unique_id:
                await _async_adopt_entry(hass, entry, old)


async def _async_adopt_entry(hass: HomeAssistant, entry: ConfigEntry, old: ConfigEntry) -> None:
    """Move every entity and device of one earlier config entry to this one."""
    # Loaded entities cannot change integration. The earlier integration is
    # only loaded when its files are still installed; otherwise they never were.
    if old.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(old.entry_id)

    entities = er.async_get(hass)
    moved_entities = 0
    for reg_entry in er.async_entries_for_config_entry(entities, old.entry_id):
        # An entity Companion already created for the same unique id (it was
        # set up once beside the earlier integration) gives way: the earlier
        # entity id is the one automations and dashboards use.
        if duplicate := entities.async_get_entity_id(reg_entry.domain, DOMAIN, reg_entry.unique_id):
            entities.async_remove(duplicate)
        entities.async_update_entity_platform(
            reg_entry.entity_id, DOMAIN, new_config_entry_id=entry.entry_id
        )
        moved_entities += 1

    devices = dr.async_get(hass)
    moved_devices = 0
    for device in dr.async_entries_for_config_entry(devices, old.entry_id):
        identifiers = {
            (DOMAIN, ident) if domain == old.domain else (domain, ident)
            for domain, ident in device.identifiers
        }
        duplicate = next(
            (
                found
                for ident in identifiers
                if (found := devices.async_get_device_by_identifier(ident, entry.entry_id))
            ),
            None,
        )
        if duplicate is not None and duplicate.id != device.id:
            # Removing a device removes its entities: hand them over first.
            for reg_entry in er.async_entries_for_device(
                entities, duplicate.id, include_disabled_entities=True
            ):
                entities.async_update_entity(reg_entry.entity_id, device_id=device.id)
            devices.async_remove_device(duplicate.id)
        _move_device(devices, device.id, identifiers, entry.entry_id, old.entry_id)
        moved_devices += 1

    # Nothing is left on the earlier entry, removing it only drops the entry.
    await hass.config_entries.async_remove(old.entry_id)
    _LOGGER.info(
        "ESPSomfy-RTS %s: took over %s entities and %s devices from the earlier %s integration",
        entry.title,
        moved_entities,
        moved_devices,
        old.domain,
    )
