"""The restore service sends a stored backup back to the board."""

from __future__ import annotations

from collections.abc import Generator
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from homeassistant.const import CONF_HOST, CONF_PIN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.espsomfy_rts_companion.const import DOMAIN
from custom_components.espsomfy_rts_companion.controller import (
    ESPSomfyAPI,
    ESPSomfyController,
)

from .conftest import API_URL, DISCOVERY_PAYLOAD, DISCOVERY_URL, HOST, LOGIN_URL, SERVER_ID

UID = f"espsomfy_{SERVER_ID}"
RESTORE_URL = f"{API_URL}/restore"


@pytest.fixture
def backup_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture(autouse=True)
def mock_device_io(backup_dir: Path) -> Generator[None]:
    async def probe(api: ESPSomfyAPI) -> bool:
        return True

    with (
        patch.object(ESPSomfyController, "ws_connect", return_value=None),
        patch.object(ESPSomfyAPI, "probe", probe),
        patch.object(ESPSomfyAPI, "backup_dir", property(lambda api: str(backup_dir))),
    ):
        yield


async def _setup(hass: HomeAssistant, aioclient_mock, *, restore_status: int = 200) -> MockConfigEntry:
    aioclient_mock.get(DISCOVERY_URL, json=DISCOVERY_PAYLOAD)
    aioclient_mock.put(LOGIN_URL, json={"success": True, "apiKey": "0123456789"})
    aioclient_mock.get(f"{API_URL}/shades", json=[])
    aioclient_mock.get(f"{API_URL}/groups", json=[])
    aioclient_mock.post(RESTORE_URL, status=restore_status, text="ok" if restore_status == 200 else "no")
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: HOST, CONF_PIN: "1234"}, unique_id=UID)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _make_backup(backup_dir: Path, name: str, content: bytes, age_s: float = 0) -> Path:
    path = backup_dir / name
    path.write_bytes(content)
    if age_s:
        t = path.stat().st_mtime - age_s
        os.utime(path, (t, t))
    return path


def _backup_button(hass: HomeAssistant) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("button", DOMAIN, f"backup_{UID}")
    assert entity_id is not None
    return entity_id


async def _restore(hass: HomeAssistant, **data) -> None:
    await hass.services.async_call(
        DOMAIN, "restore", {"entity_id": _backup_button(hass), **data}, blocking=True
    )


async def test_restore_sends_the_newest_backup_with_the_chosen_sections(
    hass: HomeAssistant, aioclient_mock, backup_dir: Path
) -> None:
    """By default the newest file and only the shades section."""
    _make_backup(backup_dir, "old.backup", b"OLD", age_s=3600)
    _make_backup(backup_dir, "new.backup", b"NEWEST")
    entry = await _setup(hass, aioclient_mock)
    entry.runtime_data.ws_onopen()

    await _restore(hass)

    posts = [c for c in aioclient_mock.mock_calls if str(c[1]).split("?")[0] == RESTORE_URL]
    assert len(posts) == 1
    # Sections: default is shades only, all others false.
    sent = json.loads(str(posts[0][1].query["data"]))
    assert sent == {
        "shades": True, "settings": False, "network": False,
        "transceiver": False, "repeaters": False, "mqtt": False,
    }


async def test_restore_honours_explicit_sections_and_file(
    hass: HomeAssistant, aioclient_mock, backup_dir: Path
) -> None:
    """A named file and several sections are passed through."""
    _make_backup(backup_dir, "chosen.backup", b"CHOSEN")
    entry = await _setup(hass, aioclient_mock)
    entry.runtime_data.ws_onopen()

    await _restore(hass, sections=["shades", "mqtt"], backup="chosen.backup")

    posts = [c for c in aioclient_mock.mock_calls if str(c[1]).split("?")[0] == RESTORE_URL]
    sent = json.loads(str(posts[0][1].query["data"]))
    assert sent["shades"] is True and sent["mqtt"] is True
    assert sent["network"] is False


async def test_restore_without_any_backup_file_errors(
    hass: HomeAssistant, aioclient_mock, backup_dir: Path
) -> None:
    """No file on disk: a clear error, no request."""
    entry = await _setup(hass, aioclient_mock)
    entry.runtime_data.ws_onopen()

    with pytest.raises(HomeAssistantError) as err:
        await _restore(hass)
    assert err.value.translation_key == "restore_failed"
    assert not [c for c in aioclient_mock.mock_calls if str(c[1]).split("?")[0] == RESTORE_URL]


async def test_restore_rejected_by_the_board_errors(
    hass: HomeAssistant, aioclient_mock, backup_dir: Path
) -> None:
    """A non-200 answer raises."""
    _make_backup(backup_dir, "x.backup", b"X")
    entry = await _setup(hass, aioclient_mock, restore_status=500)
    entry.runtime_data.ws_onopen()

    with pytest.raises(HomeAssistantError) as err:
        await _restore(hass)
    assert err.value.translation_key == "restore_failed"


async def test_restore_refuses_a_file_outside_the_backup_directory(
    hass: HomeAssistant, aioclient_mock, backup_dir: Path
) -> None:
    """A traversal name is rejected before any request."""
    _make_backup(backup_dir, "x.backup", b"X")
    entry = await _setup(hass, aioclient_mock)
    entry.runtime_data.ws_onopen()

    with pytest.raises(HomeAssistantError):
        await _restore(hass, backup="../secret.backup")
    assert not [c for c in aioclient_mock.mock_calls if str(c[1]).split("?")[0] == RESTORE_URL]
