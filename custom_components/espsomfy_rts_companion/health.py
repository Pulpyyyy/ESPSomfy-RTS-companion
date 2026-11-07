"""Radio health of a board, turned into repairs and diagnostic sensors.

The board measures every remote it hears and the idle noise of the channel
(/rfStats). From the gap between the two it derives how many times an order
should be repeated, the same ladder as its RF diagnostics page: here the
result becomes a repair with a one-click fix when a shade repeats too little,
and a warning when even more repeats cannot save a weak link.

The measured path is remote -> board, the only one RTS lets anyone observe;
the path that matters is board -> motor. The ladder is therefore a floor:
a shade already repeating more is left alone, and a weak link is only
reported from a guided measurement (remote held next to its shade), never
from passive samples taken wherever the remote happened to be pressed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from packaging.version import InvalidVersion, parse as version_parse

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, EVT_RADIOHEALTH, FLASHER_URL

if TYPE_CHECKING:
    from .controller import ESPSomfyController

_LOGGER = logging.getLogger(__name__)

# Same values as the board's own interface.
MIN_REPEATS = 2
DEFAULT_REPEATS = 2
# Below this margin, retries alone rarely save a link.
WEAK_MARGIN = 8
# Dry contacts drive relays, not radio motors.
DRY_CONTACT_TYPES = (9, 10)

ISSUE_REPEATS = "repeats_low"
ISSUE_WEAK_LINK = "weak_link"
ISSUE_FIRMWARE = "firmware_outdated"


def recommended_repeats(margin: float) -> int:
    """Repeats advised for a signal-to-noise margin, in dB."""
    if margin >= 30:
        return MIN_REPEATS
    if margin >= 22:
        return MIN_REPEATS + 1
    if margin >= 14:
        return MIN_REPEATS + 2
    if margin >= WEAK_MARGIN:
        return MIN_REPEATS + 3
    return MIN_REPEATS + 4


class BoardHealth:
    """Read the radio statistics of one board and report what needs care."""

    def __init__(self, hass: HomeAssistant, controller: ESPSomfyController) -> None:
        """Prepare the checks; nothing is read before async_refresh()."""
        self.hass = hass
        self.controller = controller
        self.api = controller.api
        # /rfStats as last read, None when the board does not offer it.
        self.stats: dict[str, Any] | None = None
        # shadeId -> {"margin", "guided", "recommended", "repeats"}
        self.shades: dict[int, dict[str, Any]] = {}
        self._issues: set[str] = set()

    @property
    def supported(self) -> bool:
        """Whether the board publishes radio statistics."""
        return self.stats is not None

    async def async_refresh(self, reload: bool = True) -> None:
        """Read the board again, then update the repairs and the sensors."""
        if reload:
            await self.api.load_shades()
        stats = await self.api.load_rf_stats()
        if stats is not None:
            self.stats = stats
        self._evaluate()
        self.controller.async_set_updated_data(data={"event": EVT_RADIOHEALTH})

    async def async_try_refresh(self, reload: bool = True) -> None:
        """Refresh, logging instead of raising when the board does not answer."""
        try:
            await self.async_refresh(reload)
        except Exception as ex:  # noqa: BLE001
            _LOGGER.debug("ESPSomfy-RTS radio health not refreshed: %s", ex)

    async def async_apply_repeats(self, shade_id: int, repeats: int) -> bool:
        """Set the repeats of a shade on the board and check it again."""
        if await self.api.save_shade_repeats(shade_id, repeats) is None:
            return False
        self._evaluate()
        self.controller.async_set_updated_data(data={"event": EVT_RADIOHEALTH})
        return True

    # ------------------------------------------------------------------

    def _evaluate(self) -> None:
        issues: set[str] = set()
        self.shades = {}
        stats = self.stats or {}
        entries = {int(e["address"]): e for e in stats.get("entries", []) if "address" in e}
        noise_ref = None
        if stats.get("noiseSamples", 0) > 0:
            noise_ref = stats.get("noiseBaseline") or stats.get("noise")

        for shade in self.api.shades:
            if "shadeId" not in shade or int(shade.get("shadeType", 0)) in DRY_CONTACT_TYPES:
                continue
            shade_id = int(shade["shadeId"])
            name = shade.get("name") or f"Shade {shade_id}"
            repeats = shade.get("repeats")
            current = int(repeats) if isinstance(repeats, int) else DEFAULT_REPEATS
            margin, guided = self._margin(shade, entries, noise_ref)
            recommended = MIN_REPEATS if margin is None else recommended_repeats(margin)
            self.shades[shade_id] = {
                "margin": margin,
                "guided": guided,
                "recommended": recommended,
                "repeats": current,
            }
            if isinstance(repeats, int) and current < recommended:
                issues.add(
                    self._issue(
                        f"{ISSUE_REPEATS}_{shade_id}",
                        ISSUE_REPEATS,
                        fixable=True,
                        placeholders={
                            "shade": name,
                            "current": str(current),
                            "recommended": str(recommended),
                        },
                        data={"shade_id": shade_id, "repeats": recommended},
                    )
                )
            if guided and margin is not None and margin < WEAK_MARGIN:
                issues.add(
                    self._issue(
                        f"{ISSUE_WEAK_LINK}_{shade_id}",
                        ISSUE_WEAK_LINK,
                        placeholders={"shade": name, "margin": f"{margin:.0f}"},
                    )
                )

        if self._firmware_outdated():
            issues.add(
                self._issue(
                    ISSUE_FIRMWARE,
                    ISSUE_FIRMWARE,
                    placeholders={"version": str(self.controller.version)},
                    learn_more_url=FLASHER_URL,
                )
            )

        for issue_id in self._issues - issues:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self._issues = issues

    @staticmethod
    def _margin(
        shade: dict[str, Any], entries: dict[int, dict[str, Any]], noise_ref: float | None
    ) -> tuple[float | None, bool]:
        """Best margin over the remotes linked to a shade, and whether it was guided."""
        if noise_ref is None:
            return None, False
        best: dict[str, Any] | None = None
        for remote in shade.get("linkedRemotes") or []:
            entry = entries.get(int(remote.get("remoteAddress", 0)))
            if entry is None:
                continue
            if best is None or _level(entry) > _level(best):
                best = entry
        if best is None:
            return None, False
        return round(_level(best) - float(noise_ref), 1), bool(best.get("guided"))

    def _firmware_outdated(self) -> bool:
        try:
            return version_parse(str(self.controller.version).lstrip("v")).major < 4
        except (InvalidVersion, TypeError):
            return False

    def _issue(
        self,
        suffix: str,
        key: str,
        *,
        fixable: bool = False,
        placeholders: dict[str, str] | None = None,
        data: dict[str, Any] | None = None,
        learn_more_url: str | None = None,
    ) -> str:
        issue_id = f"{suffix}_{self.controller.unique_id}"
        placeholders = {"device": self.controller.device_name, **(placeholders or {})}
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=fixable,
            severity=ir.IssueSeverity.WARNING,
            translation_key=key,
            translation_placeholders=placeholders,
            learn_more_url=learn_more_url,
            data={
                "kind": key,
                "entry_id": self.controller.config_entry.entry_id,
                **(data or {}),
            },
        )
        return issue_id


def _level(entry: dict[str, Any]) -> float:
    """The guided measurement when there is one, the recent trend otherwise."""
    return float(entry.get("guided") or entry.get("recent") or -127)
