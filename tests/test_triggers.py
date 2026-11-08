"""The enriched command event and the integration command_received trigger."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

from homeassistant.components import automation
from homeassistant.const import CONF_HOST, CONF_PIN
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.espsomfy_rts_companion.const import DOMAIN, EVENT_SHADE_COMMAND
from custom_components.espsomfy_rts_companion.controller import (
    ESPSomfyAPI,
    ESPSomfyController,
)

from .conftest import API_URL, DISCOVERY_PAYLOAD, DISCOVERY_URL, HOST, LOGIN_URL, SERVER_ID

UID = f"espsomfy_{SERVER_ID}"
# A shade with two linked remotes, so slot and linked can be checked.
SHADE = {
    "shadeId": 1, "type": 4, "shadeType": 4, "name": "Baie", "roomId": 0,
    "remoteAddress": 100001, "direction": 0, "position": 0, "target": 0,
    "myPos": 30, "tiltType": 0, "tiltPosition": 100, "tiltDirection": 0,
    "flipCommands": False, "flipPosition": False, "paired": True,
    "bitLength": 56, "proto": 0, "flags": 0,
    "linkedRemotes": [{"remoteAddress": 5001}, {"remoteAddress": 5002}],
}
GROUP = {"groupId": 1, "name": "Rez", "remoteAddress": 200001, "linkedShades": [{"shadeId": 1}]}


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
    aioclient_mock.get(f"{API_URL}/shades", json=[SHADE])
    aioclient_mock.get(f"{API_URL}/groups", json=[GROUP])
    aioclient_mock.get(f"{API_URL}/rooms", json=[])
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: HOST, CONF_PIN: "1234"}, unique_id=UID)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _cover(hass: HomeAssistant) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("cover", DOMAIN, f"{UID}_1")
    assert entity_id is not None
    return entity_id


async def _capture(hass: HomeAssistant) -> list[dict]:
    events: list[dict] = []
    hass.bus.async_listen(EVENT_SHADE_COMMAND, lambda event: events.append(event.data))
    return events


async def _command(hass: HomeAssistant, entry: MockConfigEntry, **data) -> None:
    entry.runtime_data.async_set_updated_data(
        {"event": "shadeCommand", "shadeId": 1, "cmd": "My", **data}
    )
    await hass.async_block_till_done()


async def test_event_from_a_dedicated_remote_is_enriched(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A remote linked at slot 2 gives type, slot, linked, name, device and area."""
    entry = await _setup(hass, aioclient_mock)
    entry.runtime_data.ws_onopen()
    events = await _capture(hass)

    await _command(hass, entry, source="remote", sourceAddress=5002, remoteAddress=100001)

    data = events[-1]
    assert data["remote_type"] == "remote"
    assert data["remote_slot"] == 2
    assert data["remote_linked"] is True
    assert data["remote_name"] == "Remote Baie #2"
    assert data["device_id"] is not None


async def test_event_from_an_unlinked_remote(hass: HomeAssistant, aioclient_mock) -> None:
    """A remote the shade does not know: no slot, not linked, bare default name."""
    entry = await _setup(hass, aioclient_mock)
    entry.runtime_data.ws_onopen()
    events = await _capture(hass)

    await _command(hass, entry, source="remote", sourceAddress=9999, remoteAddress=100001)

    data = events[-1]
    assert data["remote_type"] == "remote"
    assert data["remote_slot"] is None
    assert data["remote_linked"] is False
    assert data["remote_name"] == "Remote Baie"


async def test_group_command_uses_the_group_name(hass: HomeAssistant, aioclient_mock) -> None:
    """A group command names the remote after the group."""
    entry = await _setup(hass, aioclient_mock)
    entry.runtime_data.ws_onopen()
    events = await _capture(hass)

    await _command(hass, entry, source="group", sourceAddress=200001, remoteAddress=100001)

    data = events[-1]
    assert data["remote_type"] == "group"
    assert data["remote_name"] == "Rez"
    assert data["remote_slot"] is None


async def test_internal_command_has_no_remote_name(hass: HomeAssistant, aioclient_mock) -> None:
    """A command from Home Assistant or the board is internal, no remote name."""
    entry = await _setup(hass, aioclient_mock)
    entry.runtime_data.ws_onopen()
    events = await _capture(hass)

    await _command(hass, entry, source="internal", sourceAddress=0, remoteAddress=100001)

    data = events[-1]
    assert data["remote_type"] == "internal"
    assert data["remote_name"] is None


async def _record_service(hass: HomeAssistant) -> list[ServiceCall]:
    calls: list[ServiceCall] = []
    hass.services.async_register("test", "record", lambda call: calls.append(call))
    return calls


async def test_integration_trigger_all_shades_with_source_filter(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """command_received, no target, source=remote: every shade, remotes only."""
    entry = await _setup(hass, aioclient_mock)
    entry.runtime_data.ws_onopen()
    calls = await _record_service(hass)

    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: {
                "trigger": {
                    "trigger": "espsomfy_rts_companion.command_received",
                    "options": {"source": "remote"},
                },
                "action": {
                    "service": "test.record",
                    "data": {
                        "name": "{{ trigger.event.data.name }}",
                        "remote": "{{ trigger.event.data.remote_name }}",
                    },
                },
            }
        },
    )
    await hass.async_block_till_done()

    # A group command is filtered out by source=remote.
    await _command(hass, entry, source="group", sourceAddress=200001, remoteAddress=100001)
    assert not calls

    await _command(hass, entry, source="remote", sourceAddress=5001, remoteAddress=100001)
    assert len(calls) == 1
    assert calls[0].data["name"] == "Baie"
    assert calls[0].data["remote"] == "Remote Baie #1"


async def test_integration_trigger_target_limits_to_a_shade(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A target restricts the trigger to the chosen cover."""
    entry = await _setup(hass, aioclient_mock)
    entry.runtime_data.ws_onopen()
    calls = await _record_service(hass)

    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: {
                "trigger": {
                    "trigger": "espsomfy_rts_companion.command_received",
                    "target": {"entity_id": "cover.does_not_exist"},
                },
                "action": {"service": "test.record"},
            }
        },
    )
    await hass.async_block_till_done()

    await _command(hass, entry, source="remote", sourceAddress=5001, remoteAddress=100001)
    # The command is for cover Baie, not the targeted (missing) entity.
    assert not calls


async def test_integration_trigger_remote_address_filter(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """command_received with a remote_address only starts for that remote."""
    entry = await _setup(hass, aioclient_mock)
    entry.runtime_data.ws_onopen()
    calls = await _record_service(hass)

    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: {
                "trigger": {
                    "trigger": "espsomfy_rts_companion.command_received",
                    "options": {"source": "remote", "remote_address": 5001},
                },
                "action": {"service": "test.record"},
            }
        },
    )
    await hass.async_block_till_done()

    # Another remote of the same shade is filtered out.
    await _command(hass, entry, source="remote", sourceAddress=5002, remoteAddress=100001)
    assert not calls

    await _command(hass, entry, source="remote", sourceAddress=5001, remoteAddress=100001)
    assert len(calls) == 1
