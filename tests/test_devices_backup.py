"""Devices follow the board, and every Home Assistant backup carries a fresh copy."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_HOST, CONF_PIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.espsomfy_rts_companion import async_remove_config_entry_device
from custom_components.espsomfy_rts_companion.backup import async_pre_backup
from custom_components.espsomfy_rts_companion.const import DOMAIN

from .conftest import API_URL, DISCOVERY_PAYLOAD, DISCOVERY_URL, HOST, LOGIN_URL, SERVER_ID

UID = f"espsomfy_{SERVER_ID}"
SHADE = {
    "shadeId": 1, "type": 4, "shadeType": 4, "name": "Baie", "roomId": 0,
    "remoteAddress": 100001, "direction": 0, "position": 0, "target": 0,
    "myPos": 30, "tiltType": 0, "tiltPosition": 100, "tiltDirection": 0,
    "flipCommands": False, "flipPosition": False, "paired": True,
    "bitLength": 56, "proto": 0, "flags": 0,
}


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: HOST, CONF_PIN: "1234"}, unique_id=UID
    )
    entry.add_to_hass(hass)
    return entry


async def _setup(hass: HomeAssistant, aioclient_mock, entry, *, shades_status: int = 200) -> None:
    aioclient_mock.get(DISCOVERY_URL, json=DISCOVERY_PAYLOAD)
    aioclient_mock.put(LOGIN_URL, json={"success": True, "apiKey": "0123456789"})
    if shades_status == 200:
        aioclient_mock.get(f"{API_URL}/shades", json=[SHADE])
    else:
        aioclient_mock.get(f"{API_URL}/shades", status=shades_status, text="busy")
    aioclient_mock.get(f"{API_URL}/groups", json=[])
    aioclient_mock.get(f"{API_URL}/rooms", json=[])
    with patch(
        "custom_components.espsomfy_rts_companion.controller.ESPSomfyController.ws_connect",
        return_value=None,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def _device(hass: HomeAssistant, identifier: str) -> dr.DeviceEntry | None:
    return dr.async_get(hass).async_get_device_by_identifier((DOMAIN, identifier), hass.config_entries.async_entries(DOMAIN)[0].entry_id)


def _stale_shade(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, f"shade_{UID}_9")}
    )


async def test_shades_deleted_while_stopped_are_removed(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A device whose shade is gone from the board is removed at startup."""
    entry = _entry(hass)
    _stale_shade(hass, entry)
    await _setup(hass, aioclient_mock, entry)

    assert _device(hass, f"shade_{UID}_9") is None
    assert _device(hass, f"shade_{UID}_1") is not None


async def test_failed_read_removes_nothing(hass: HomeAssistant, aioclient_mock) -> None:
    """A shade list the board did not return never looks like an empty board."""
    entry = _entry(hass)
    _stale_shade(hass, entry)
    await _setup(hass, aioclient_mock, entry, shades_status=500)

    assert _device(hass, f"shade_{UID}_9") is not None


async def test_shade_removed_on_the_board(hass: HomeAssistant, aioclient_mock) -> None:
    """The shadeRemoved event takes the device away at once."""
    entry = _entry(hass)
    await _setup(hass, aioclient_mock, entry)

    entry.runtime_data.ws_onpacket({"event": "shadeRemoved", "shadeId": 1})
    # Let the follow-up refresh of rooms and groups run.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=10))
    await hass.async_block_till_done()

    assert _device(hass, f"shade_{UID}_1") is None


async def test_shade_added_reloads_the_entry(hass: HomeAssistant, aioclient_mock) -> None:
    """A shade added on the board shows up through a reload, once per burst."""
    entry = _entry(hass)
    await _setup(hass, aioclient_mock, entry)

    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        entry.runtime_data.ws_onpacket({"event": "shadeAdded", "shadeId": 2})
        entry.runtime_data.ws_onpacket({"event": "shadeAdded", "shadeId": 2})
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=10))
        await hass.async_block_till_done()

    reload.assert_called_once_with(entry.entry_id)


async def test_only_devices_gone_from_the_board_can_be_deleted(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Deleting a live shade by hand would only bring it back at the next reload."""
    entry = _entry(hass)
    await _setup(hass, aioclient_mock, entry)
    live = _device(hass, f"shade_{UID}_1")
    gone = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, f"shade_{UID}_9")}
    )

    assert await async_remove_config_entry_device(hass, entry, live) is False
    assert await async_remove_config_entry_device(hass, entry, gone) is True


async def test_home_assistant_backup_takes_a_fresh_copy(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Each loaded board is backed up before Home Assistant backs up."""
    entry = _entry(hass)
    await _setup(hass, aioclient_mock, entry)
    controller = entry.runtime_data
    controller.last_backup = None

    with patch.object(controller, "async_backup", AsyncMock(return_value=True)) as backup:
        await async_pre_backup(hass)
    backup.assert_awaited_once()

    # A copy taken a few minutes ago is fresh enough.
    controller.last_backup = dt_util.utcnow() - timedelta(minutes=5)
    with patch.object(controller, "async_backup", AsyncMock(return_value=True)) as backup:
        await async_pre_backup(hass)
    backup.assert_not_awaited()


async def test_board_failure_never_fails_the_home_assistant_backup(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """An unreachable board is logged, the Home Assistant backup goes on."""
    entry = _entry(hass)
    await _setup(hass, aioclient_mock, entry)
    controller = entry.runtime_data
    controller.last_backup = None

    with patch.object(controller, "async_backup", AsyncMock(side_effect=OSError("down"))):
        await async_pre_backup(hass)
