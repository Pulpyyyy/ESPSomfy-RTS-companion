"""Support for ESPSomfy RTS device actions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import logging

from packaging.version import Version, parse as version_parse

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .__init__ import ESPSomfyRTSEntityFeature
from .const import API_REBOOT, DOMAIN, EVT_CONNECTED
from .controller import ESPSomfyController
from .entity import ESPSomfyEntity

SVC_REBOOT = "reboot"
SVC_BACKUP = "backup"

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class ESPSomfyButtonDescription(ButtonEntityDescription):
    """A base class descriptor for a button entity."""

    id: str | None = None
    events: dict | None = None
    action: dict | None = None
    features: Iterable[int] | None = None


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ESPSomfy-RTS update based on a config entry."""
    new_entities = []
    controller: ESPSomfyController = config_entry.runtime_data
    v = version_parse(controller.version)
    if v >= Version("2.3.0"):
        new_entities.append(
            ESPSomfyButton(
                controller=controller,
                cfg=ESPSomfyButtonDescription(
                    key="reboot",
                    translation_key="reboot",
                    has_entity_name=True,
                    entity_category=EntityCategory.CONFIG,
                    device_class=ButtonDeviceClass.RESTART,
                    events={},
                    action={"service": API_REBOOT},
                    features=1,
                    icon="mdi:restart",
                ),
            )
        )
    if v.major >= 1:
        new_entities.append(
            ESPSomfyButton(
                controller=controller,
                cfg=ESPSomfyButtonDescription(
                    key="backup",
                    translation_key="backup",
                    has_entity_name=True,
                    entity_category=EntityCategory.CONFIG,
                    device_class=ButtonDeviceClass.IDENTIFY,
                    events={},
                    action={"apimethod": "create_backup"},
                    features=2,
                    icon="mdi:download",
                ),
            )
        )
    async_add_entities(new_entities)
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        name=SVC_REBOOT,
        schema={},
        func="async_press",
        required_features=[ESPSomfyRTSEntityFeature.REBOOT],
    )
    platform.async_register_entity_service(
        name=SVC_BACKUP,
        schema={},
        func="async_press",
        required_features=[ESPSomfyRTSEntityFeature.BACKUP],
    )


class ESPSomfyButton(ESPSomfyEntity, ButtonEntity):
    """Defines a reboot entity."""

    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(
        self, *, controller: ESPSomfyController, cfg: ESPSomfyButtonDescription
    ) -> None:
        """Initialize the reboot entity."""
        super().__init__(data=None, controller=controller)
        self._controller = controller
        self._attr_device_class = cfg.device_class

        # Bind the description
        self.entity_description = cfg

        self._attr_unique_id = f"{cfg.key}_{controller.unique_id}"
        self._attr_entity_category = cfg.entity_category
        self._attr_icon = cfg.icon
        self._attr_available = True
        self._action = cfg.action
        self._attr_assumed_state = True
        self._attr_supported_features = cfg.features

        # Home Assistant naming standard: the entity id is built from the device
        # name and the translation key, no need to force an object id.
        self._attr_has_entity_name = cfg.has_entity_name
        self._attr_translation_key = cfg.translation_key

    async def async_press(self) -> None:
        """Process the button press."""
        data = None
        if "data" in self._action:
            data = self._action["data"]
        is_backup = self.entity_description.key == "backup"

        # 1. A backup of a device known to be offline fails right away, with
        # no request: the caller (an automation) must see it fail.
        if is_backup and self._controller.connectivity is False:
            raise self._backup_failed()

        # 2. Run the requested action. A backup also keeps the configured
        # number of copies; create_backup() already logged why it failed.
        if is_backup:
            if not await self._controller.async_backup():
                raise self._backup_failed()
        elif "service" in self._action:
            await self._controller.api.put_command(self._action["service"], data)
        elif "apimethod" in self._action:
            method = getattr(self._controller.api, self._action["apimethod"])
            await method()

    def _backup_failed(self) -> HomeAssistantError:
        """Build the error raised when a backup could not be written."""
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="backup_failed",
            translation_placeholders={"name": self._controller.device_name},
        )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # The backup button stays available: Home Assistant silently skips
        # unavailable entities in a service call, so an offline device would
        # make the backup a no-op instead of the error async_press raises.
        if self.entity_description.key == "backup":
            return
        if self._controller.data.get("event", "") == EVT_CONNECTED:
            if "connected" in self._controller.data and self._attr_available != bool(
                self._controller.data["connected"]
            ):
                self._attr_available = bool(self._controller.data["connected"])
                self.async_write_ha_state()
