"""Repairs about the board itself, read from /discovery.

- MQTT discovery on: Home Assistant then shows every shade twice, once from
  this integration and once from MQTT. Gone as soon as the board stops
  publishing it.
- A restart after a crash or a watchdog: one repair per crash, the user ignores
  it once read. A clean restart afterwards (a power cycle, an update) clears
  the ones left.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .const import CRASH_RESET_REASONS, DOMAIN

if TYPE_CHECKING:
    from .controller import ESPSomfyController

ISSUE_MQTT_DUPLICATES = "mqtt_duplicates"
ISSUE_UNEXPECTED_RESTART = "unexpected_restart"
# Readings of one boot differ by the request latency: they share this bucket.
BOOT_BUCKET_SECONDS = 300


@callback
def async_check_board(hass: HomeAssistant, controller: ESPSomfyController) -> None:
    """Create or clear the board repairs from what /discovery last said."""
    api = controller.api
    uid = controller.unique_id
    device = controller.device_name

    mqtt_issue = f"{ISSUE_MQTT_DUPLICATES}_{uid}"
    if api.mqtt_discovery:
        ir.async_create_issue(
            hass,
            DOMAIN,
            mqtt_issue,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_MQTT_DUPLICATES,
            translation_placeholders={"device": device, "url": api.get_config_url()},
            learn_more_url=api.get_config_url(),
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, mqtt_issue)

    reason = api.reset_reason
    boot = api.boot_time
    if reason is None or boot is None:
        return
    prefix = f"{ISSUE_UNEXPECTED_RESTART}_{uid}_"
    if reason not in CRASH_RESET_REASONS:
        registry = ir.async_get(hass)
        for domain, issue_id in list(registry.issues):
            if domain == DOMAIN and issue_id.startswith(prefix):
                ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{prefix}{int(boot.timestamp()) // BOOT_BUCKET_SECONDS}",
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_UNEXPECTED_RESTART,
        translation_placeholders={
            "device": device,
            "time": dt_util.as_local(boot).strftime("%Y-%m-%d %H:%M"),
            "reason": reason,
        },
    )
