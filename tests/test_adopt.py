"""Taking over a board from an earlier ESPSomfy-RTS integration, on request."""

from __future__ import annotations

from collections.abc import Generator
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
from homeassistant.setup import async_setup_component

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.espsomfy_rts_companion.adopt import PREVIOUS_DOMAINS
from custom_components.espsomfy_rts_companion.const import DOMAIN
from custom_components.espsomfy_rts_companion.controller import (
    ESPSomfyAPI,
    ESPSomfyController,
)

from .conftest import API_URL, DISCOVERY_PAYLOAD, HOST, SERVER_ID

BOARD = f"espsomfy_{SERVER_ID}"
# Entity ids as a Home Assistant that ran an earlier integration for years has
# them; neither matches what Companion would name these entities today.
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


def _companion_entry(hass: HomeAssistant, adopt_from: str | None = None) -> MockConfigEntry:
    data = {CONF_HOST: HOST}
    if adopt_from is not None:
        data["adopt_from"] = adopt_from
    entry = MockConfigEntry(domain=DOMAIN, data=data, unique_id=BOARD)
    entry.add_to_hass(hass)
    return entry


async def _setup(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()


@pytest.mark.parametrize("old_domain", PREVIOUS_DOMAINS)
async def test_takeover_keeps_entity_ids_areas_and_names(
    hass: HomeAssistant, aioclient_mock, old_domain: str
) -> None:
    """On the marker, every entity keeps its id, the board its area and name."""
    _mock_board(aioclient_mock)
    old, hub = _previous_board(hass, old_domain)
    assert _previous_entity(hass, old, hub, "button", "backup", "backup_espsomfy_rts") == BACKUP_ID
    assert (
        _previous_entity(hass, old, hub, "binary_sensor", "connectivity", "espsomfyrts_connectivite")
        == CONNECTIVITY_ID
    )
    entry = _companion_entry(hass, adopt_from=old.entry_id)

    await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    entities = er.async_get(hass)
    for entity_id, domain, key in (
        (BACKUP_ID, "button", "backup"),
        (CONNECTIVITY_ID, "binary_sensor", "connectivity"),
    ):
        assert entities.async_get_entity_id(domain, DOMAIN, f"{key}_{BOARD}") == entity_id
        reg_entry = entities.async_get(entity_id)
        assert reg_entry.platform == DOMAIN
        assert reg_entry.config_entry_id == entry.entry_id
        assert reg_entry.device_id == hub.id
        assert hass.states.get(entity_id) is not None

    device = dr.async_get(hass).async_get(hub.id)
    assert device.identifiers == {(DOMAIN, BOARD)}
    assert device.config_entry_id == entry.entry_id
    assert device.area_id == hub.area_id
    assert device.name_by_user == "Box du garage"

    # The old entry is gone, and the one-shot marker is cleared.
    assert not hass.config_entries.async_entries(old_domain)
    assert "adopt_from" not in entry.data


async def test_takeover_removes_a_duplicate_companion_entity(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A Companion entity made for the same unique id gives way to the old id."""
    _mock_board(aioclient_mock)
    old, hub = _previous_board(hass, PREVIOUS_DOMAINS[-1])
    _previous_entity(hass, old, hub, "button", "backup", "backup_espsomfy_rts")
    entry = _companion_entry(hass, adopt_from=old.entry_id)
    entities = er.async_get(hass)
    duplicate = entities.async_get_or_create(
        "button", DOMAIN, f"backup_{BOARD}", config_entry=entry, suggested_object_id="espsomfyrts_sauvegarder"
    ).entity_id

    await _setup(hass)

    assert entities.async_get_entity_id("button", DOMAIN, f"backup_{BOARD}") == BACKUP_ID
    assert entities.async_get(duplicate) is None


async def test_no_marker_leaves_the_old_integration_alone(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Without the marker nothing of the earlier integration is touched."""
    _mock_board(aioclient_mock)
    old, hub = _previous_board(hass, PREVIOUS_DOMAINS[-1])
    old_id = _previous_entity(hass, old, hub, "button", "backup", "backup_espsomfy_rts")
    _companion_entry(hass)  # no adopt_from

    await _setup(hass)

    assert hass.config_entries.async_entries(old.domain) == [old]
    assert er.async_get(hass).async_get(old_id).platform == old.domain
    assert dr.async_get(hass).async_get(hub.id).identifiers == {(old.domain, BOARD)}


async def _user_flow(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_PIN: "1234"}
    )


async def test_flow_offers_the_takeover_and_confirming_sets_the_marker(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A previous entry makes the flow offer the takeover; yes sets the marker."""
    _mock_board(aioclient_mock)
    old, _ = _previous_board(hass, PREVIOUS_DOMAINS[-1])

    with patch("custom_components.espsomfy_rts_companion.async_setup_entry", return_value=True):
        result = await _user_flow(hass)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "adopt"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"adopt": True}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["adopt_from"] == old.entry_id
    assert result["data"][CONF_HOST] == HOST


async def test_flow_declining_the_takeover_adds_no_marker(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Declining adds the board fresh, no takeover."""
    _mock_board(aioclient_mock)
    _previous_board(hass, PREVIOUS_DOMAINS[-1])

    with patch("custom_components.espsomfy_rts_companion.async_setup_entry", return_value=True):
        result = await _user_flow(hass)
        assert result["step_id"] == "adopt"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"adopt": False}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "adopt_from" not in result["data"]


async def test_flow_without_a_previous_entry_skips_the_step(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """No earlier integration: the flow creates the entry straight away."""
    _mock_board(aioclient_mock)

    with patch("custom_components.espsomfy_rts_companion.async_setup_entry", return_value=True):
        result = await _user_flow(hass)
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "adopt_from" not in result["data"]
