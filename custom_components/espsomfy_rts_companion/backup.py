"""A fresh copy of each board in every Home Assistant backup.

The board backups live under the configuration directory, so Home Assistant
backups already carry them; this takes a new one first, so the copy in a
Home Assistant backup is the configuration of that moment. A board that does
not answer never makes the Home Assistant backup fail: the newest copy on
disk is kept instead.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# A copy younger than this is fresh enough.
FRESH_ENOUGH = timedelta(hours=1)
BOARD_TIMEOUT = 30


async def async_pre_backup(hass: HomeAssistant) -> None:
    """Take a backup of each loaded board before Home Assistant backs up."""
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        controller = getattr(entry, "runtime_data", None)
        if controller is None:
            continue
        last = controller.last_backup
        if last is not None and dt_util.utcnow() - last < FRESH_ENOUGH:
            continue
        if controller.connectivity is False:
            _LOGGER.warning(
                "ESPSomfy-RTS %s is offline: its newest copy on disk goes in the backup",
                controller.device_name,
            )
            continue
        try:
            async with asyncio.timeout(BOARD_TIMEOUT):
                ok = await controller.async_backup()
        except Exception as ex:  # noqa: BLE001
            _LOGGER.warning("ESPSomfy-RTS %s not backed up: %s", controller.device_name, ex)
            continue
        if not ok:
            _LOGGER.warning(
                "ESPSomfy-RTS %s not backed up: its newest copy on disk goes in the backup",
                controller.device_name,
            )


async def async_post_backup(hass: HomeAssistant) -> None:
    """Nothing to undo after a backup."""
