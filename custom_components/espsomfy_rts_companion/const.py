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
# A button press or release of any remote the board hears (socket room 1).
EVT_REMOTEHEARD = "remoteHeard"
# Internal events broadcast by the controller itself, never sent by the
# firmware (the websocket filter would drop them anyway).
EVT_HTTPPROBE = "httpProbe"
EVT_BACKUPDONE = "backupDone"
# The board answered /discovery again (boot time, reset reason, MQTT discovery).
EVT_BOARDINFO = "boardInfo"
# Published by the integration itself after reading the radio statistics.
EVT_RADIOHEALTH = "radioHealth"

# Browser installer of the firmware.
FLASHER_URL = "https://pulpyyyy.github.io/ESPSomfy-RTS/"

CONF_MAX_BACKUPS = "max_backups"
# Rooms <-> areas and groups -> labels (see organization.py).
CONF_SYNC_ORGANIZATION = "sync_organization"
DEFAULT_SYNC_ORGANIZATION = True
# Longest room name the board stores, in UTF-8 bytes (not characters).
ROOM_NAME_MAX = 20
DEFAULT_MAX_BACKUPS = 5
MIN_BACKUPS = 1
MAX_BACKUPS = 50

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.COVER,
    Platform.EVENT,
    Platform.NUMBER,
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

# Socket room of the button presses (ROOM_EMIT_REMOTES on the firmware).
SOCK_ROOM_REMOTES = 1
# Bus event of a remote device, read by its device triggers.
EVENT_REMOTE = f"{DOMAIN}_remote"
# Subentry type of a remote adopted from Home Assistant (not linked to a shade).
SUBENTRY_REMOTE = "remote"
CONF_ADDRESS = "address"

# Commands the board reports (translateSomfyCommand), normalized to the values
# the event entities and the trigger filters use.
COMMANDS = {
    "Up": "up",
    "Down": "down",
    "My": "my",
    "My+Up": "my_up",
    "Up+Down": "up_down",
    "My+Down": "my_down",
    "My+Up+Down": "my_up_down",
    "Prog": "prog",
    "Sun Flag": "sun_flag",
    "Flag": "flag",
    "Step Up": "step_up",
    "Step Down": "step_down",
    "Sensor": "sensor",
    "Toggle": "toggle",
    "Favorite": "favorite",
    "Stop": "stop",
}
# Buttons a hand holds down on purpose: they also report a short or a long press.
HOLD_COMMANDS = ("up", "down", "my")
# Held this long, a press is a long press.
LONG_PRESS_SECONDS = 1.0

# Where a command came from. "internal" is the board itself (its web page,
# MQTT, a GPIO); "home_assistant" is a command this integration sent.
SOURCE_HA = "home_assistant"
COMMAND_SOURCES = ["remote", "group", "internal", SOURCE_HA]

# Reset reasons that mean the board crashed rather than restarted on purpose.
CRASH_RESET_REASONS = ("panic", "int_wdt", "task_wdt", "wdt")
