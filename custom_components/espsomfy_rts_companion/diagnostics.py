"""Diagnostics for ESPSomfy-RTS Companion.

Everything a bug report needs, with the secrets taken out: the login details,
the API key, and the radio addresses and rolling codes that would let anyone
clone a remote. Shades are summarised rather than dumped whole, so no code
leaves the device.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_PIN, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import ESPSomfyConfigEntry
from .controller import ESPSomfyController

TO_REDACT = {
    CONF_PASSWORD,
    CONF_PIN,
    CONF_USERNAME,
    "apiKey",
    "ssid",
    "serverId",
    # The radio address and rolling code are what it takes to clone a remote;
    # they appear on shades, on groups and inside a group's linked shades.
    "remoteAddress",
    "rollingCode",
}


def _shade_summary(shade: dict[str, Any]) -> dict[str, Any]:
    """A shade without anything that could clone a remote."""
    return {
        "shadeId": shade.get("shadeId"),
        "name": shade.get("name"),
        "roomId": shade.get("roomId"),
        "shadeType": shade.get("shadeType"),
        "tiltType": shade.get("tiltType"),
        "position": shade.get("position"),
        "repeats": shade.get("repeats"),
        "linked_remotes": len(shade.get("linkedRemotes") or []),
    }


def _radio(controller: ESPSomfyController) -> dict[str, Any]:
    health = controller.health
    if health is None or not health.supported:
        return {"supported": False}
    stats = health.stats or {}
    return {
        "supported": True,
        "noise": stats.get("noise"),
        "noise_baseline": stats.get("noiseBaseline"),
        "noise_samples": stats.get("noiseSamples"),
        "dropped": stats.get("tx", {}).get("dropped"),
        "shades": {
            shade_id: {
                "margin": data.get("margin"),
                "guided": data.get("guided"),
                "unknown_reason": data.get("unknown_reason"),
                "repeats": data.get("repeats"),
                "recommended": data.get("recommended"),
            }
            for shade_id, data in health.shades.items()
        },
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ESPSomfyConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    controller = entry.runtime_data
    api = controller.api
    return {
        "entry": {
            "data": async_redact_data(entry.data, TO_REDACT),
            "options": dict(entry.options),
        },
        "device": {
            "version": api.version,
            "latest": api.latest_version,
            "model": api.model,
            "chip_model": api.get_config().get("chipModel"),
            "conn_type": api.get_config().get("connType"),
            "auth_type": api.get_config().get("authType"),
            "memory": api.get_config().get("memory"),
            "rooms": len(api.rooms),
            "shades": len(api.shades),
            "groups": len(api.groups),
        },
        "connectivity": {
            "connectivity": controller.connectivity,
            "websocket_connected": controller.ws_connected,
            "http_ok": controller.http_ok,
            "ws_reconnects": controller.ws_reconnects,
            "last_probe_ok": controller.last_probe_ok,
        },
        "backup": {
            "last_backup": controller.last_backup,
            "backup_count": controller.backup_count,
            "max_backups": controller.max_backups,
        },
        "radio": _radio(controller),
        "organization_sync": controller.organization is not None,
        "shades": [_shade_summary(shade) for shade in api.shades],
        # Groups keep their structure, but their own address and the addresses
        # inside their linked shades are redacted by key.
        "groups": async_redact_data(api.groups, TO_REDACT),
        "rooms": api.rooms,
    }
