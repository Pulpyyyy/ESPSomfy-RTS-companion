"""Sensors related to ESPSomfy-RTS-HA."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import statistics
import time
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    UnitOfDataRate,
    UnitOfInformation,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    EVT_BACKUPDONE,
    EVT_BOARDINFO,
    EVT_CONNECTED,
    EVT_ETHERNET,
    EVT_MEMSTATUS,
    EVT_RADIOHEALTH,
    EVT_WIFISTRENGTH,
)
from .controller import ESPSomfyController
from .entity import ESPSomfyEntity
from .health import BoardHealth


@dataclass(frozen=True, kw_only=True)
class ESPSomfyDiagSensorDescription(SensorEntityDescription):
    """A base class descriptor for a sensor entity."""

    id: str | None = None
    events: dict | None = None
    native_value: Any | None = None
    min_interval: int = 0
    value_count: int = 1


@dataclass(frozen=True, kw_only=True)
class ESPSomfyRadioSensorDescription(SensorEntityDescription):
    """A sensor read from the radio health of the board (shade_id None: the board)."""

    value_fn: Callable[[BoardHealth, int | None], Any]
    attrs_fn: Callable[[BoardHealth, int | None], dict[str, Any]] | None = None


def _stats(health: BoardHealth) -> dict[str, Any]:
    return health.stats or {}


def _margin_attrs(health: BoardHealth, shade_id: int | None) -> dict[str, Any]:
    shade = health.shades.get(shade_id, {})
    measurement = None
    if shade.get("margin") is not None:
        measurement = "guided" if shade.get("guided") else "passive"
    return {
        "measurement": measurement,
        "unknown_reason": shade.get("unknown_reason"),
        "repeats": shade.get("repeats"),
        "recommended_repeats": shade.get("recommended"),
    }


RADIO_NOISE = ESPSomfyRadioSensorDescription(
    key="radio_noise",
    translation_key="radio_noise",
    has_entity_name=True,
    entity_category=EntityCategory.DIAGNOSTIC,
    device_class=SensorDeviceClass.SIGNAL_STRENGTH,
    state_class=SensorStateClass.MEASUREMENT,
    native_unit_of_measurement="dBm",
    suggested_display_precision=1,
    value_fn=lambda h, _: _stats(h).get("noise") if _stats(h).get("noiseSamples") else None,
    attrs_fn=lambda h, _: {"noise_baseline": _stats(h).get("noiseBaseline")},
)
RADIO_DROPPED = ESPSomfyRadioSensorDescription(
    key="radio_dropped",
    translation_key="radio_dropped",
    has_entity_name=True,
    entity_category=EntityCategory.DIAGNOSTIC,
    state_class=SensorStateClass.TOTAL_INCREASING,
    icon="mdi:radio-off",
    value_fn=lambda h, _: _stats(h).get("tx", {}).get("dropped"),
)
RADIO_MARGIN = ESPSomfyRadioSensorDescription(
    key="radio_margin",
    translation_key="radio_margin",
    has_entity_name=True,
    entity_category=EntityCategory.DIAGNOSTIC,
    device_class=SensorDeviceClass.SIGNAL_STRENGTH,
    state_class=SensorStateClass.MEASUREMENT,
    native_unit_of_measurement="dB",
    suggested_display_precision=0,
    value_fn=lambda h, shade_id: h.shades.get(shade_id, {}).get("margin"),
    attrs_fn=_margin_attrs,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up shades for the shade controller."""

    controller = config_entry.runtime_data
    new_entities = []
    data = controller.api.get_config()
    if "serverId" in data:
        if "hostname" in data:
            new_entities.append(
                ESPSomfyDiagSensor(
                    controller=controller,
                    cfg=ESPSomfyDiagSensorDescription(
                        key="host_name",
                        translation_key="host_name",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        has_entity_name=True,
                        native_value=data["hostname"],
                        events={},
                        icon="mdi:tag-text",
                    ),
                    data=data,
                )
            )
        if "chipModel" in data:
            chip_model = "ESP32"
            if len(data.get("chipModel") or ""):
                chip_model += "-"
                chip_model += data["chipModel"]
            new_entities.append(
                ESPSomfyDiagSensor(
                    controller=controller,
                    cfg=ESPSomfyDiagSensorDescription(
                        key="chip_model",
                        translation_key="chip_model",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        has_entity_name=True,
                        native_value=chip_model.upper(),
                        events={},
                        icon="mdi:cpu-32-bit",
                    ),
                    data=data,
                )
            )
        if "connType" in data:
            new_entities.append(
                ESPSomfyDiagSensor(
                    controller=controller,
                    cfg=ESPSomfyDiagSensorDescription(
                        key="conn_type",
                        translation_key="conn_type",
                        entity_category=EntityCategory.DIAGNOSTIC,
                        has_entity_name=True,
                        events={},
                        native_value=data["connType"],
                        icon="mdi:connection",
                    ),
                    data=data,
                )
            )
            if data["connType"] == "Wifi":
                new_entities.append(ESPSomfyWifiStrengthSensor(controller=controller, data=data))
                new_entities.append(
                    ESPSomfyDiagSensor(
                        controller=controller,
                        cfg=ESPSomfyDiagSensorDescription(
                            key="wifi_ssid",
                            translation_key="wifi_ssid",
                            entity_category=EntityCategory.DIAGNOSTIC,
                            has_entity_name=True,
                            icon="mdi:wifi-cog",
                            native_value=data.get("ssid", ""),
                            events={EVT_WIFISTRENGTH: "ssid"},
                        ),
                        data=data,
                    )
                )
                new_entities.append(
                    ESPSomfyDiagSensor(
                        controller=controller,
                        cfg=ESPSomfyDiagSensorDescription(
                            key="wifi_channel",
                            translation_key="wifi_channel",
                            entity_category=EntityCategory.DIAGNOSTIC,
                            has_entity_name=True,
                            icon="mdi:radio-tower",
                            events={EVT_WIFISTRENGTH: "channel"},
                        ),
                        data=data,
                    )
                )
            elif data["connType"] == "Ethernet":
                new_entities.append(
                    ESPSomfyDiagSensor(
                        controller=controller,
                        cfg=ESPSomfyDiagSensorDescription(
                            key="eth_speed",
                            translation_key="eth_speed",
                            entity_category=EntityCategory.DIAGNOSTIC,
                            has_entity_name=True,
                            state_class=SensorStateClass.MEASUREMENT,
                            device_class=SensorDeviceClass.DATA_RATE,
                            unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
                            icon="mdi:lan-connect",
                            native_value=data.get("speed", 100),
                            events={EVT_ETHERNET: "speed"},
                        ),
                        data=data,
                    )
                )
                new_entities.append(
                    ESPSomfyDiagSensor(
                        controller=controller,
                        cfg=ESPSomfyDiagSensorDescription(
                            key="eth_full_duplex",
                            translation_key="eth_full_duplex",
                            entity_category=EntityCategory.DIAGNOSTIC,
                            has_entity_name=True,
                            icon="mdi:sync",
                            native_value=bool(data.get("fullduplex", True)),
                            events={EVT_ETHERNET: "fullduplex"},
                        ),
                        data=data,
                    )
                )
        if "memory" in data:
            mem = data.get("memory") or {}
            if "free" in mem:
                new_entities.append(
                    ESPSomfyDiagSensor(
                        controller=controller,
                        cfg=ESPSomfyDiagSensorDescription(
                            key="free_memory",
                            translation_key="free_memory",
                            entity_category=EntityCategory.DIAGNOSTIC,
                            has_entity_name=True,
                            device_class=SensorDeviceClass.DATA_SIZE,
                            icon="mdi:memory",
                            state_class=SensorStateClass.MEASUREMENT,
                            unit_of_measurement=UnitOfInformation.BYTES,
                            suggested_display_precision=0,
                            native_value=mem["free"],
                            min_interval=25,
                            value_count=15,
                            events={EVT_MEMSTATUS: "free"},
                        ),
                        data=data,
                    )
                )
            if "max" in mem:
                new_entities.append(
                    ESPSomfyDiagSensor(
                        controller=controller,
                        cfg=ESPSomfyDiagSensorDescription(
                            key="max_memory",
                            translation_key="max_memory",
                            entity_category=EntityCategory.DIAGNOSTIC,
                            has_entity_name=True,
                            icon="mdi:memory",
                            device_class=SensorDeviceClass.DATA_SIZE,
                            unit_of_measurement=UnitOfInformation.BYTES,
                            state_class=SensorStateClass.MEASUREMENT,
                            suggested_display_precision=0,
                            native_value=mem["max"],
                            min_interval=30,
                            value_count=15,
                            events={EVT_MEMSTATUS: "max"},
                        ),
                        data=data,
                    )
                )
            if "min" in mem:
                new_entities.append(
                    ESPSomfyDiagSensor(
                        controller=controller,
                        cfg=ESPSomfyDiagSensorDescription(
                            key="min_memory",
                            translation_key="min_memory",
                            entity_category=EntityCategory.DIAGNOSTIC,
                            has_entity_name=True,
                            icon="mdi:memory",
                            device_class=SensorDeviceClass.DATA_SIZE,
                            min_interval=30,
                            value_count=15,
                            unit_of_measurement=UnitOfInformation.BYTES,
                            state_class=SensorStateClass.MEASUREMENT,
                            suggested_display_precision=0,
                            native_value=mem["min"],
                            events={EVT_MEMSTATUS: "min"},
                        ),
                        data=data,
                    )
                )

        new_entities.append(
            ESPSomfyDiagSensor(
                controller=controller,
                cfg=ESPSomfyDiagSensorDescription(
                    key="ip_address",
                    translation_key="ip_address",
                    entity_category=EntityCategory.DIAGNOSTIC,
                    has_entity_name=True,
                    icon="mdi:ip",
                    events={},
                    # The entry data always carries the host, but a hand edited
                    # entry must not take the whole platform down.
                    native_value=controller.api.get_data().get(
                        CONF_HOST, controller.api.get_host()
                    ),
                ),
                data=data,
            )
        )
        new_entities.append(
            ESPSomfyLastBackupSensor(
                controller=controller,
                cfg=ESPSomfyDiagSensorDescription(
                    key="last_backup",
                    translation_key="last_backup",
                    entity_category=EntityCategory.DIAGNOSTIC,
                    has_entity_name=True,
                    device_class=SensorDeviceClass.TIMESTAMP,
                    icon="mdi:backup-restore",
                    events={EVT_BACKUPDONE: None},
                ),
            )
        )
        # Firmware 4.3 tells since when it runs and why it started.
        if controller.api.boot_time is not None:
            new_entities.append(ESPSomfyLastBootSensor(controller))
        health = controller.health
        if health is not None and health.supported:
            new_entities.append(ESPSomfyRadioSensor(controller, RADIO_NOISE))
            new_entities.append(ESPSomfyRadioSensor(controller, RADIO_DROPPED))
            registry = er.async_get(hass)
            for shade in controller.api.shades:
                shade_id = int(shade.get("shadeId", -1))
                if shade_id not in health.shades:
                    continue
                if health.shades[shade_id]["linked"]:
                    new_entities.append(ESPSomfyRadioSensor(controller, RADIO_MARGIN, shade))
                # No remote linked: the board has nothing to measure for this
                # shade, the margin would stay unknown for good.
                elif entity_id := registry.async_get_entity_id(
                    "sensor", DOMAIN, f"{RADIO_MARGIN.key}_{controller.unique_id}_{shade_id}"
                ):
                    registry.async_remove(entity_id)
    if new_entities:
        async_add_entities(new_entities)


class ESPSomfyDiagSensor(ESPSomfyEntity, SensorEntity):
    """A diagnostic entity for the hub."""

    def __init__(
        self, *, controller: ESPSomfyController, cfg: ESPSomfyDiagSensorDescription, data: Any
    ) -> None:
        """Initialize a new diagnostic sensor."""
        super().__init__(data=data, controller=controller)
        self._controller = controller
        self._available = True
        self.events = {}

        self._attr_entity_category = cfg.entity_category
        self._attr_unique_id = f"{cfg.key}_{controller.unique_id}"
        self.entity_description = cfg
        self.events = cfg.events
        self._attr_native_value = cfg.native_value

        # Entity naming standard, the name comes from the translation key
        self._attr_has_entity_name = cfg.has_entity_name

        # Map the system properties the description carries

        self._attr_native_unit_of_measurement = cfg.unit_of_measurement
        self._attr_device_class = cfg.device_class
        self._attr_state_class = cfg.state_class

        self._last_recorded = time.time()
        self._min_interval = cfg.min_interval
        self._value_count = cfg.value_count
        self._values = []

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if not self.enabled:
            return
        if (
            "event" in self._controller.data
            and self._controller.data["event"] in self.events
        ):
            evt = self.events[self._controller.data["event"]]
            if evt in self._controller.data:
                self._values.append(self._controller.data[evt])
                val = self._controller.data[evt]
                if (
                    time.time() > self._last_recorded + self._min_interval
                    or len(self._values) >= self._value_count
                    or not self._available
                ):
                    self._available = True
                    if self._value_count > 1:
                        val = int(statistics.median(self._values))
                    self._values.clear()
                    self._last_recorded = time.time()
                    if val != self._attr_native_value:
                        self._attr_native_value = val
                        self.async_write_ha_state()
                elif self._attr_native_value is None:
                    self._attr_native_value = val
                    self.async_write_ha_state()
        elif (
            self._controller.data["event"] == EVT_CONNECTED
            and "connected" in self._controller.data
        ):
            if self._available != bool(self._controller.data["connected"]):
                self._available = bool(self._controller.data["connected"])
                self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Indicates whether the sensor is available."""
        return self._available


class ESPSomfyWifiStrengthSensor(ESPSomfyDiagSensor):
    """A wifi strength sensor indicating the current connection strength."""

    def __init__(self, *, controller: ESPSomfyController, data: Any) -> None:
        """Initialize a new Wifi strength Sensor."""
        super().__init__(
            controller=controller,
            cfg=ESPSomfyDiagSensorDescription(
                key="wifi_sensor",
                translation_key="wifi_sensor",
                has_entity_name=True,
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                entity_category=EntityCategory.DIAGNOSTIC,
                unit_of_measurement="dBm",
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:wifi",
                min_interval=30,
                value_count=15,
                events={EVT_WIFISTRENGTH: "strength"},
            ),
            data=data,
        )
        self._available = True


class ESPSomfyLastBackupSensor(ESPSomfyEntity, SensorEntity):
    """Time of the newest backup stored on the Home Assistant host."""

    def __init__(
        self, *, controller: ESPSomfyController, cfg: ESPSomfyDiagSensorDescription
    ) -> None:
        """Initialize the last backup sensor."""
        super().__init__(data=None, controller=controller)
        self._controller = controller
        self.entity_description = cfg
        self.events = cfg.events
        self._attr_unique_id = f"{cfg.key}_{controller.unique_id}"
        self._attr_has_entity_name = cfg.has_entity_name

    @property
    def available(self) -> bool:
        """The backups are local files, the device being offline is irrelevant."""
        return True

    @property
    def native_value(self) -> Any:
        """Modification time of the newest backup file."""
        return self._controller.last_backup

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Number of backups kept on disk."""
        return {"backup_count": self._controller.backup_count}

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self._controller.data.get("event") in self.events:
            self.async_write_ha_state()


class ESPSomfyLastBootSensor(ESPSomfyEntity, SensorEntity):
    """When the board last started, and why.

    Read from /discovery at setup and after each reconnection, never polled:
    the value only changes when the board restarts.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "last_boot"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:restart-alert"

    def __init__(self, controller: ESPSomfyController) -> None:
        """Initialize the last start sensor of the board."""
        super().__init__(data=None, controller=controller)
        self._controller = controller
        self._attr_unique_id = f"last_boot_{controller.unique_id}"

    @property
    def native_value(self) -> Any:
        """Time the board last started."""
        return self._controller.api.boot_time

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Why the board started (power on, restart, crash, watchdog...)."""
        return {"reset_reason": self._controller.api.reset_reason}

    def _handle_coordinator_update(self) -> None:
        """Rewrite the state when /discovery was read again."""
        if self._controller.data.get("event") == EVT_BOARDINFO:
            self.async_write_ha_state()


class ESPSomfyRadioSensor(ESPSomfyEntity, SensorEntity):
    """A value of the radio health, for the board or one of its shades."""

    entity_description: ESPSomfyRadioSensorDescription

    def __init__(
        self,
        controller: ESPSomfyController,
        description: ESPSomfyRadioSensorDescription,
        shade: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the sensor; a shade puts it on the device of that shade."""
        super().__init__(data=shade, controller=controller)
        self.entity_description = description
        self._shade_id = int(shade["shadeId"]) if shade else None
        suffix = "" if shade is None else f"_{self._shade_id}"
        self._attr_unique_id = f"{description.key}_{controller.unique_id}{suffix}"

    @property
    def available(self) -> bool:
        """Available once the board has published its radio statistics."""
        return self.controller.health is not None and self.controller.health.supported

    @property
    def native_value(self) -> Any:
        """The value, read from the last radio statistics."""
        health = self.controller.health
        if health is None:
            return None
        return self.entity_description.value_fn(health, self._shade_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Details of the value."""
        health = self.controller.health
        if health is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(health, self._shade_id)

    def _handle_coordinator_update(self) -> None:
        """Write the state after each reading of the radio statistics."""
        if self.controller.data.get("event") == EVT_RADIOHEALTH:
            self.async_write_ha_state()
