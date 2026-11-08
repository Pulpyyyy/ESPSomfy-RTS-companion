"""Rooms <-> areas and groups -> labels synchronisation."""

from __future__ import annotations

import json
from unittest.mock import patch

from homeassistant.const import CONF_HOST, CONF_PIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
    label_registry as lr,
)

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.espsomfy_rts_companion.const import (
    CONF_SYNC_ORGANIZATION,
    DOMAIN,
)
from custom_components.espsomfy_rts_companion.organization import (
    RESOLVE_BOARD,
    RESOLVE_HOME_ASSISTANT,
    room_name_for_board,
)
from custom_components.espsomfy_rts_companion.repairs import async_create_fix_flow

from .conftest import API_URL, DISCOVERY_PAYLOAD, DISCOVERY_URL, HOST, LOGIN_URL, SERVER_ID

CONFIG_URL = f"http://{HOST}"
UID = f"espsomfy_{SERVER_ID}"
CONFLICT_ISSUE = f"organization_conflict_{UID}"
LIMIT_ISSUE = f"room_limit_{UID}"


def _shade(shade_id: int, name: str, room_id: int) -> dict:
    return {
        "shadeId": shade_id, "type": 4, "shadeType": 4, "name": name,
        "roomId": room_id, "remoteAddress": 100000 + shade_id, "direction": 0,
        "position": 0, "target": 0, "myPos": 30, "tiltType": 0,
        "tiltPosition": 100, "tiltDirection": 0, "flipCommands": False,
        "flipPosition": False, "paired": True, "bitLength": 56, "proto": 0,
        "flags": 0,
    }


ROOMS = [{"roomId": 0, "name": "Home"}, {"roomId": 1, "name": "Salon"}]
SHADES = [_shade(1, "Baie", 1), _shade(2, "Cuisine", 0)]
GROUPS = [
    {
        "groupId": 1, "name": "Rez", "remoteAddress": 200001, "flags": 0,
        "linkedShades": [{"shadeId": 1}, {"shadeId": 2}],
    }
]


def _mock_board(aioclient_mock, *, add_room_status: int = 200) -> None:
    aioclient_mock.get(DISCOVERY_URL, json=DISCOVERY_PAYLOAD)
    aioclient_mock.put(LOGIN_URL, json={"success": True, "apiKey": "0123456789"})
    aioclient_mock.get(f"{API_URL}/shades", json=SHADES)
    aioclient_mock.get(f"{API_URL}/groups", json=GROUPS)
    aioclient_mock.get(f"{API_URL}/rooms", json=ROOMS)
    if add_room_status == 200:
        aioclient_mock.put(f"{CONFIG_URL}/addRoom", json={"roomId": 2, "name": "Bureau"})
    else:
        aioclient_mock.put(f"{CONFIG_URL}/addRoom", status=add_room_status, text="Maximum rooms")
    aioclient_mock.put(f"{CONFIG_URL}/saveShade", json=SHADES[0])
    aioclient_mock.put(f"{CONFIG_URL}/saveRoom", json={"roomId": 1, "name": "Séjour"})


def _entry(hass: HomeAssistant, options: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: HOST, CONF_PIN: "1234"},
        options=options or {},
        unique_id=UID,
    )
    entry.add_to_hass(hass)
    return entry


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    with patch(
        "custom_components.espsomfy_rts_companion.controller.ESPSomfyController.ws_connect",
        return_value=None,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def _puts(aioclient_mock, path: str) -> list:
    return [
        call for call in aioclient_mock.mock_calls
        if str(call[0]).upper() == "PUT" and str(call[1]) == f"{CONFIG_URL}{path}"
    ]


def _body(call) -> dict:
    data = call[2]
    return json.loads(data) if isinstance(data, (str, bytes)) else data


def _shade_device(hass: HomeAssistant, shade_id: int) -> dr.DeviceEntry:
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"shade_{UID}_{shade_id}"), hass.config_entries.async_entries(DOMAIN)[0].entry_id
    )
    assert device is not None
    return device


def test_room_name_for_board() -> None:
    """Area names are cut to what the board stores, without commas."""
    assert room_name_for_board(" Salon, côté jardin ") == "Salon  côté jardin"
    assert len(room_name_for_board("A" * 40)) == 20


async def test_board_rooms_and_groups_reach_home_assistant(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Rooms become areas, shades land in them, groups become labels."""
    _mock_board(aioclient_mock)
    await _setup(hass, _entry(hass))

    salon = ar.async_get(hass).async_get_area_by_name("Salon")
    assert salon is not None
    assert _shade_device(hass, 1).area_id == salon.id
    assert _shade_device(hass, 2).area_id is None

    label = lr.async_get(hass).async_get_label_by_name("Rez")
    assert label is not None
    entities = er.async_get(hass)
    for shade_id in (1, 2):
        entity_id = entities.async_get_entity_id("cover", DOMAIN, f"{UID}_{shade_id}")
        assert label.label_id in entities.async_get(entity_id).labels

    # Nothing to write back, nothing to repair.
    assert not _puts(aioclient_mock, "/saveShade")
    assert ir.async_get(hass).async_get_issue(DOMAIN, CONFLICT_ISSUE) is None


async def test_area_change_in_home_assistant_moves_the_shade(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A new area creates its room on the board and moves the shade there."""
    _mock_board(aioclient_mock)
    await _setup(hass, _entry(hass))

    bureau = ar.async_get(hass).async_create("Bureau")
    dr.async_get(hass).async_update_device(_shade_device(hass, 2).id, area_id=bureau.id)
    await hass.async_block_till_done()

    assert _body(_puts(aioclient_mock, "/addRoom")[-1]) == {"name": "Bureau"}
    assert _body(_puts(aioclient_mock, "/saveShade")[-1]) == {"shadeId": 2, "roomId": 2}


async def test_area_rename_renames_the_room(hass: HomeAssistant, aioclient_mock) -> None:
    """Renaming a linked area renames its room on the board."""
    _mock_board(aioclient_mock)
    await _setup(hass, _entry(hass))

    areas = ar.async_get(hass)
    areas.async_update(areas.async_get_area_by_name("Salon").id, name="Séjour")
    await hass.async_block_till_done()

    assert _body(_puts(aioclient_mock, "/saveRoom")[-1]) == {"roomId": 1, "name": "Séjour"}


async def test_room_limit_raises_a_repair(hass: HomeAssistant, aioclient_mock) -> None:
    """A board with no free room raises an issue instead of failing silently."""
    _mock_board(aioclient_mock, add_room_status=500)
    await _setup(hass, _entry(hass))

    bureau = ar.async_get(hass).async_create("Bureau")
    dr.async_get(hass).async_update_device(_shade_device(hass, 2).id, area_id=bureau.id)
    await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, LIMIT_ISSUE) is not None
    assert not _puts(aioclient_mock, "/saveShade")


async def _setup_with_conflict(hass: HomeAssistant, aioclient_mock) -> MockConfigEntry:
    """Shade 1 is in "Salon" on the board but already in "Bureau" in Home Assistant."""
    _mock_board(aioclient_mock)
    entry = _entry(hass)
    bureau = ar.async_get(hass).async_create("Bureau")
    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, f"shade_{UID}_1")}
    )
    devices.async_update_device(device.id, area_id=bureau.id)
    await _setup(hass, entry)
    return entry


async def test_mismatch_changes_nothing_and_asks(hass: HomeAssistant, aioclient_mock) -> None:
    """A first-sight mismatch leaves both sides alone and opens a repair."""
    await _setup_with_conflict(hass, aioclient_mock)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, CONFLICT_ISSUE)
    assert issue is not None and issue.is_fixable
    assert _shade_device(hass, 1).area_id == ar.async_get(hass).async_get_area_by_name("Bureau").id
    assert not _puts(aioclient_mock, "/saveShade")


async def test_repair_keeps_the_board(hass: HomeAssistant, aioclient_mock) -> None:
    """Keeping the board moves the device to the area of its room."""
    await _setup_with_conflict(hass, aioclient_mock)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, CONFLICT_ISSUE)

    flow = await async_create_fix_flow(hass, CONFLICT_ISSUE, issue.data)
    flow.hass = hass
    assert (await flow.async_step_init())["type"] == "menu"
    assert (await flow.async_step_board())["type"] == "create_entry"
    await hass.async_block_till_done()

    assert _shade_device(hass, 1).area_id == ar.async_get(hass).async_get_area_by_name("Salon").id
    assert not _puts(aioclient_mock, "/saveShade")
    assert ir.async_get(hass).async_get_issue(DOMAIN, CONFLICT_ISSUE) is None


async def test_repair_keeps_home_assistant(hass: HomeAssistant, aioclient_mock) -> None:
    """Keeping Home Assistant writes the area to the board as a room."""
    await _setup_with_conflict(hass, aioclient_mock)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, CONFLICT_ISSUE)

    flow = await async_create_fix_flow(hass, CONFLICT_ISSUE, issue.data)
    flow.hass = hass
    assert (await flow.async_step_home_assistant())["type"] == "create_entry"
    await hass.async_block_till_done()

    assert _body(_puts(aioclient_mock, "/addRoom")[-1]) == {"name": "Bureau"}
    assert _body(_puts(aioclient_mock, "/saveShade")[-1]) == {"shadeId": 1, "roomId": 2}
    assert ir.async_get(hass).async_get_issue(DOMAIN, CONFLICT_ISSUE) is None


async def test_option_off_leaves_home_assistant_alone(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """With the option off, no label is created and no room is written."""
    _mock_board(aioclient_mock)
    entry = _entry(hass, options={CONF_SYNC_ORGANIZATION: False})
    await _setup(hass, entry)

    assert entry.runtime_data.organization is None
    assert lr.async_get(hass).async_get_label_by_name("Rez") is None


async def test_group_deleted_on_the_board_removes_its_label(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A group deleted on the board takes its label off the shades.

    The label id was dropped from the tracking map before the covers were
    reconciled, so nothing ever removed it and it stayed on them for good.
    """
    _mock_board(aioclient_mock)
    entry = _entry(hass)
    await _setup(hass, entry)

    entities = er.async_get(hass)
    label = lr.async_get(hass).async_get_label_by_name("Rez")
    assert label is not None
    covers = [
        entities.async_get_entity_id("cover", DOMAIN, f"{UID}_{shade_id}")
        for shade_id in (1, 2)
    ]
    for entity_id in covers:
        assert label.label_id in entities.async_get(entity_id).labels

    # The group is gone from the board; the next sync must clean the shades.
    controller = entry.runtime_data
    controller.api._config["groups"] = []
    controller.organization._apply_groups()

    for entity_id in covers:
        assert label.label_id not in entities.async_get(entity_id).labels
