"""Remote devices, short and long presses, adopted remotes, Home Assistant as a
source, the My button and favorite position, board repairs and device actions."""

from __future__ import annotations

from collections.abc import Generator
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from homeassistant import config_entries
from homeassistant.components import automation
from homeassistant.components.device_automation import DeviceAutomationType
from homeassistant.const import CONF_HOST, CONF_PIN
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_get_device_automations,
)

from custom_components.espsomfy_rts_companion import device_action, device_trigger
from custom_components.espsomfy_rts_companion.const import (
    DOMAIN,
    EVENT_SHADE_COMMAND,
    SUBENTRY_REMOTE,
)
from custom_components.espsomfy_rts_companion.controller import (
    ESPSomfyAPI,
    ESPSomfyController,
)

from .conftest import API_URL, DISCOVERY_PAYLOAD, DISCOVERY_URL, HOST, LOGIN_URL, SERVER_ID

UID = f"espsomfy_{SERVER_ID}"
CONFIG_URL = f"http://{HOST}"


def _shade(shade_id: int, name: str, remotes: list[int], **extra) -> dict:
    return {
        "shadeId": shade_id, "type": 4, "shadeType": 4, "name": name, "roomId": 0,
        "remoteAddress": 100000 + shade_id, "direction": 0, "position": 0, "target": 0,
        "myPos": 30, "tiltType": 0, "tiltPosition": 100, "tiltDirection": 0,
        "flipCommands": False, "flipPosition": False, "paired": True,
        "bitLength": 56, "proto": 0, "flags": 0,
        "linkedRemotes": [{"remoteAddress": a} for a in remotes],
        **extra,
    }


SHADES = [_shade(1, "Baie", [5001, 5002]), _shade(2, "Cuisine", [5002])]
# Firmware 4.3 answers /discovery with the boot information and the press room.
DISCOVERY_43 = {
    **DISCOVERY_PAYLOAD,
    "version": "4.3.0",
    "uptime": 120,
    "resetReason": "software",
    "mqttDisco": False,
    "remoteEvents": True,
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


async def _setup(
    hass: HomeAssistant,
    aioclient_mock,
    discovery: dict | None = None,
    subentries: list | None = None,
) -> MockConfigEntry:
    aioclient_mock.get(DISCOVERY_URL, json=discovery or DISCOVERY_43)
    aioclient_mock.put(LOGIN_URL, json={"success": True, "apiKey": "0123456789"})
    aioclient_mock.get(f"{API_URL}/shades", json=SHADES)
    aioclient_mock.get(f"{API_URL}/groups", json=[])
    aioclient_mock.get(f"{API_URL}/rooms", json=[])
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: HOST, CONF_PIN: "1234"},
        unique_id=UID,
        subentries_data=subentries or [],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entry.runtime_data.ws_onopen()
    return entry


def _entity(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id is not None, unique_id
    return entity_id


def _device(hass: HomeAssistant, identifier: str) -> dr.DeviceEntry:
    entry_id = hass.config_entries.async_entries(DOMAIN)[0].entry_id
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, identifier), entry_id)
    assert device is not None, identifier
    return device


async def _push(hass: HomeAssistant, entry: MockConfigEntry, **data) -> None:
    # As the socket delivers it.
    entry.runtime_data.ws_onpacket(data)
    await hass.async_block_till_done()


async def _heard(hass, entry, address, cmd, phase, **extra) -> None:
    data = {"linked": True, "rssi": -60, "frames": 1, "durationMs": 0, **extra}
    await _push(
        hass, entry, event="remoteHeard", address=address, cmd=cmd, phase=phase, **data
    )


async def _record_service(hass: HomeAssistant) -> list[ServiceCall]:
    calls: list[ServiceCall] = []
    hass.services.async_register("test", "record", lambda call: calls.append(call))
    return calls


# Remotes: a device each, short and long presses ---------------------------------


async def test_remote_has_its_own_device(hass: HomeAssistant, aioclient_mock) -> None:
    """A linked remote is a device under the board, named after its shade."""
    await _setup(hass, aioclient_mock)
    device = _device(hass, f"remote_{UID}_5001")
    assert device.name == "Remote Baie #1"
    assert device.via_device_id == _device(hass, UID).id
    entry = er.async_get(hass).async_get(_entity(hass, "event", f"remote_{UID}_5001"))
    assert entry.device_id == device.id


async def test_press_then_short_release(hass: HomeAssistant, aioclient_mock) -> None:
    """Up fires on the press, up_short on a quick release."""
    entry = await _setup(hass, aioclient_mock)
    event_id = _entity(hass, "event", f"remote_{UID}_5001")
    seen: list[str] = []
    hass.bus.async_listen(
        "state_changed",
        lambda e: seen.append(e.data["new_state"].attributes.get("event_type"))
        if e.data.get("entity_id") == event_id else None,
    )
    await _heard(hass, entry, 5001, "Up", "press")
    await _heard(hass, entry, 5001, "Up", "release", durationMs=200)
    assert seen == ["up", "up_short"]
    assert hass.states.get(event_id).attributes["rssi"] == -60


async def test_long_press_fires_while_held(hass: HomeAssistant, aioclient_mock) -> None:
    """Held past a second, my_long fires before the release, and only once."""
    entry = await _setup(hass, aioclient_mock)
    event_id = _entity(hass, "event", f"remote_{UID}_5001")
    seen: list[str] = []
    hass.bus.async_listen(
        "state_changed",
        lambda e: seen.append(e.data["new_state"].attributes.get("event_type"))
        if e.data.get("entity_id") == event_id else None,
    )
    await _heard(hass, entry, 5001, "My", "press")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1.5))
    await hass.async_block_till_done()
    assert seen == ["my", "my_long"]
    await _heard(hass, entry, 5001, "My", "release", durationMs=1600)
    assert seen == ["my", "my_long"]


async def test_shade_commands_do_not_fire_with_a_press_stream(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """With remoteHeard, the per shade echo of a press is not a second event."""
    entry = await _setup(hass, aioclient_mock)
    event_id = _entity(hass, "event", f"remote_{UID}_5001")
    await _push(hass, entry, event="shadeCommand", shadeId=1, cmd="Up",
                source="remote", sourceAddress=5001, remoteAddress=100001)
    assert hass.states.get(event_id).state == "unknown"


async def test_remote_device_triggers(hass: HomeAssistant, aioclient_mock) -> None:
    """A remote device lists one trigger per button, and they run automations."""
    entry = await _setup(hass, aioclient_mock)
    device = _device(hass, f"remote_{UID}_5001")
    triggers = await async_get_device_automations(
        hass, DeviceAutomationType.TRIGGER, device.id
    )
    types = {t["type"] for t in triggers if t["domain"] == DOMAIN}
    assert {"up", "down", "my", "my_long", "up_short"} <= types

    calls = await _record_service(hass)
    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: {
                "trigger": {
                    "platform": "device",
                    "domain": DOMAIN,
                    "device_id": device.id,
                    "type": "down_short",
                },
                "action": {"service": "test.record"},
            }
        },
    )
    await hass.async_block_till_done()
    await _heard(hass, entry, 5001, "Down", "press")
    assert not calls
    await _heard(hass, entry, 5001, "Down", "release", durationMs=100)
    assert len(calls) == 1


# Adopted remotes -----------------------------------------------------------------


async def test_add_remote_subentry(hass: HomeAssistant, aioclient_mock) -> None:
    """Press a remote the board does not drive, name it: it becomes a device."""
    entry = await _setup(hass, aioclient_mock)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_REMOTE), context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS

    # A linked remote is not offered; the unlinked one is.
    await _push(hass, entry, event="remoteHeard", address=5001, cmd="Up",
                phase="press", linked=True)
    await _push(hass, entry, event="remoteHeard", address=7777, cmd="Up",
                phase="press", linked=False)
    result = await hass.config_entries.subentries.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "name"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Situo salon"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    device = _device(hass, f"remote_{UID}_7777")
    assert device.name == "Situo salon"
    event_id = _entity(hass, "event", f"remote_{UID}_7777")
    entry = hass.config_entries.async_get_entry(entry.entry_id)
    await _heard(hass, entry, 7777, "My", "press", linked=False)
    assert hass.states.get(event_id).attributes["event_type"] == "my"


async def test_add_remote_needs_the_press_stream(hass: HomeAssistant, aioclient_mock) -> None:
    """Older firmware cannot report a remote it does not drive."""
    entry = await _setup(hass, aioclient_mock, discovery=DISCOVERY_PAYLOAD)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_REMOTE), context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "firmware_too_old"


async def test_greeting_joins_the_press_room(hass: HomeAssistant, aioclient_mock) -> None:
    """The socket joins room 1 with the API key when the board has it."""
    entry = await _setup(hass, aioclient_mock)
    assert entry.runtime_data._ws_greeting() == ["join:1:0123456789"]


# Home Assistant as a source ------------------------------------------------------


async def test_commands_sent_by_home_assistant(hass: HomeAssistant, aioclient_mock) -> None:
    """The board echoes them as internal; the event says home_assistant, with context."""
    entry = await _setup(hass, aioclient_mock)
    aioclient_mock.put(f"{API_URL}/shadeCommand", json={})
    cover = _entity(hass, "cover", f"{UID}_1")
    events = []
    hass.bus.async_listen(EVENT_SHADE_COMMAND, events.append)

    context = Context()
    await hass.services.async_call(
        "cover", "close_cover", {"entity_id": cover}, blocking=True, context=context
    )
    await _push(hass, entry, event="shadeCommand", shadeId=1, cmd="Down",
                source="internal", sourceAddress=0, remoteAddress=100001)
    assert events[-1].data["source"] == "home_assistant"
    assert events[-1].context.id == context.id
    assert hass.states.get(cover).attributes["cmd_source"] == "home_assistant"

    # A remote takes it over: the next board command is the board's again.
    await _push(hass, entry, event="shadeCommand", shadeId=1, cmd="Up",
                source="remote", sourceAddress=5001, remoteAddress=100001)
    await _push(hass, entry, event="shadeCommand", shadeId=1, cmd="My",
                source="internal", sourceAddress=0, remoteAddress=100001)
    assert events[-1].data["source"] == "internal"


async def test_board_commands_stay_internal(hass: HomeAssistant, aioclient_mock) -> None:
    """A command from the board's page, without Home Assistant, stays internal."""
    entry = await _setup(hass, aioclient_mock)
    events = []
    hass.bus.async_listen(EVENT_SHADE_COMMAND, events.append)
    await _push(hass, entry, event="shadeCommand", shadeId=2, cmd="Up",
                source="internal", sourceAddress=0, remoteAddress=100002)
    assert events[-1].data["source"] == "internal"


# Trigger filters -----------------------------------------------------------------


async def test_device_trigger_command_filter(hass: HomeAssistant, aioclient_mock) -> None:
    """The command filter of a shade trigger matches the board spelling."""
    await _setup(hass, aioclient_mock)
    calls = await _record_service(hass)
    cover = _entity(hass, "cover", f"{UID}_1")
    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: {
                "trigger": {
                    "platform": "device",
                    "domain": DOMAIN,
                    "device_id": _device(hass, f"shade_{UID}_1").id,
                    "entity_id": cover,
                    "type": "command_received",
                    "command": "my",
                },
                "action": {"service": "test.record"},
            }
        },
    )
    await hass.async_block_till_done()
    hass.bus.async_fire(EVENT_SHADE_COMMAND, {"entity_id": cover, "event_key": "shadeCommand", "command": "Up"})
    await hass.async_block_till_done()
    assert not calls
    hass.bus.async_fire(EVENT_SHADE_COMMAND, {"entity_id": cover, "event_key": "shadeCommand", "command": "My"})
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_shade_trigger_offers_remotes_by_name(hass: HomeAssistant, aioclient_mock) -> None:
    """The remote filter lists the linked remotes, not a bare number box."""
    await _setup(hass, aioclient_mock)
    capabilities = await device_trigger.async_get_trigger_capabilities(
        hass,
        {
            "platform": "device",
            "domain": DOMAIN,
            "device_id": _device(hass, f"shade_{UID}_1").id,
            "entity_id": _entity(hass, "cover", f"{UID}_1"),
            "type": "command_received",
        },
    )
    remote = next(
        field for field in capabilities["extra_fields"].schema
        if str(field) == "remote_address"
    )
    choices = capabilities["extra_fields"].schema[remote].container
    assert set(choices) == {5001, 5002}


async def test_integration_trigger_once_per_press(hass: HomeAssistant, aioclient_mock) -> None:
    """One press reaching two shades runs the automation once."""
    entry = await _setup(hass, aioclient_mock)
    calls = await _record_service(hass)
    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: {
                "trigger": {
                    "trigger": "espsomfy_rts_companion.command_received",
                    "options": {"once_per_press": True, "command": "up"},
                },
                "action": {"service": "test.record"},
            }
        },
    )
    await hass.async_block_till_done()
    await _push(hass, entry, event="shadeCommand", shadeId=1, cmd="Up",
                source="remote", sourceAddress=5002, remoteAddress=100001)
    await _push(hass, entry, event="shadeCommand", shadeId=2, cmd="Up",
                source="remote", sourceAddress=5002, remoteAddress=100002)
    assert len(calls) == 1


# My button and favorite position -------------------------------------------------


async def test_my_button(hass: HomeAssistant, aioclient_mock) -> None:
    """The button sends My to its shade."""
    await _setup(hass, aioclient_mock)
    aioclient_mock.put(f"{API_URL}/shadeCommand", json={})
    button = _entity(hass, "button", f"my_{UID}_1")
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    sent = [c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/shadeCommand")]
    assert sent[-1][2] == {"shadeId": 1, "command": "My"}


async def test_favorite_position(hass: HomeAssistant, aioclient_mock) -> None:
    """Shown in open percent; a new value goes to the board in its own scale."""
    await _setup(hass, aioclient_mock)
    aioclient_mock.put(f"{CONFIG_URL}/setMyPosition", json={"shadeId": 1})
    number = _entity(hass, "number", f"my_position_{UID}_1")
    # The board says 30 (closed percent of a shutter): 70 % open.
    assert hass.states.get(number).state == "70"

    await hass.services.async_call(
        "number", "set_value", {"entity_id": number, "value": 70}, blocking=True
    )
    assert not [c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/setMyPosition")]

    await hass.services.async_call(
        "number", "set_value", {"entity_id": number, "value": 40}, blocking=True
    )
    sent = [c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/setMyPosition")]
    assert sent[-1][2] == {"shadeId": 1, "pos": 60}


# Board repairs and the last start ------------------------------------------------


async def test_mqtt_duplicates_repair(hass: HomeAssistant, aioclient_mock) -> None:
    """MQTT discovery on the board raises a repair."""
    await _setup(hass, aioclient_mock, discovery={**DISCOVERY_43, "mqttDisco": True})
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"mqtt_duplicates_{UID}")


async def test_crash_restart_repair(hass: HomeAssistant, aioclient_mock) -> None:
    """A start after a crash raises a repair and shows in the last start sensor."""
    await _setup(hass, aioclient_mock, discovery={**DISCOVERY_43, "resetReason": "panic"})
    issues = [
        issue_id for (domain, issue_id) in ir.async_get(hass).issues
        if domain == DOMAIN and issue_id.startswith(f"unexpected_restart_{UID}_")
    ]
    assert len(issues) == 1
    sensor = hass.states.get(_entity(hass, "sensor", f"last_boot_{UID}"))
    assert sensor.attributes["reset_reason"] == "panic"


async def test_clean_start_has_no_repair(hass: HomeAssistant, aioclient_mock) -> None:
    """A software restart is not a crash."""
    await _setup(hass, aioclient_mock)
    assert not [
        issue_id for (domain, issue_id) in ir.async_get(hass).issues
        if domain == DOMAIN and issue_id.startswith("unexpected_restart")
    ]


# Device actions ------------------------------------------------------------------


async def test_device_actions_in_any_language(hass: HomeAssistant, aioclient_mock) -> None:
    """Restart and Backup are offered whatever the entity ids are called."""
    await _setup(hass, aioclient_mock)
    registry = er.async_get(hass)
    backup = _entity(hass, "button", f"backup_{UID}")
    registry.async_update_entity(backup, new_entity_id="button.espsomfyrts_sauvegarder")
    reboot = _entity(hass, "button", f"reboot_{UID}")
    registry.async_update_entity(reboot, new_entity_id="button.espsomfyrts_redemarrer")
    actions = await device_action.async_get_actions(hass, _device(hass, UID).id)
    types = {a["type"] for a in actions if a.get("type") in ("Backup", "Reboot")}
    assert types == {"Backup", "Reboot"}


async def test_check_for_updates_asks_the_board(hass: HomeAssistant, aioclient_mock) -> None:
    """Settings > Updates > Check for updates makes the board fetch its releases."""
    await _setup(hass, aioclient_mock)
    aioclient_mock.get(f"{CONFIG_URL}/getReleases", json={"releases": []})
    update = _entity(hass, "update", f"update_{UID}")
    await async_setup_component(hass, "homeassistant", {})
    await hass.services.async_call(
        "homeassistant", "update_entity", {"entity_id": update}, blocking=True
    )
    assert [c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/getReleases")]
