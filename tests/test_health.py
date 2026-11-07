"""Radio health: repairs and diagnostic sensors from /rfStats."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from homeassistant.const import CONF_HOST, CONF_PIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.espsomfy_rts_companion.const import DOMAIN
from custom_components.espsomfy_rts_companion.health import recommended_repeats
from custom_components.espsomfy_rts_companion.repairs import async_create_fix_flow

from .conftest import API_URL, DISCOVERY_PAYLOAD, DISCOVERY_URL, HOST, LOGIN_URL, SERVER_ID

CONFIG_URL = f"http://{HOST}"
UID = f"espsomfy_{SERVER_ID}"
REMOTE = 5001


def _shade(repeats: int) -> dict:
    return {
        "shadeId": 1, "type": 4, "shadeType": 4, "name": "Baie", "roomId": 0,
        "remoteAddress": 100001, "direction": 0, "position": 0, "target": 0,
        "myPos": 30, "tiltType": 0, "tiltPosition": 100, "tiltDirection": 0,
        "flipCommands": False, "flipPosition": False, "paired": True,
        "bitLength": 56, "proto": 0, "flags": 0, "repeats": repeats,
        "linkedRemotes": [{"remoteAddress": REMOTE}],
    }


def _rf_stats(*, recent: float = -60.0, guided: int = 0) -> dict:
    return {
        "frequency": 433.42, "remotes": 1, "frames": 40,
        "noise": -99.5, "noiseBaseline": -100.0, "noiseSamples": 500,
        "entries": [{"address": REMOTE, "frames": 40, "recent": recent, "guided": guided}],
        "tx": {"jobs": 10, "frames": 40, "dropped": 3},
    }


async def _setup(
    hass: HomeAssistant,
    aioclient_mock,
    *,
    repeats: int,
    rf_stats: dict | None,
    version: str = "4.2.1",
    linked_remotes: list | None = None,
) -> MockConfigEntry:
    aioclient_mock.get(DISCOVERY_URL, json={**DISCOVERY_PAYLOAD, "version": version})
    aioclient_mock.put(LOGIN_URL, json={"success": True, "apiKey": "0123456789"})
    shade = _shade(repeats)
    if linked_remotes is not None:
        shade["linkedRemotes"] = linked_remotes
    aioclient_mock.get(f"{API_URL}/shades", json=[shade])
    aioclient_mock.get(f"{API_URL}/groups", json=[])
    aioclient_mock.get(f"{API_URL}/rooms", json=[])
    if rf_stats is None:
        aioclient_mock.get(f"{CONFIG_URL}/rfStats", status=404, text="Not found")
    else:
        aioclient_mock.get(f"{CONFIG_URL}/rfStats", json=rf_stats)
    aioclient_mock.put(f"{CONFIG_URL}/saveShade", json=_shade(2))

    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: HOST, CONF_PIN: "1234"}, unique_id=UID
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.espsomfy_rts_companion.controller.ESPSomfyController.ws_connect",
        return_value=None,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _issue(hass: HomeAssistant, key: str) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{key}_{UID}")


def _state(hass: HomeAssistant, unique_id: str):
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, unique_id)
    return None if entity_id is None else hass.states.get(entity_id)


@pytest.mark.parametrize(
    ("margin", "repeats"), [(40, 2), (30, 2), (25, 3), (15, 4), (10, 5), (3, 6)]
)
def test_recommended_repeats(margin: float, repeats: int) -> None:
    """Same ladder as the RF diagnostics page of the board."""
    assert recommended_repeats(margin) == repeats


async def test_zero_repeats_is_repaired(hass: HomeAssistant, aioclient_mock) -> None:
    """A shade sending each order once gets a repair that sets the advised value."""
    await _setup(hass, aioclient_mock, repeats=0, rf_stats=_rf_stats())

    issue = _issue(hass, "repeats_low_1")
    assert issue is not None and issue.is_fixable
    assert issue.translation_placeholders["recommended"] == "2"

    flow = await async_create_fix_flow(hass, issue.issue_id, issue.data)
    flow.hass = hass
    assert (await flow.async_step_init())["type"] == "form"
    assert (await flow.async_step_init({}))["type"] == "create_entry"
    await hass.async_block_till_done()

    puts = [c for c in aioclient_mock.mock_calls if str(c[1]) == f"{CONFIG_URL}/saveShade"]
    assert puts[-1][2] == {"shadeId": 1, "repeats": 2}
    assert _issue(hass, "repeats_low_1") is None


async def test_sensors_follow_the_statistics(hass: HomeAssistant, aioclient_mock) -> None:
    """Noise, lost orders and the margin of each shade are diagnostic sensors."""
    await _setup(hass, aioclient_mock, repeats=3, rf_stats=_rf_stats(recent=-60.0))

    assert float(_state(hass, f"radio_noise_{UID}").state) == pytest.approx(-99.5)
    assert int(_state(hass, f"radio_dropped_{UID}").state) == 3
    margin = _state(hass, f"radio_margin_{UID}_1")
    assert float(margin.state) == pytest.approx(40.0)
    assert margin.attributes["measurement"] == "passive"
    assert margin.attributes["unknown_reason"] is None
    assert margin.attributes["recommended_repeats"] == 2
    # Enough repeats, a good link: nothing to repair.
    assert _issue(hass, "repeats_low_1") is None
    assert _issue(hass, "weak_link_1") is None


async def test_weak_guided_link_is_reported(hass: HomeAssistant, aioclient_mock) -> None:
    """A weak guided measurement warns even when the repeats are already high."""
    await _setup(hass, aioclient_mock, repeats=6, rf_stats=_rf_stats(guided=-95))

    assert _issue(hass, "weak_link_1") is not None
    assert _issue(hass, "repeats_low_1") is None


async def test_weak_passive_link_is_not_reported(hass: HomeAssistant, aioclient_mock) -> None:
    """Passive samples alone never raise the weak link warning."""
    await _setup(hass, aioclient_mock, repeats=6, rf_stats=_rf_stats(recent=-95.0))

    assert _issue(hass, "weak_link_1") is None


async def test_board_without_statistics(hass: HomeAssistant, aioclient_mock) -> None:
    """Without /rfStats there are no radio sensors, the repeats floor still applies."""
    await _setup(hass, aioclient_mock, repeats=1, rf_stats=None)

    assert _state(hass, f"radio_noise_{UID}") is None
    issue = _issue(hass, "repeats_low_1")
    assert issue is not None
    assert issue.translation_placeholders["recommended"] == "2"


async def test_old_firmware_is_reported(hass: HomeAssistant, aioclient_mock) -> None:
    """A board below v4 gets a repair pointing at the browser installer."""
    await _setup(hass, aioclient_mock, repeats=2, rf_stats=None, version="3.1.0")

    issue = _issue(hass, "firmware_outdated")
    assert issue is not None
    assert issue.learn_more_url == "https://pulpyyyy.github.io/ESPSomfy-RTS/"


async def test_current_firmware_is_not_reported(hass: HomeAssistant, aioclient_mock) -> None:
    """A v4 board raises no firmware repair."""
    await _setup(hass, aioclient_mock, repeats=2, rf_stats=None)

    assert _issue(hass, "firmware_outdated") is None



async def test_margin_says_the_remote_was_not_heard(hass: HomeAssistant, aioclient_mock) -> None:
    """A linked remote the board never heard: unknown, and why."""
    stats = _rf_stats()
    stats["entries"] = []
    await _setup(hass, aioclient_mock, repeats=3, rf_stats=stats)

    margin = _state(hass, f"radio_margin_{UID}_1")
    assert margin.state == "unknown"
    assert margin.attributes["unknown_reason"] == "remote_not_heard"
    assert margin.attributes["measurement"] is None


async def test_margin_says_the_noise_is_not_measured(hass: HomeAssistant, aioclient_mock) -> None:
    """No noise sample yet: unknown, and why."""
    stats = _rf_stats()
    stats["noiseSamples"] = 0
    await _setup(hass, aioclient_mock, repeats=3, rf_stats=stats)

    margin = _state(hass, f"radio_margin_{UID}_1")
    assert margin.state == "unknown"
    assert margin.attributes["unknown_reason"] == "noise_not_measured"


async def test_no_margin_sensor_without_a_linked_remote(hass: HomeAssistant, aioclient_mock) -> None:
    """A shade driven by the board alone has nothing to measure: no sensor,
    and the one an earlier version created is removed."""
    registry = er.async_get(hass)
    stale = registry.async_get_or_create("sensor", DOMAIN, f"radio_margin_{UID}_1").entity_id
    await _setup(hass, aioclient_mock, repeats=3, rf_stats=_rf_stats(), linked_remotes=[])

    assert registry.async_get(stale) is None
    assert _state(hass, f"radio_margin_{UID}_1") is None
    # The board-wide sensors are still there.
    assert _state(hass, f"radio_noise_{UID}") is not None
