"""Yandex Quasar — cloud API for device discovery and fallback commands.

Adapted from AlexxIT/YandexStation (MIT license).
Stripped of Home Assistant dependencies; uses pure aiohttp.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .constants import QUASAR_DEVICES_URL

if TYPE_CHECKING:
    from .session import YandexSession

_LOGGER = logging.getLogger(__name__)

# Mapping from Russian UID chars to English hex for scenario triggers
MASK_EN = "0123456789abcdef-"
MASK_RU = "оеаинтсрвлкмдпуяы"


def _encode_uid(uid: str) -> str:
    """Encode device UID to Russian chars (Yandex scenario trigger format)."""
    return "".join(MASK_RU[MASK_EN.index(s)] for s in uid)


class YandexQuasar:
    """Yandex Quasar cloud API client for device discovery."""

    devices: list[dict[str, Any]] | None = None

    def __init__(self, session: YandexSession) -> None:
        """Initialize with an authenticated session."""
        self.session = session

    async def get_devices(self) -> list[dict[str, Any]]:
        """Fetch all devices from Quasar IoT API."""
        _LOGGER.debug("Fetching device list from Quasar")
        r = await self.session.get(QUASAR_DEVICES_URL, timeout=15)
        resp = await r.json()
        if resp.get("status") != "ok":
            msg = f"Failed to get devices: {resp}"
            raise RuntimeError(msg)

        devices: list[dict[str, Any]] = []
        for house in resp.get("households", []):
            devices.extend(
                {**device, "house_name": house.get("name", "")} for device in house.get("all", [])
            )

        self.devices = devices
        return devices

    async def get_speakers(self) -> list[dict[str, Any]]:
        """Get only speaker devices (those with quasar_info)."""
        devices = await self.get_devices()
        return [d for d in devices if "quasar_info" in d]

    async def load_device_config(self, device: dict[str, Any]) -> None:
        """Load device_id and platform from device config (not in main list)."""
        device_cloud_id = device.get("id")
        if not device_cloud_id:
            return
        r = await self.session.get(
            f"https://iot.quasar.yandex.ru/m/user/devices/{device_cloud_id}/configuration"
        )
        resp = await r.json()
        if resp.get("status") == "ok" and "quasar_info" in resp:
            device["quasar_info"] = resp["quasar_info"]

    async def get_local_speakers(self) -> list[dict[str, Any]]:
        """Get device list via Glagol device_list API (includes IP/port)."""
        try:
            r = await self.session.get("https://quasar.yandex.net/glagol/device_list")
            resp = await r.json()
            return [
                {
                    "device_id": d["id"],
                    "name": d["name"],
                    "platform": d["platform"],
                }
                for d in resp.get("devices", [])
            ]
        except Exception:
            _LOGGER.exception("Failed to load local speakers")
            return []
