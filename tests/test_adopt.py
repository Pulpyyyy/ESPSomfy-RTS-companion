"""Tests for taking over a board from an earlier ESPSomfy-RTS integration."""

from __future__ import annotations

from collections.abc import Generator
from ipaddress import ip_address
from pathlib import Path
from unittest.mock import patch

import pytest

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PIN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.setup import async_setup_component

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.espsomfy_rts_companion.adopt import PREVIOUS_DOMAINS
from custom_components.espsomfy_rts_companion.const import CONF_MAX_BACKUPS, DOMAIN
from custom_components.espsomfy_rts_companion.controller import (
    ESPSomfyAPI,
    ESPSomfyController,
)

from .conftest import API_URL, DISCOVERY_PAYLOAD, HOST, LOGIN_URL, SERVER_ID

BOARD = f"espsomfy_{SERVER_ID}"
# Entity ids as they exist in a Home Assistant that ran an earlier integration
# for years: neither matches what Companion would name these entities today.
BACKUP_ID = "button.backup_espsomfy_rts"
CONNECTIVITY_ID = "binary_sensor.espsomfyrts_connectivite"


@pytest.fixture(autouse=True)
def mock_device_io(tmp_path: Path) -> Generator[None]:
    """No websocket, no probe, backups under a temporary directory."""

    async def probe(api: ESPSomfyAPI) -> bool:
        return True

    with (
        patch.object(ESPSomfyController, "ws_connect", return_value=None),
        patch.object(ESPSomfyAPI, "probe", probe),
        patch.object(ESPSomfyAPI, "backup_dir", property(lambda api: str(tmp_path))),
    ):
        yield


def _mock_board(aioclient_mock) -> None:
    aioclient_mock.get(f"{API_URL}/discovery", json=DISCOVERY_PAYLOAD)
    aioclient_mock.put(f"{API_URL}/login", json={"success": True, "apiKey": "0123456789"})
    aioclient_mock.get(f"{API_URL}/shades", json=[])
    aioclient_mock.get(f"{API_URL}/groups", json=[])


def _previous_board(
    hass: HomeAssistant, domain: str, unique_id: str = BOARD
) -> tuple[MockConfigEntry, dr.DeviceEntry]:
    """An earlier entry whose files are gone, with a customised hub device."""
    old = MockConfigEntry(domain=domain, data={CONF_HOST: HOST}, unique_id=unique_id)
    old.add_to_hass(hass)
    devices = dr.async_get(hass)
    hub = devices.async_get_or_create(
        config_entry_id=old.entry_id, identifiers={(domain, unique_id)}, name="ESPSomfyRTS"
    )
    area = ar.async_get(hass).async_get_or_create("Garage")
    hub = devices.async_update_device(hub.id, area_id=area.id, name_by_user="Box du garage")
    return old, hub


def _previous_entity(
    hass: HomeAssistant, old: MockConfigEntry, hub: dr.DeviceEntry, domain: str, key: str, object_id: str
) -> str:
    return er.async_get(hass).async_get_or_create(
        domain,
        old.domain,
        f"{key}_{old.unique_id}",
        config_entry=old,
        device_id=hub.id,
        suggested_object_id=object_id,
    ).entity_id


def _companion_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: HOST}, unique_id=BOARD)
    entry.add_to_hass(hass)
    return entry


async def _setup(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()


@pytest.mark.parametrize("old_domain", PREVIOUS_DOMAINS)
async def test_entity_ids_areas_and_names_survive_the_new_domain(
    hass: HomeAssistant, aioclient_mock, old_domain: str
) -> None:
    """Every entity keeps its entity id, the board keeps its area and name."""
    _mock_board(aioclient_mock)
    old, hub = _previous_board(hass, old_domain)
    assert _previous_entity(hass, old, hub, "button", "backup", "backup_espsomfy_rts") == BACKUP_ID
    assert (
        _previous_entity(hass, old, hub, "binary_sensor", "connectivity", "espsomfyrts_connectivite")
        == CONNECTIVITY_ID
    )
    entry = _companion_entry(hass)

    await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    entities = er.async_get(hass)
    for entity_id, domain, key in (
        (BACKUP_ID, "button", "backup"),
        (CONNECTIVITY_ID, "binary_sensor", "connectivity"),
    ):
        # The Companion entity is the earlier registry entry, under its old id.
        assert entities.async_get_entity_id(domain, DOMAIN, f"{key}_{BOARD}") == entity_id
        reg_entry = entities.async_get(entity_id)
        assert reg_entry.platform == DOMAIN
        assert reg_entry.config_entry_id == entry.entry_id
        assert reg_entry.device_id == hub.id
        assert hass.states.get(entity_id) is not None
    # No second backup button under the name Companion would have picked.
    buttons = [e for e in er.async_entries_for_config_entry(entities, entry.entry_id) if e.unique_id == f"backup_{BOARD}"]
    assert [e.entity_id for e in buttons] == [BACKUP_ID]

    device = dr.async_get(hass).async_get(hub.id)
    assert device.identifiers == {(DOMAIN, BOARD)}
    assert device.config_entries == {entry.entry_id}
    assert device.area_id == hub.area_id
    assert device.name_by_user == "Box du garage"

    assert not hass.config_entries.async_entries(old_domain)


async def test_old_entity_id_wins_over_a_previous_companion_setup(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Companion set up once beside the earlier integration: the id in use is kept."""
    _mock_board(aioclient_mock)
    old, hub = _previous_board(hass, PREVIOUS_DOMAINS[-1])
    _previous_entity(hass, old, hub, "button", "backup", "backup_espsomfy_rts")
    entry = _companion_entry(hass)
    entities = er.async_get(hass)
    duplicate = entities.async_get_or_create(
        "button", DOMAIN, f"backup_{BOARD}", config_entry=entry, suggested_object_id="espsomfyrts_sauvegarder"
    ).entity_id

    await _setup(hass)

    assert entities.async_get_entity_id("button", DOMAIN, f"backup_{BOARD}") == BACKUP_ID
    assert entities.async_get(duplicate) is None
    assert hass.states.get(BACKUP_ID) is not None


async def test_board_under_both_earlier_domains(hass: HomeAssistant, aioclient_mock) -> None:
    """The most recent earlier integration has the last word, nothing is lost."""
    _mock_board(aioclient_mock)
    oldest, oldest_hub = _previous_board(hass, PREVIOUS_DOMAINS[0])
    only_in_oldest = _previous_entity(hass, oldest, oldest_hub, "sensor", "chip_model", "espsomfyrts_puce")
    _previous_entity(hass, oldest, oldest_hub, "button", "backup", "espsomfy_rts_backup")
    recent, recent_hub = _previous_board(hass, PREVIOUS_DOMAINS[1])
    _previous_entity(hass, recent, recent_hub, "button", "backup", "backup_espsomfy_rts")
    _companion_entry(hass)

    await _setup(hass)

    entities = er.async_get(hass)
    assert entities.async_get_entity_id("button", DOMAIN, f"backup_{BOARD}") == BACKUP_ID
    assert entities.async_get(only_in_oldest).platform == DOMAIN
    assert entities.async_get(only_in_oldest).device_id == recent_hub.id
    assert not any(hass.config_entries.async_entries(d) for d in PREVIOUS_DOMAINS)


async def test_another_board_is_left_alone(hass: HomeAssistant, aioclient_mock) -> None:
    """Only the entries of the same board are taken over."""
    _mock_board(aioclient_mock)
    old, hub = _previous_board(hass, PREVIOUS_DOMAINS[-1], unique_id="espsomfy_ffffffff")
    other_id = _previous_entity(hass, old, hub, "button", "backup", "backup_espsomfy_rts")
    _companion_entry(hass)

    await _setup(hass)

    assert hass.config_entries.async_entries(old.domain) == [old]
    assert er.async_get(hass).async_get(other_id).platform == old.domain
    assert dr.async_get(hass).async_get(hub.id).identifiers == {(old.domain, "espsomfy_ffffffff")}


def _previous_entry_with_pin(hass: HomeAssistant) -> MockConfigEntry:
    """An earlier entry with a PIN, options, and the stale copy of the data
    that early versions kept in the options."""
    old = MockConfigEntry(
        domain=PREVIOUS_DOMAINS[-1],
        data={CONF_HOST: "192.168.1.99", CONF_PIN: "1234"},
        options={CONF_MAX_BACKUPS: 12, CONF_HOST: "192.168.1.98", CONF_PIN: "0000"},
        unique_id=BOARD,
    )
    old.add_to_hass(hass)
    return old


async def test_discovery_carries_the_pin_and_options_over(hass: HomeAssistant) -> None:
    """Confirming a discovered board needs no PIN when the earlier entry had it."""
    _previous_entry_with_pin(hass)
    info = ZeroconfServiceInfo(
        ip_address=ip_address(HOST),
        ip_addresses=[ip_address(HOST)],
        port=80,
        hostname="ESPSomfyRTS.local.",
        type="_espsomfy_rts._tcp.local.",
        name="ESPSomfyRTS._espsomfy_rts._tcp.local.",
        properties={"serverId": SERVER_ID, "model": "ESPSomfyRTS"},
    )
    with patch("custom_components.espsomfy_rts_companion.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=info
        )
        assert result["step_id"] == "zeroconf_confirm"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    # The discovered address wins, the PIN and the options come from the earlier entry.
    assert result["data"] == {CONF_HOST: HOST, CONF_PIN: "1234"}
    assert result["result"].options == {CONF_MAX_BACKUPS: 12}


async def test_manual_setup_without_pin_uses_the_earlier_one(hass: HomeAssistant, aioclient_mock) -> None:
    """A board added by hand logs in with the PIN of the earlier entry."""
    _previous_entry_with_pin(hass)
    aioclient_mock.get(f"{API_URL}/discovery", json=DISCOVERY_PAYLOAD | {"authType": 1})
    aioclient_mock.put(LOGIN_URL, json={"success": True, "apiKey": "0123456789"})

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    with patch("custom_components.espsomfy_rts_companion.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: HOST, CONF_PIN: ""}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: HOST, CONF_PIN: "1234"}
    login = [call for call in aioclient_mock.mock_calls if str(call[1]) == LOGIN_URL]
    assert login and login[-1][2]["pin"] == "1234"
