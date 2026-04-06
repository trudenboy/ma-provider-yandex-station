"""Yandex Station Player Provider — device discovery and lifecycle."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from typing import TYPE_CHECKING

from aiohttp import ClientSession

from music_assistant.models.player_provider import PlayerProvider

from .constants import CONF_MUSIC_TOKEN, CONF_X_TOKEN, MDNS_TYPE
from .glagol import YandexGlagol
from .player import YandexStationPlayer
from .quasar import YandexQuasar
from .session import YandexSession

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ProviderConfig
    from music_assistant_models.enums import ProviderFeature
    from music_assistant_models.provider import ProviderManifest
    from zeroconf import ServiceInfo, Zeroconf

    from music_assistant.mass import MusicAssistant

_LOGGER = logging.getLogger(__name__)


class YandexStationProvider(PlayerProvider):
    """Player provider for Yandex Station smart speakers."""

    def __init__(
        self,
        mass: MusicAssistant,
        manifest: ProviderManifest,
        config: ProviderConfig,
        supported_features: set[ProviderFeature],
    ) -> None:
        """Initialize the provider."""
        super().__init__(mass, manifest, config, supported_features)
        self._session: YandexSession | None = None
        self._quasar: YandexQuasar | None = None
        self._http_session: ClientSession | None = None
        self._pending_discoveries: set[str] = set()
        self._discovery_done = False

    async def discover_players(self) -> None:
        """Discover Yandex Station players.

        Two-phase discovery:
        1. mDNS (handled by MA core via manifest.json mdns_discovery)
        2. Quasar API fallback for devices not on local network
        """
        if self._discovery_done:
            return

        # Initialize Yandex session
        x_token = self.config.get_value(CONF_X_TOKEN)
        music_token = self.config.get_value(CONF_MUSIC_TOKEN)

        if not x_token:
            self.logger.warning("No x_token configured, cannot discover devices")
            return

        self._http_session = ClientSession()
        self._session = YandexSession(
            self._http_session, x_token=x_token, music_token=music_token
        )
        await self._session.ensure_music_token()

        # Load device list from Quasar cloud API for metadata
        self._quasar = YandexQuasar(self._session)
        try:
            speakers = await self._quasar.get_speakers()
            self.logger.debug("Found %d speakers via Quasar API", len(speakers))

            # Enrich devices with config (device_id, platform) if missing
            for speaker in speakers:
                if "quasar_info" not in speaker:
                    await self._quasar.load_device_config(speaker)
        except Exception:
            self.logger.exception("Failed to load speakers from Quasar")
            speakers = []

        self._discovery_done = True

    def on_mdns_service_state_change(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        service_info: ServiceInfo | None = None,
    ) -> None:
        """Handle mDNS discovery callback (called by MA core)."""
        if not service_info or not service_info.addresses:
            return

        try:
            properties = {
                k.decode(): v.decode() if isinstance(v, bytes) else v
                for k, v in service_info.properties.items()
            }

            device_id = properties.get("deviceId", "")
            platform = properties.get("platform", "")
            host = str(ipaddress.ip_address(service_info.addresses[0]))
            port = service_info.port

            if not device_id:
                return

            player_id = f"ys_{device_id}"

            if player_id in self._pending_discoveries:
                return

            # Check if player already registered — just update connection info
            existing = self.mass.players.get_player(player_id)
            if existing and isinstance(existing, YandexStationPlayer):
                existing.update_connection(host, port)
                return

            self._pending_discoveries.add(player_id)

            device_info = {
                "quasar_info": {
                    "device_id": device_id,
                    "platform": platform,
                },
                "name": name.replace(f".{MDNS_TYPE}", ""),
                "host": host,
                "port": port,
            }

            # Enrich with Quasar cloud data if available
            if self._quasar and self._quasar.devices:
                for cloud_device in self._quasar.devices:
                    qi = cloud_device.get("quasar_info", {})
                    if qi.get("device_id") == device_id:
                        device_info.update(
                            {
                                k: v
                                for k, v in cloud_device.items()
                                if k not in ("host", "port")
                            }
                        )
                        break

            asyncio.run_coroutine_threadsafe(
                self._create_player(player_id, device_info),
                loop=self.mass.loop,
            )

        except Exception:
            _LOGGER.exception("Error processing mDNS discovery for %s", name)

    async def _create_player(
        self, player_id: str, device_info: dict
    ) -> None:
        """Create and register a new YandexStationPlayer."""
        try:
            if not self._session:
                self.logger.warning("Session not initialized, skipping player creation")
                return

            glagol = YandexGlagol(self._session, device_info)

            player = YandexStationPlayer(
                provider=self,
                player_id=player_id,
                device_info=device_info,
                glagol=glagol,
            )
            await player.async_setup()
            await self.mass.players.register_or_update(player)

        except Exception:
            self.logger.exception("Failed to create player %s", player_id)
        finally:
            self._pending_discoveries.discard(player_id)

    async def unload(self, is_removed: bool = False) -> None:
        """Clean up on provider unload."""
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
