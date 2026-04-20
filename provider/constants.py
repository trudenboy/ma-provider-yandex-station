"""Constants for Yandex Station Player provider."""

from __future__ import annotations

DOMAIN = "yandex_station"

# Config entry keys
CONF_X_TOKEN = "x_token"
CONF_MUSIC_TOKEN = "music_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_REMEMBER_SESSION = "remember_session"
CONF_COOKIE = "cookie"
CONF_COOKIES = "cookies"

# Config action keys
CONF_ACTION_AUTH_DEVICE = "action_auth_device"
CONF_ACTION_AUTH_QR = "action_auth_qr"
CONF_ACTION_AUTH_COOKIES = "action_auth_cookies"
CONF_ACTION_CLEAR_AUTH = "action_clear_auth"
CONF_VOICE_CONTROL = "voice_control"

# Yandex API endpoints
QUASAR_DEVICES_URL = "https://iot.quasar.yandex.ru/m/v3/user/devices"
QUASAR_IOT_URL = "https://iot.quasar.yandex.ru"

# mDNS service type for Yandex Station devices
MDNS_TYPE = "_yandexio._tcp.local."

# WebSocket settings
WS_HEARTBEAT = 55
WS_RECONNECT_BASE_DELAY = 30
WS_RECONNECT_MAX_MULTIPLIER = 10
WS_COMMAND_TIMEOUT = 5

# DDoS protection: minimum interval between Yandex API requests (seconds)
API_REQUEST_INTERVAL = 0.2
