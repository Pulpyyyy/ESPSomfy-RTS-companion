"""Constants for the ESPSomfy RTS integration."""

import json
from pathlib import Path

from homeassistant.const import Platform

# Source de vérité unique : la version vient du manifest (lu à l'import,
# que HA exécute en executor). Plus de désynchro possible entre les deux.
VERSION = "v" + json.loads(
    (Path(__file__).parent / "manifest.json").read_text(encoding="utf-8")
)["version"]
DOMAIN = "espsomfy_rts_companion"
MANUFACTURER = "Pulpyyyy"
API_SHADES = "/shades"
API_GROUPS = "/groups"
API_SHADECOMMAND = "/shadeCommand"
API_GROUPCOMMAND = "/groupCommand"
API_TILTCOMMAND = "/tiltCommand"
API_DISCOVERY = "/discovery"
API_ROOMS = "/rooms"
API_LOGIN = "/login"
API_SETPOSITIONS = "/setPositions"
API_SETSENSOR = "/setSensor"
API_BACKUP = "/backup"
API_REBOOT = "/reboot"
API_RESTORE = "/restore"
EVT_SHADESTATE = "shadeState"
EVT_GROUPSTATE = "groupState"
EVT_GROUPREMOVED = "groupRemoved"
EVT_GROUPADDED = "groupAdded"
EVT_SHADECOMMAND = "shadeCommand"
EVT_SHADEADDED = "shadeAdded"
EVT_SHADEREMOVED = "shadeRemoved"
EVT_ROOMADDED = "roomAdded"
EVT_ROOMREMOVED = "roomRemoved"
EVT_CONNECTED = "connected"
EVT_FWSTATUS = "fwStatus"
EVT_UPDPROGRESS = "updateProgress"
EVT_WIFISTRENGTH = "wifiStrength"
EVT_ETHERNET = "ethernet"
EVT_MEMSTATUS = "memStatus"
# Internal events broadcast by the controller itself, never sent by the
# firmware (the websocket filter would drop them anyway).
EVT_HTTPPROBE = "httpProbe"
EVT_BACKUPDONE = "backupDone"
# Published by the integration itself after reading the radio statistics.
EVT_RADIOHEALTH = "radioHealth"

# Browser installer of the firmware.
FLASHER_URL = "https://pulpyyyy.github.io/ESPSomfy-RTS/"

CONF_MAX_BACKUPS = "max_backups"
# Rooms <-> areas and groups -> labels (see organization.py).
CONF_SYNC_ORGANIZATION = "sync_organization"
DEFAULT_SYNC_ORGANIZATION = True
# Longest room name the board stores.
ROOM_NAME_MAX = 20
DEFAULT_MAX_BACKUPS = 5
MIN_BACKUPS = 1
MAX_BACKUPS = 50

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.COVER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]

# Sections a board restore can bring back (restore_options_t on the firmware).
RESTORE_SECTIONS = ("shades", "settings", "network", "transceiver", "repeaters", "mqtt")

# Home Assistant event bus name for shade commands the board reports.
EVENT_SHADE_COMMAND = "espsomfy-rts_event"
# "Remote", per Home Assistant language, to build a default remote name in
# the event when a command comes from a dedicated remote.
REMOTE_NAME_PREFIX = {
    "en": "Remote",
    "fr": "Télécommande",
    "de": "Fernbedienung",
    "es": "Mando",
}
