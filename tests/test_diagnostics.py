"""Config-entry diagnostics: useful content, secrets taken out."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PIN, CONF_USERNAME
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.espsomfy_rts_companion.const import CONF_MAX_BACKUPS, DOMAIN
from custom_components.espsomfy_rts_companion.controller import ESPSomfyAPI, ESPSomfyController
from custom_components.espsomfy_rts_companion.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import API_URL, DISCOVERY_PAYLOAD, DISCOVERY_URL, HOST, LOGIN_URL, SERVER_ID

UID = f"espsomfy_{SERVER_ID}"
SHADE = {
    "shadeId": 1, "type": 4, "shadeType": 4, "name": "Baie", "roomId": 1,
    "remoteAddress": 123456, "rollingCode": 42, "position": 30, "target": 30,
    "myPos": 30, "tiltType": 0, "tiltPosition": 100, "repeats": 3, "flags": 0,
    "linkedRemotes": [{"remoteAddress": 123456, "rollingCode": 42}],
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


async def _setup(hass: HomeAssistant, aioclient_mock) -> MockConfigEntry:
    aioclient_mock.get(DISCOVERY_URL, json={**DISCOVERY_PAYLOAD, "version": "4.2.1"})
    aioclient_mock.put(LOGIN_URL, json={"success": True, "apiKey": "secret-key-123"})
    aioclient_mock.get(f"{API_URL}/shades", json=[SHADE])
    aioclient_mock.get(f"{API_URL}/groups", json=[])
    aioclient_mock.get(f"{API_URL}/rooms", json=[{"roomId": 1, "name": "Salon"}])
    aioclient_mock.get(f"http://{HOST}/rfStats", status=404, text="none")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: HOST, CONF_PIN: "1234", CONF_PASSWORD: "hunter2", CONF_USERNAME: "leo"},
        options={CONF_MAX_BACKUPS: 7},
        unique_id=UID,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_diagnostics_redacts_secrets_and_keeps_the_useful_parts(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """The login details are hidden, the device summary is there, no remote code leaks."""
    entry = await _setup(hass, aioclient_mock)

    diag = await async_get_config_entry_diagnostics(hass, entry)

    # Secrets are redacted.
    data = diag["entry"]["data"]
    for key in (CONF_PIN, CONF_PASSWORD, CONF_USERNAME):
        assert data[key] == "**REDACTED**"
    assert data[CONF_HOST] == HOST
    assert diag["entry"]["options"] == {CONF_MAX_BACKUPS: 7}

    # Device summary.
    assert diag["device"]["version"] == "4.2.1"
    assert diag["device"]["shades"] == 1
    assert diag["device"]["rooms"] == 1

    # Connectivity and backup.
    assert diag["connectivity"]["http_ok"] is True
    assert diag["backup"]["max_backups"] == 7

    # Shades are summarised: the count of linked remotes, never an address or code.
    shade = diag["shades"][0]
    assert shade == {
        "shadeId": 1, "name": "Baie", "roomId": 1, "shadeType": 4,
        "tiltType": 0, "position": 30, "repeats": 3, "linked_remotes": 1,
    }
    flat = str(diag)
    assert "123456" not in flat
    assert "secret-key-123" not in flat
    assert "hunter2" not in flat

    # No radio statistics on this board.
    assert diag["radio"] == {"supported": False}
