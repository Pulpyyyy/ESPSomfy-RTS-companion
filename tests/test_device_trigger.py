"""Device triggers: an automation starts when a shade receives a command."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

from homeassistant.components import automation
from homeassistant.const import CONF_HOST, CONF_PIN
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.espsomfy_rts_companion import device_trigger
from custom_components.espsomfy_rts_companion.const import DOMAIN
from custom_components.espsomfy_rts_companion.controller import (
    ESPSomfyAPI,
    ESPSomfyController,
)

from .conftest import API_URL, DISCOVERY_PAYLOAD, DISCOVERY_URL, HOST, LOGIN_URL, SERVER_ID

UID = f"espsomfy_{SERVER_ID}"
SHADE = {
    "shadeId": 1, "type": 4, "shadeType": 4, "name": "Baie", "roomId": 0,
    "remoteAddress": 100001, "direction": 0, "position": 0, "target": 0,
    "myPos": 30, "tiltType": 0, "tiltPosition": 100, "tiltDirection": 0,
    "flipCommands": False, "flipPosition": False, "paired": True,
    "bitLength": 56, "proto": 0, "flags": 0,
}


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


async def _setup(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(DISCOVERY_URL, json=DISCOVERY_PAYLOAD)
    aioclient_mock.put(LOGIN_URL, json={"success": True, "apiKey": "0123456789"})
    aioclient_mock.get(f"{API_URL}/shades", json=[SHADE])
    aioclient_mock.get(f"{API_URL}/groups", json=[])
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: HOST, CONF_PIN: "1234"}, unique_id=UID)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _cover(hass: HomeAssistant) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("cover", DOMAIN, f"{UID}_1")
    assert entity_id is not None
    return entity_id


def _shade_device(hass: HomeAssistant) -> str:
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, f"shade_{UID}_1"), hass.config_entries.async_entries(DOMAIN)[0].entry_id)
    assert device is not None
    return device.id


async def test_get_triggers_lists_command_received_per_shade(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Each shade device offers a command_received trigger on its cover."""
    await _setup(hass, aioclient_mock)
    triggers = await device_trigger.async_get_triggers(hass, _shade_device(hass))
    types = [t["type"] for t in triggers if t["domain"] == DOMAIN]
    assert types == ["command_received"]


async def test_command_event_fires_the_automation(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A shadeCommand event on the shade runs an automation built from the trigger."""
    await _setup(hass, aioclient_mock)
    calls: list[ServiceCall] = []
    hass.services.async_register("test", "record", lambda call: calls.append(call))

    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: {
                "trigger": {
                    "platform": "device",
                    "domain": DOMAIN,
                    "device_id": _shade_device(hass),
                    "entity_id": _cover(hass),
                    "type": "command_received",
                },
                "action": {
                    "service": "test.record",
                    "data": {"command": "{{ trigger.event.data.command }}"},
                },
            }
        },
    )
    await hass.async_block_till_done()

    # A command the board saw for another shade must not trigger it.
    hass.bus.async_fire(
        "espsomfy-rts_event",
        {"entity_id": "cover.other", "event_key": "shadeCommand", "command": "up"},
    )
    await hass.async_block_till_done()
    assert not calls

    hass.bus.async_fire(
        "espsomfy-rts_event",
        {"entity_id": _cover(hass), "event_key": "shadeCommand", "command": "my"},
    )
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert calls[0].data["command"] == "my"


async def test_device_trigger_source_filter(hass: HomeAssistant, aioclient_mock) -> None:
    """The optional source filter narrows a device trigger to one source."""
    await _setup(hass, aioclient_mock)
    calls: list[ServiceCall] = []
    hass.services.async_register("test", "record", lambda call: calls.append(call))

    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: {
                "trigger": {
                    "platform": "device",
                    "domain": DOMAIN,
                    "device_id": _shade_device(hass),
                    "entity_id": _cover(hass),
                    "type": "command_received",
                    "source": "remote",
                },
                "action": {"service": "test.record"},
            }
        },
    )
    await hass.async_block_till_done()

    hass.bus.async_fire(
        "espsomfy-rts_event",
        {"entity_id": _cover(hass), "event_key": "shadeCommand", "source": "internal"},
    )
    await hass.async_block_till_done()
    assert not calls

    hass.bus.async_fire(
        "espsomfy-rts_event",
        {"entity_id": _cover(hass), "event_key": "shadeCommand", "source": "remote"},
    )
    await hass.async_block_till_done()
    assert len(calls) == 1
