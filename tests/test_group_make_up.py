"""What a group is made of: its class, its make-up attribute, the mixed-group repair.

One radio command moves every member of a group, so a group that holds a gate or a
garage door must be one for Home Assistant (voice assistants then ask before
opening it), and mixing it with window coverings is worth a warning.
"""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.components.cover import CoverDeviceClass
from homeassistant.const import CONF_HOST, CONF_PIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.espsomfy_rts_companion.const import DOMAIN
from custom_components.espsomfy_rts_companion.cover import (
    ISSUE_GROUP_MIXED,
    group_device_class,
    group_make_up,
)

from .conftest import API_URL, DISCOVERY_PAYLOAD, DISCOVERY_URL, HOST, LOGIN_URL, SERVER_ID


def _shade(shade_id: int, shade_type: int, name: str) -> dict:
    return {
        "shadeId": shade_id, "type": shade_type, "shadeType": shade_type, "name": name,
        "remoteAddress": 100000 + shade_id, "direction": 0, "position": 0, "target": 0,
        "myPos": -1, "tiltType": 0, "tiltPosition": -1, "tiltDirection": 0,
        "flipCommands": False, "flipPosition": False, "paired": True,
        "bitLength": 56, "proto": 0, "flags": 0,
    }


SHADES = [
    _shade(1, 0, "Living Room"),
    _shade(2, 4, "Kitchen"),
    _shade(3, 1, "Office"),
    _shade(4, 12, "Driveway"),
    _shade(5, 6, "Garage"),
]


def _group(group_id: int, name: str, members: list[int]) -> dict:
    return {
        "groupId": group_id, "name": name, "remoteAddress": 200000 + group_id,
        "roomId": 0, "flags": 0, "bitLength": 56, "proto": 0, "flipCommands": False,
        "repeats": 2, "sortOrder": group_id - 1,
        "linkedShades": [s for s in SHADES if s["shadeId"] in members],
    }


def test_make_up_counts_families() -> None:
    """Roller shades and shutters are one family; unknown ids are skipped."""
    assert group_make_up(SHADES, [1, 2, 3, 4, 99]) == {"shutter": 2, "blind": 1, "gate": 1}
    assert group_make_up(SHADES, []) == {}


def test_device_class_follows_the_members() -> None:
    """A gate or a garage door decides; otherwise the most numerous covering."""
    assert group_device_class({"shutter": 4, "gate": 1}) == CoverDeviceClass.GATE
    assert group_device_class({"shutter": 2, "garage": 1}) == CoverDeviceClass.GARAGE
    assert group_device_class({"shutter": 1, "blind": 3}) == CoverDeviceClass.BLIND
    assert group_device_class({"shutter": 2, "awning": 2}) == CoverDeviceClass.SHUTTER
    assert group_device_class({"contact": 1}) == CoverDeviceClass.SHADE
    assert group_device_class({}) == CoverDeviceClass.SHADE


async def test_groups_get_their_class_attribute_and_repair(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A mixed group is a gate with a warning; a plain one is a shutter, no warning."""
    groups = [_group(1, "Front", [1, 2, 4]), _group(2, "Downstairs", [1, 2])]
    aioclient_mock.get(DISCOVERY_URL, json=DISCOVERY_PAYLOAD)
    aioclient_mock.put(LOGIN_URL, json={"success": True, "apiKey": "0123456789"})
    aioclient_mock.get(f"{API_URL}/shades", json=SHADES)
    aioclient_mock.get(f"{API_URL}/groups", json=groups)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: HOST, CONF_PIN: "1234"},
        unique_id=f"espsomfy_{SERVER_ID}",
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.espsomfy_rts_companion.controller.ESPSomfyController.ws_connect",
        return_value=None,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    controller = entry.runtime_data
    registry = er.async_get(hass)

    def group_state(group_id: int):
        entity_id = registry.async_get_entity_id("cover", DOMAIN, f"{controller.unique_id}_group{group_id}")
        assert entity_id is not None
        return hass.states.get(entity_id)

    front, downstairs = group_state(1), group_state(2)
    assert front.attributes["device_class"] == CoverDeviceClass.GATE
    assert front.attributes["make_up"] == {"shutter": 2, "gate": 1}
    assert downstairs.attributes["device_class"] == CoverDeviceClass.SHUTTER
    assert downstairs.attributes["make_up"] == {"shutter": 2}

    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, f"{ISSUE_GROUP_MIXED}_{controller.unique_id}_1") is not None
    assert issues.async_get_issue(DOMAIN, f"{ISSUE_GROUP_MIXED}_{controller.unique_id}_2") is None
