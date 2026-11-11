"""Config flow for ESPSomfy RTS."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import zeroconf
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PIN,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util.network import is_host_valid

from .const import (
    CONF_ADDRESS,
    CONF_MAX_BACKUPS,
    CONF_SYNC_ORGANIZATION,
    DEFAULT_MAX_BACKUPS,
    DEFAULT_SYNC_ORGANIZATION,
    DOMAIN,
    MAX_BACKUPS,
    MIN_BACKUPS,
    SUBENTRY_REMOTE,
)

# Seconds the board listens for the remote to add.
LEARN_TIMEOUT = 30

# Settings kept in the entry options; everything else goes to the entry data.
OPTION_KEYS = (CONF_MAX_BACKUPS, CONF_SYNC_ORGANIZATION)
from .adopt import previous_entry
from .controller import (
    DiscoveryError,
    ESPSomfyAPI,
    ESPSomfyController,
    InvalidHost,
    LoginError,
)

_LOGGER = logging.getLogger(__name__)


# The ConfigFlow is only accessed when first setting up the integration.  This simply
# collects the initial data from the user to determine whether the integration can
# be installed.
class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configuration flow for ESPSomfyController."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self.controller: ESPSomfyController
        self.zero_conf: zeroconf.ZeroconfServiceInfo
        self.server_id = None
        self.host = None

    @callback
    def _show_setup_form(
        self,
        user_input: dict[str, Any] | None = None,
        errors: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Show the setup form to the user."""
        host = user_input.get(CONF_HOST, self.host) if user_input else ""
        return self.async_show_form(
            step_id="user",
            data_schema=_get_data_schema(self.hass, data=user_input, host=host),
            errors=errors,
        )

    async def _finish(self, title: str, data: dict[str, Any]) -> FlowResult:
        """Create the entry, or first offer to take over an earlier integration.

        When the same board is set up under an earlier ESPSomfy-RTS integration,
        the user is asked whether to move its entities and devices here; nothing
        is touched otherwise. Credentials are never read from the other entry.
        """
        self._title = title
        self._data = data
        old = previous_entry(self.hass, self.unique_id)
        if old is None:
            return self.async_create_entry(title=title, data=data)
        self._adopt_from = old.entry_id
        return await self.async_step_adopt()

    async def async_step_adopt(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask whether to take over an earlier ESPSomfy-RTS integration."""
        old = self.hass.config_entries.async_get_entry(self._adopt_from)
        if old is None:
            return self.async_create_entry(title=self._title, data=self._data)
        if user_input is not None:
            data = dict(self._data)
            if user_input["adopt"]:
                # A one-shot marker: async_setup_entry moves the registry
                # entries and removes the old entry, then clears it.
                data["adopt_from"] = self._adopt_from
            return self.async_create_entry(title=self._title, data=data)
        entities = len(er.async_entries_for_config_entry(er.async_get(self.hass), old.entry_id))
        devices = len(dr.async_entries_for_config_entry(dr.async_get(self.hass), old.entry_id))
        return self.async_show_form(
            step_id="adopt",
            data_schema=vol.Schema({vol.Required("adopt", default=True): bool}),
            description_placeholders={
                "name": old.title,
                "entities": str(entities),
                "devices": str(devices),
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the flow initialized by the user."""

        errors = {}
        if user_input is not None:
            try:
                if not is_host_valid(user_input.get(CONF_HOST, "")):
                    raise InvalidHost
                self.host = user_input.get(CONF_HOST, "")
                api = ESPSomfyAPI(self.hass, 0, user_input)
                await api.discover()
                await self.async_set_unique_id(f"espsomfy_{api.server_id}")
                self._abort_if_unique_id_configured(updates={CONF_HOST: self.host})
                await api.login(
                    {
                        "username": user_input.get(CONF_USERNAME, ""),
                        "password": user_input.get(CONF_PASSWORD, ""),
                        "pin": user_input.get(CONF_PIN, ""),
                    }
                )
                return await self._finish(api.deviceName, dict(user_input))
            except InvalidHost:
                errors[CONF_HOST] = "invalid_host"
            except (aiohttp.ClientError, OSError, TimeoutError):
                errors["base"] = "cannot_connect"
            except DiscoveryError:
                errors[CONF_HOST] = "discovery_error"
            except LoginError as ex:
                if len(ex.args) >= 2:
                    errors[ex.args[0]] = ex.args[1]
                else:
                    errors["base"] = "login_error"
        return self._show_setup_form(user_input=user_input, errors=errors)

    async def async_step_zeroconf(
        self, discovery_info: zeroconf.ZeroconfServiceInfo
    ) -> FlowResult:
        """Handle zeroconf discovery."""
        self.zero_conf = discovery_info

        # Check if already configured
        self.server_id = discovery_info.properties.get("serverId", "")
        # This was part of PR#54 and was incorrect the server id is simply the chip id of the ESP32 but could
        # be replicated by other items.  If this server id is already configured then we do not want
        # to add the device again.  Since the unique id contains the server id this will always be the same
        # as identified by the chip id on the ESP32.
        # await self.async_set_unique_id(f"{self.server_id}")
        self.host = discovery_info.host
        await self.async_set_unique_id(f"espsomfy_{self.server_id}")

        self._abort_if_unique_id_configured(
            updates={CONF_HOST: discovery_info.host}, reload_on_update=True
        )
        self.context.update(
            {
                "title_placeholders": {
                    CONF_NAME: discovery_info.hostname,
                    CONF_HOST: discovery_info.host,
                    "model": discovery_info.properties.get("model", ""),
                    "configuration_url": f"http://{discovery_info.host}",
                },
            }
        )
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initiated by zeroconf."""
        if user_input is not None:
            return await self._finish(
                self.zero_conf.hostname, {CONF_HOST: self.zero_conf.host}
            )

        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={
                CONF_NAME: self.zero_conf.hostname,
                "model": self.zero_conf.properties.get("model", ""),
                "server_id": self.server_id,
            },
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle reauthentication when the device rejects the credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for new credentials and validate them against the device."""
        errors: dict[str, Any] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if user_input is not None and entry is not None:
            data = {**entry.data, **user_input}
            try:
                api = ESPSomfyAPI(self.hass, 0, data)
                await api.discover()
                await api.login(
                    {
                        "username": data.get(CONF_USERNAME, ""),
                        "password": data.get(CONF_PASSWORD, ""),
                        "pin": data.get(CONF_PIN, ""),
                    }
                )
                self.hass.config_entries.async_update_entry(entry, data=data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            except (aiohttp.ClientError, OSError, TimeoutError):
                errors["base"] = "cannot_connect"
            except DiscoveryError:
                errors["base"] = "discovery_error"
            except LoginError as ex:
                if len(ex.args) >= 2:
                    errors[ex.args[0]] = ex.args[1]
                else:
                    errors["base"] = "login_error"
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_USERNAME): str,
                    vol.Optional(CONF_PASSWORD): str,
                    vol.Optional(CONF_PIN): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for espsomfy_rts_companion."""
        return ESPSomfyOptionsFlowHandler(config_entry)

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: config_entries.ConfigEntry
    ) -> dict[str, type[config_entries.ConfigSubentryFlow]]:
        """A remote the board drives nothing with, adopted as a scene switch."""
        return {SUBENTRY_REMOTE: RemoteSubentryFlow}


class RemoteSubentryFlow(config_entries.ConfigSubentryFlow):
    """Add a remote: press one of its buttons, then name it."""

    def __init__(self) -> None:
        """Initialize."""
        self._listen: asyncio.Task | None = None
        self._address: int | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.SubentryFlowResult:
        """Listen for a press of a remote neither linked nor added yet."""
        entry = self._get_entry()
        if entry.state is not config_entries.ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        controller: ESPSomfyController = entry.runtime_data
        if not controller.api.remote_events:
            return self.async_abort(reason="firmware_too_old")
        if self._listen is None:
            added = {
                int(subentry.data[CONF_ADDRESS])
                for subentry in entry.subentries.values()
                if subentry.subentry_type == SUBENTRY_REMOTE
            }
            # Listening starts now, not when the task first runs: a press right
            # after the dialog opened is not lost.
            heard = controller.async_listen_new_remote(added)

            async def _wait() -> int | None:
                try:
                    return await asyncio.wait_for(heard, LEARN_TIMEOUT)
                except TimeoutError:
                    return None

            self._listen = self.hass.async_create_background_task(
                _wait(), "espsomfy_rts_learn_remote"
            )
        if not self._listen.done():
            return self.async_show_progress(
                step_id="user",
                progress_action="press_remote",
                progress_task=self._listen,
            )
        self._address = self._listen.result()
        self._listen = None
        if self._address is None:
            return self.async_show_progress_done(next_step_id="not_heard")
        return self.async_show_progress_done(next_step_id="name")

    async def async_step_not_heard(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.SubentryFlowResult:
        """Nothing heard: listen again on submit."""
        if user_input is not None:
            return await self.async_step_user()
        return self.async_show_form(step_id="not_heard", data_schema=vol.Schema({}))

    async def async_step_name(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.SubentryFlowResult:
        """Name the remote heard; it becomes a device."""
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={CONF_ADDRESS: self._address},
                unique_id=str(self._address),
            )
        return self.async_show_form(
            step_id="name",
            data_schema=vol.Schema({vol.Required(CONF_NAME): str}),
            description_placeholders={"address": str(self._address)},
        )


class ESPSomfyOptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow for espsomfy_rts_companion component."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the OptionsFlow."""
        self._config_entry = config_entry
        self._errors: dict[str, Any] = {}
        self._host = (
            config_entry.data.get(CONF_HOST, "")
            if config_entry and config_entry.data
            else ""
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure options for espsomfy_rts_companion."""
        errors = {}
        if user_input is not None:
            # The connection settings live in the entry data, the backup
            # retention and the synchronisation are true options.
            data = {k: v for k, v in user_input.items() if k not in OPTION_KEYS}
            options = {
                CONF_MAX_BACKUPS: user_input.get(
                    CONF_MAX_BACKUPS, self._max_backups()
                ),
                CONF_SYNC_ORGANIZATION: bool(
                    user_input.get(CONF_SYNC_ORGANIZATION, self._sync_organization())
                ),
            }
            try:
                if not is_host_valid(data[CONF_HOST]):
                    raise InvalidHost
                api = ESPSomfyAPI(self.hass, 0, data)
                await api.discover()
                await api.login(
                    {
                        "username": data.get(CONF_USERNAME, ""),
                        "password": data.get(CONF_PASSWORD, ""),
                        "pin": data.get(CONF_PIN, ""),
                    }
                )
                # Update config entry with data from user input
                self.hass.config_entries.async_update_entry(
                    self._config_entry, title=api.deviceName, data=data
                )
                return self.async_create_entry(
                    title=api.deviceName,
                    data=options,
                )
            except InvalidHost:
                errors[CONF_HOST] = "invalid_host"
            except (aiohttp.ClientError, OSError, TimeoutError):
                errors["base"] = "cannot_connect"
            except DiscoveryError:
                errors[CONF_HOST] = "discovery_error"
            except LoginError as ex:
                if len(ex.args) >= 2:
                    errors[ex.args[0]] = ex.args[1]
                else:
                    errors["base"] = "login_error"

        return self.async_show_form(
            step_id="init",
            data_schema=_get_data_schema(
                self.hass, data=self._config_entry.data, host=self._host
            ).extend(
                {
                    vol.Optional(
                        CONF_MAX_BACKUPS, default=self._max_backups()
                    ): vol.All(
                        vol.Coerce(int), vol.Range(min=MIN_BACKUPS, max=MAX_BACKUPS)
                    ),
                    vol.Optional(
                        CONF_SYNC_ORGANIZATION, default=self._sync_organization()
                    ): bool,
                }
            ),
            errors=errors,
        )

    def _max_backups(self) -> int:
        """Current retention, the default for entries created before the option."""
        return int(
            self._config_entry.options.get(CONF_MAX_BACKUPS, DEFAULT_MAX_BACKUPS)
        )

    def _sync_organization(self) -> bool:
        """Whether rooms and groups follow the board, on unless turned off."""
        return bool(
            self._config_entry.options.get(
                CONF_SYNC_ORGANIZATION, DEFAULT_SYNC_ORGANIZATION
            )
        )


def _get_data_schema(
    hass: HomeAssistant,
    data: dict[str, Any] | None = None,
    host: str = "",
) -> vol.Schema:
    """Get a schema with default values."""
    # If tracking home or no config entry is passed in, default value come from Home location
    if data is None or data.get(CONF_HOST, host) == "":
        return vol.Schema(
            {
                vol.Required(CONF_HOST, default=host): str,
                vol.Optional(CONF_USERNAME, description={"suggested_value": ""}): str,
                vol.Optional(CONF_PASSWORD, description={"suggested_value": ""}): str,
                vol.Optional(CONF_PIN, description={"suggested_value": ""}): str,
            }
        )
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=data.get(CONF_HOST)): str,
            vol.Optional(
                CONF_USERNAME,
                description={"suggested_value": data.get(CONF_USERNAME, None)},
            ): str,
            vol.Optional(
                CONF_PASSWORD,
                description={"suggested_value": data.get(CONF_PASSWORD, None)},
            ): str,
            vol.Optional(
                CONF_PIN,
                description={"suggested_value": data.get(CONF_PIN, None)},
            ): str,
        }
    )
