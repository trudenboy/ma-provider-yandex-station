"""Yandex Station Player Provider — device discovery and lifecycle."""

from __future__ import annotations

import ipaddress
import logging
from typing import TYPE_CHECKING, Any

from aiohttp import ClientSession
from ya_passport_auth import PassportClient, SecretStr

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
    from zeroconf import ServiceStateChange
    from zeroconf.asyncio import AsyncServiceInfo

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
        self._passport_client: PassportClient | None = None
        self._pending_discoveries: set[str] = set()
        self._mdns_players: dict[str, str] = {}  # mDNS service name → player_id
        self._discovery_done = False

    async def _init_session(self) -> bool:
        """Initialize Yandex HTTP session and login. Return True on success."""
        x_token_val = self.config.get_value(CONF_X_TOKEN)
        music_token_val = self.config.get_value(CONF_MUSIC_TOKEN)

        if not x_token_val:
            self.logger.warning("No x_token configured, cannot discover devices")
            return False

        x_token = SecretStr(str(x_token_val))
        music_token = SecretStr(str(music_token_val)) if music_token_val else None

        self._http_session = ClientSession()
        self._passport_client = PassportClient(session=self._http_session)
        self._session = YandexSession(
            self._http_session,
            self._passport_client,
            x_token=x_token,
            music_token=music_token,
        )

        try:
            logged_in = await self._session.login_token()
            if not logged_in:
                self.logger.error("Failed to login with x_token — cannot discover devices")
                await self._cleanup_session()
                return False
            await self._session.ensure_music_token()
        except Exception:
            self.logger.exception("Error during token login")
            await self._cleanup_session()
            return False

        return True

    async def _cleanup_session(self) -> None:
        """Close HTTP session and PassportClient."""
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
        self._http_session = None
        self._passport_client = None
        self._session = None

    async def discover_players(self) -> None:
        """Discover Yandex Station players.

        Two-phase discovery:
        1. Cloud: Quasar API (requires session cookies from x_token)
        2. Local: mDNS (handled by MA core via manifest.json mdns_discovery)
        """
        if self._discovery_done:
            return

        if not await self._init_session():
            return

        # Load device list from Quasar cloud API
        assert self._session is not None  # guaranteed by _init_session()
        self._quasar = YandexQuasar(self._session)
        speakers: list[dict[str, Any]] = []
        try:
            speakers = await self._quasar.get_speakers()
            self.logger.info("Found %d speakers via Quasar API", len(speakers))

            for speaker in speakers:
                if "quasar_info" not in speaker:
                    await self._quasar.load_device_config(speaker)
        except Exception:
            self.logger.exception("Failed to load speakers from Quasar")

        # Register all cloud-discovered speakers as players
        # Enrich with local connection info from glagol API (mDNS fallback)
        local_speakers: dict[str, dict[str, Any]] = {}
        try:
            local_list = await self._quasar.get_local_speakers()
            for ls in local_list:
                local_speakers[ls["device_id"]] = ls
            self.logger.info("Found %d local speakers via Glagol API", len(local_speakers))
        except Exception:
            self.logger.debug("Failed to get local speakers from Glagol API")

        for speaker in speakers:
            qi = speaker.get("quasar_info", {})
            device_id = qi.get("device_id", "")
            if not device_id:
                continue
            player_id = f"ys_{device_id}"
            # Merge local connection info (IP/port from glagol API)
            if device_id in local_speakers:
                ls = local_speakers[device_id]
                speaker.setdefault("host", ls["host"])
                speaker.setdefault("port", ls["port"])
                speaker.setdefault("glagol", ls.get("glagol", {}))
            self.logger.info(
                "Registering speaker: %s [%s]", speaker.get("name"), qi.get("platform")
            )
            await self._create_player(player_id, speaker)

        self._discovery_done = True

    async def on_mdns_service_state_change(
        self,
        name: str,
        state_change: ServiceStateChange,
        info: AsyncServiceInfo | None,
    ) -> None:
        """Handle mDNS discovery callback (called by MA core).

        Note: MA passes info=None for Removed events, so we use a cached
        name→player_id mapping to mark players unavailable.
        """
        from zeroconf import ServiceStateChange  # noqa: PLC0415

        if state_change == ServiceStateChange.Removed:
            player_id = self._mdns_players.get(name)
            if player_id:
                existing = self.mass.players.get_player(player_id)
                if existing and isinstance(existing, YandexStationPlayer):
                    existing._attr_available = False
                    existing.update_state()
                    _LOGGER.debug("Marked player %s unavailable (mDNS removed)", player_id)
            return

        if not info or not info.addresses:
            return

        try:
            properties: dict[str, Any] = {
                k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
                for k, v in info.properties.items()
            }

            device_id = properties.get("deviceId", "")
            platform = properties.get("platform", "")
            host = str(ipaddress.ip_address(info.addresses[0]))
            port = info.port or 0

            if not device_id or not port:
                return

            player_id = f"ys_{device_id}"

            # Cache mDNS name → player_id for Removed events (info=None)
            self._mdns_players[name] = player_id

            if player_id in self._pending_discoveries:
                return

            # Check if player already registered (cloud-discovered) — connect Glagol
            existing = self.mass.players.get_player(player_id)
            if existing and isinstance(existing, YandexStationPlayer):
                if not existing.glagol.connected:
                    existing.update_connection(host, port)
                    await existing.async_setup()
                else:
                    existing.update_connection(host, port)
                return

            self._pending_discoveries.add(player_id)

            device_info: dict[str, Any] = {
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
                            {k: v for k, v in cloud_device.items() if k not in ("host", "port")}
                        )
                        break

            await self._create_player(player_id, device_info)

        except Exception:
            _LOGGER.exception("Error processing mDNS discovery for %s", name)

    async def _create_player(self, player_id: str, device_info: dict[str, Any]) -> None:
        """Create and register a new YandexStationPlayer."""
        try:
            if not self._session:
                # Lazily initialize session for mDNS events arriving before discover_players
                if not await self._init_session():
                    self.logger.warning("Session not initialized, skipping player creation")
                    return

            assert self._session is not None  # guaranteed by _init_session()
            assert self._passport_client is not None  # guaranteed by _init_session()

            # Skip if already registered
            existing = self.mass.players.get_player(player_id)
            if existing is not None:
                return

            glagol = YandexGlagol(self._session, self._passport_client, device_info)

            player = YandexStationPlayer(
                provider=self,
                player_id=player_id,
                device_info=device_info,
                glagol=glagol,
            )
            # Only start Glagol if host/port are available (mDNS or glagol API)
            host = device_info.get("host")
            port = device_info.get("port")
            if host and port:
                self.logger.info("Starting Glagol for %s at %s:%s", player_id, host, port)
                await player.async_setup()
            else:
                self.logger.info("No host/port for %s — cloud-only", player_id)
            await self.mass.players.register_or_update(player)

        except Exception:
            self.logger.exception("Failed to create player %s", player_id)
        finally:
            self._pending_discoveries.discard(player_id)

    async def unload(self, is_removed: bool = False) -> None:
        """Clean up on provider unload."""
        await self._cleanup_session()
