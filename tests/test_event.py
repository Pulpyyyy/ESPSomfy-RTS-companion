"""Event entities: one per linked remote, fired by the board's commands."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

from homeassistant.const import CONF_HOST, CONF_PIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.espsomfy_rts_companion.const import DOMAIN
from custom_components.espsomfy_rts_companion.controller import (
    ESPSomfyAPI,
    ESPSomfyController,
)

from .conftest import API_URL, DISCOVERY_PAYLOAD, DISCOVERY_URL, HOST, LOGIN_URL, SERVER_ID

UID = f"espsomfy_{SERVER_ID}"


def _shade(shade_id: int, name: str, remotes: list[int]) -> dict:
    return {
        "shadeId": shade_id, "type": 4, "shadeType": 4, "name": name, "roomId": 0,
        "remoteAddress": 100000 + shade_id, "direction": 0, "position": 0, "target": 0,
        "myPos": 30, "tiltType": 0, "tiltPosition": 100, "tiltDirection": 0,
        "flipCommands": False, "flipPosition": False, "paired": True,
        "bitLength": 56, "proto": 0, "flags": 0,
        "linkedRemotes": [{"remoteAddress": a} for a in remotes],
    }


# Shade 1 has two remotes (5001, 5002); shade 2 shares 5002. So 5002 is one
# entity on shade 1 (its first shade), driving both.
SHADES = [_shade(1, "Baie", [5001, 5002]), _shade(2, "Cuisine", [5002])]


@pytest.fixture(autouse=True)
def mock_device_io(tmp_path: Path) -> Generator[None]:
    async def probe(api: ESPSomfyAPI) -> bool:
        return True

    with (
        patch.object(ESPSomfyController, "ws_connect", return_value=None),
        patch.object(ESPSomfyAPI, "probe", probe),
        patch.object(ESPSomfyAPI, "backup_dir", property(lambda api: str(tmp_path))),
    ):
        yield


async def _setup(hass: HomeAssistant, aioclient_mock) -> MockConfigEntry:
    aioclient_mock.get(DISCOVERY_URL, json=DISCOVERY_PAYLOAD)
    aioclient_mock.put(LOGIN_URL, json={"success": True, "apiKey": "0123456789"})
    aioclient_mock.get(f"{API_URL}/shades", json=SHADES)
    aioclient_mock.get(f"{API_URL}/groups", json=[])
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: HOST, CONF_PIN: "1234"}, unique_id=UID)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _event_id(hass: HomeAssistant, address: int) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("event", DOMAIN, f"remote_{UID}_{address}")
    assert entity_id is not None
    return entity_id


async def _command(hass: HomeAssistant, entry: MockConfigEntry, **data) -> None:
    entry.runtime_data.async_set_updated_data({"event": "shadeCommand", **data})
    await hass.async_block_till_done()


async def test_one_entity_per_remote(hass: HomeAssistant, aioclient_mock) -> None:
    """One event entity per address; a shared remote is a single entity."""
    await _setup(hass, aioclient_mock)
    entities = er.async_get(hass)

    # Two distinct remotes, so two entities (5002 is shared, not duplicated).
    ours = [e for e in er.async_entries_for_config_entry(entities, hass.config_entries.async_entries(DOMAIN)[0].entry_id) if e.domain == "event"]
    assert {e.unique_id for e in ours} == {f"remote_{UID}_5001", f"remote_{UID}_5002"}

    # The shared remote lists both shades it drives.
    shared = hass.states.get(_event_id(hass, 5002))
    assert shared.attributes["linked_shades"] == ["Baie", "Cuisine"]
    assert shared.attributes["remote_address"] == 5002


async def test_fires_on_a_remote_command(hass: HomeAssistant, aioclient_mock) -> None:
    """A command from the remote fires its entity with the command event type."""
    entry = await _setup(hass, aioclient_mock)
    entry.runtime_data.ws_onopen()
    event_id = _event_id(hass, 5001)
    assert hass.states.get(event_id).state == "unknown"  # no event yet

    await _command(hass, entry, shadeId=1, cmd="My", source="remote", sourceAddress=5001, remoteAddress=100001)

    state = hass.states.get(event_id)
    assert state.attributes["event_type"] == "my"
    assert state.attributes["command"] == "My"
    # A command from another remote leaves it untouched.
    before = state.state
    await _command(hass, entry, shadeId=1, cmd="Up", source="remote", sourceAddress=5002, remoteAddress=100001)
    assert hass.states.get(event_id).state == before


async def test_fanout_fires_once(hass: HomeAssistant, aioclient_mock) -> None:
    """One press of the shared remote reaches two shades but fires once."""
    entry = await _setup(hass, aioclient_mock)
    entry.runtime_data.ws_onopen()
    event_id = _event_id(hass, 5002)

    changes: list = []
    hass.bus.async_listen(
        "state_changed",
        lambda e: changes.append(e) if e.data.get("entity_id") == event_id else None,
    )

    # The board emits one shadeCommand per shade the remote drives.
    await _command(hass, entry, shadeId=1, cmd="Up", source="remote", sourceAddress=5002, remoteAddress=100001)
    await _command(hass, entry, shadeId=2, cmd="Up", source="remote", sourceAddress=5002, remoteAddress=100002)

    assert len(changes) == 1
    assert hass.states.get(event_id).attributes["event_type"] == "up"


async def test_internal_command_does_not_fire(hass: HomeAssistant, aioclient_mock) -> None:
    """A command from Home Assistant or the board is not a remote press."""
    entry = await _setup(hass, aioclient_mock)
    entry.runtime_data.ws_onopen()
    event_id = _event_id(hass, 5001)

    await _command(hass, entry, shadeId=1, cmd="My", source="internal", sourceAddress=0, remoteAddress=100001)
    assert hass.states.get(event_id).state == "unknown"
