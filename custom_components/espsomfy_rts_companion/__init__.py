"""The ESPSomfy RTS integration."""

from __future__ import annotations

from enum import IntFlag
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_PIN,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry

from .adopt import async_adopt_entry
from .board import async_check_board
from .const import (
    CONF_ADDRESS,
    CONF_SYNC_ORGANIZATION,
    DEFAULT_SYNC_ORGANIZATION,
    DOMAIN,
    MANUFACTURER,
    PLATFORMS,
    SUBENTRY_REMOTE,
    VERSION,
)
from .controller import ESPSomfyAPI, ESPSomfyController, LoginError
from .health import BoardHealth
from .organization import OrganizationSync

_LOGGER = logging.getLogger(__name__)

type ESPSomfyConfigEntry = ConfigEntry[ESPSomfyController]


class ESPSomfyRTSEntityFeature(IntFlag):
    """Supported features of ESPSomfy-RTS Entities."""

    REBOOT = 1
    BACKUP = 2


async def async_setup_entry(hass: HomeAssistant, entry: ESPSomfyConfigEntry) -> bool:
    """Set up ESPSomfy-RTS from a config entry."""
    api = ESPSomfyAPI(hass, entry.entry_id, entry.data)
    controller = ESPSomfyController(entry, hass, api)

    entry.runtime_data = controller

    # 1. On récupère la configuration initiale du boîtier
    await api.get_initial()
    if not api.is_configured:
        raise ConfigEntryNotReady(
            f"Could not find ESPSomfy-RTS device with address {api.get_api_url()}"
        )

    # 2. Authentification auprès du boîtier : sans ce login l'apikey reste vide
    #    et tous les appels REST authentifiés renvoient 401.
    try:
        await api.login(
            {
                "username": entry.data.get(CONF_USERNAME, ""),
                "password": entry.data.get(CONF_PASSWORD, ""),
                "pin": entry.data.get(CONF_PIN, ""),
            }
        )
    except LoginError as ex:
        raise ConfigEntryAuthFailed(
            f"Could not log in to ESPSomfy-RTS device at {api.get_api_url()}"
        ) from ex

    hass.config_entries.async_update_entry(entry, title=api.deviceName)

    # Take over an earlier ESPSomfy-RTS integration only when the user asked for
    # it in the config flow (a one-shot marker in the entry data). Before the
    # platforms, so nothing gets created twice.
    if adopt_from := entry.data.get("adopt_from"):
        await async_adopt_entry(hass, entry, adopt_from)
        hass.config_entries.async_update_entry(
            entry, data={k: v for k, v in entry.data.items() if k != "adopt_from"}
        )

    # Migration des unique_id historiques (typo "ip_addresss" corrigé en v3.0.2),
    # à faire avant le chargement des plateformes pour ne pas orpheliner l'entité.
    await _async_migrate_unique_ids(hass, entry)

    # 3. Chargement des shades/groups, une fois authentifié. get_initial() ne récupère
    #    que /discovery (identité) : sur un boîtier en auth complète, /discovery n'inclut
    #    plus la liste des shades/groups sans token, donc les plateformes seraient créées
    #    avec une liste vide et tous les volets reviendraient "unavailable".
    shades = await api.load_shades()
    groups = await api.load_groups()
    # Newest local backup for the "Last backup" sensor, read before the
    # platforms so the entity starts with its value.
    await controller.async_update_backup_info()
    # Radio health, read before the platforms so the sensor platform knows
    # whether the board publishes radio statistics.
    controller.health = BoardHealth(hass, controller)
    await controller.health.async_try_refresh(reload=False)

    # The board's device first: shades, groups and remotes hang under it by its
    # registry id, which the platforms load concurrently could not count on.
    board = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, controller.unique_id)},
        name=controller.device_name,
        manufacturer=MANUFACTURER,
        model=f"ESPSomfy-RTS Companion {VERSION}",
        sw_version=controller.version,
        configuration_url=api.get_config_url(),
    )
    controller.board_device_id = board.id

    # 4. Les plateformes ne sont chargées qu'une fois le login réussi, sinon un
    #    échec après forward provoquait un double chargement au retry.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Shades and groups deleted on the board while Home Assistant was not
    # listening. Only from lists the board actually returned: a failed read
    # must never look like a board without shades.
    if shades is not None and groups is not None:
        _async_remove_stale_devices(hass, entry, controller, shades, groups)
    # MQTT duplicates and restarts after a crash, from the /discovery read above.
    async_check_board(hass, controller)

    async def _async_ws_close(_: Event) -> None:
        await controller.ws_close()

    # Si Home Assistant s'arrête proprement, on ferme le socket
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_ws_close)
    )
    # Reload automatique quand l'hôte ou les identifiants changent via le flow d'options
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # 4. On lance la connexion WebSocket
    await controller.ws_connect()
    # 5. HTTP reachability probe, independent from the websocket reconnects.
    controller.start_probe()
    # 6. Rooms <-> areas and groups -> labels. A failure here must not keep
    #    the shades from working, so it is only logged.
    if entry.options.get(CONF_SYNC_ORGANIZATION, DEFAULT_SYNC_ORGANIZATION):
        organization = OrganizationSync(hass, controller)
        try:
            await organization.async_start()
        except Exception:
            _LOGGER.exception("ESPSomfy-RTS %s: rooms and groups not synchronised", api.deviceName)
            organization.async_stop()
        else:
            controller.organization = organization
            entry.async_on_unload(organization.async_stop)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when its data is updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_migrate_unique_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Migrate legacy entity unique ids to their corrected form."""

    @callback
    def _migrate(reg_entry: er.RegistryEntry) -> dict[str, str] | None:
        if reg_entry.unique_id.startswith("ip_addresss_"):
            return {
                "new_unique_id": reg_entry.unique_id.replace(
                    "ip_addresss_", "ip_address_", 1
                )
            }
        return None

    await er.async_migrate_entries(hass, entry.entry_id, _migrate)

async def async_unload_entry(hass: HomeAssistant, entry: ESPSomfyConfigEntry) -> bool:
    """Unload a config entry."""
    controller: ESPSomfyController | None = getattr(entry, "runtime_data", None)
    if controller is not None:
        controller.organization = None
        controller.health = None
        controller.cancel_reload()
        await controller.async_stop_probe()
        await controller.ws_close()
        return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return True


def _board_ids(controller: ESPSomfyController, shades: list, groups: list) -> set[str]:
    """Identifiers of the devices the board still has."""
    uid = controller.unique_id
    ids = {uid}
    ids.update(f"shade_{uid}_{s['shadeId']}" for s in shades if "shadeId" in s)
    ids.update(f"group_{uid}_{g['groupId']}" for g in groups if "groupId" in g)
    # Remotes: the ones linked to a shade, and the ones added from Home
    # Assistant (removed with their subentry, never as stale).
    for shade in shades:
        for remote in shade.get("linkedRemotes") or []:
            if address := int(remote.get("remoteAddress", 0) or 0):
                ids.add(f"remote_{uid}_{address}")
    for subentry in controller.config_entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_REMOTE:
            ids.add(f"remote_{uid}_{int(subentry.data[CONF_ADDRESS])}")
    return ids


@callback
def _async_remove_stale_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    controller: ESPSomfyController,
    shades: list,
    groups: list,
) -> None:
    """Drop the devices whose shade or group no longer exists on the board."""
    known = _board_ids(controller, shades, groups)
    prefixes = (
        f"shade_{controller.unique_id}_",
        f"group_{controller.unique_id}_",
        f"remote_{controller.unique_id}_",
    )
    devices = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
        ours = {i for d, i in device.identifiers if d == DOMAIN and i.startswith(prefixes)}
        if ours and not ours & known:
            devices.async_update_device(device.id, remove_config_entry_id=entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Allow deleting a device only once the board no longer has it.

    A shade or group still on the board would come back at the next reload,
    and the board itself is removed with the integration.
    """
    controller: ESPSomfyController | None = getattr(config_entry, "runtime_data", None)
    if controller is None:
        return True
    known = _board_ids(controller, controller.api.shades, controller.api.groups)
    return not any(d == DOMAIN and i in known for d, i in device_entry.identifiers)
