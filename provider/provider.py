"""Yandex Station Player Provider — device discovery and lifecycle."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from typing import TYPE_CHECKING, Any

from aiohttp import ClientSession, CookieJar
from music_assistant_models.errors import LoginFailed, ProviderUnavailableError
from ya_passport_auth import PassportClient, SecretStr

from music_assistant.models.player_provider import PlayerProvider

from .auth import refresh_credentials_via_passport, refresh_music_token
from .constants import (
    CONF_MUSIC_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_REMEMBER_SESSION,
    CONF_X_TOKEN,
    MDNS_TYPE,
)
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
        self._reauth_lock: asyncio.Lock = asyncio.Lock()
        self._init_lock: asyncio.Lock = asyncio.Lock()

    # ── Credential cascade ────────────────────────────────────────────

    async def _init_session(self) -> bool:
        """Initialize Yandex HTTP session with credential cascade.

        Returns ``True`` when a working session is established, ``False`` otherwise.

        Cascade steps (each step updates config on success):
          1. Fast-path: if *both* ``music_token`` and ``x_token`` are present,
             validate the session by logging in with x_token (Quasar-cookie
             refresh) and confirming a usable music_token. ``music_token``-only
             configs skip this step and run without validation — Quasar calls
             will surface errors lazily.
          2. If step 1 fails and ``x_token`` exists → ask Passport for a fresh
             music_token.
          3. If step 2 fails and ``refresh_token`` exists (Device Flow only) →
             silently rotate the full credential triple.
          4. Terminal: clear all three config keys and return ``False`` so the
             caller can surface a re-login prompt.

        Respects :const:`CONF_REMEMBER_SESSION`: when False, steps 2-4 are skipped
        because x_token/refresh_token are not stored for throw-away sessions.

        Raises:
            ProviderUnavailableError: Transient failure (network, rate limit)
                while talking to Yandex Passport during silent refresh.
                Stored credentials are preserved so retrying later can succeed.
        """
        # Serialize init: concurrent callers (discover_players + mDNS-triggered
        # _create_player) must not race on self._http_session/self._session. The
        # first to arrive runs the cascade; others await and reuse the result.
        async with self._init_lock:
            music_token_val = self.config.get_value(CONF_MUSIC_TOKEN)
            x_token_val = self.config.get_value(CONF_X_TOKEN)
            refresh_token_val = self.config.get_value(CONF_REFRESH_TOKEN)
            remember_session = self.config.get_value(CONF_REMEMBER_SESSION)
            if remember_session is None:
                remember_session = True

            if not music_token_val and not x_token_val:
                self.logger.warning("No credentials configured, cannot discover devices")
                return False

            # Idempotent: if a previous init already produced a healthy session,
            # reuse it. mDNS-triggered ``_create_player`` may have initialised the
            # session already and started Glagol on top of it — tearing it down
            # here would break those connections.
            if (
                self._session is not None
                and self._http_session is not None
                and not self._http_session.closed
            ):
                return True

            # Close any orphaned HTTP session from a failed init to avoid leaking
            # aiohttp sockets.
            if self._http_session is not None:
                await self._cleanup_session()

            # Dedicated session: Yandex Passport rejects percent-encoded
            # cookies, so we need ``CookieJar(quote_cookie=False)`` — a
            # constructor-only kwarg that can't be applied to ``mass.http_session``.
            # Bare ``aiohttp.ClientSession`` rather than MA's
            # ``create_clientsession`` helper: the helper's connector +
            # ``_default_headers`` override broke Yandex Passport's session
            # refresh redirect chain (HTTP 400) on production stations.
            self._http_session = ClientSession(cookie_jar=CookieJar(quote_cookie=False))
            self._passport_client = PassportClient(session=self._http_session)

            x_token = SecretStr(str(x_token_val)) if x_token_val else None
            music_token = SecretStr(str(music_token_val)) if music_token_val else None
            refresh_token = SecretStr(str(refresh_token_val)) if refresh_token_val else None

            self._session = YandexSession(
                self._http_session,
                self._passport_client,
                x_token=x_token,
                music_token=music_token,
                refresh_token=refresh_token,
            )

            # Step 1 (fast-path): try the stored music_token as-is.
            if music_token and x_token and await self._try_fast_path():
                return True

            # No silent-refresh path available when either:
            #   - Remember session is off (x_token/refresh_token weren't persisted), or
            #   - x_token is missing (e.g. music_token-only config, or already cleared).
            # In both cases run with the music_token as the only credential.
            if not bool(remember_session):
                return await self._finish_without_refresh(
                    music_token is not None, reason="disabled"
                )
            if not x_token:
                return await self._finish_without_refresh(
                    music_token is not None, reason="no_x_token"
                )

            # Steps 2-3: silent refresh via x_token, then refresh_token if present.
            return await self._try_silent_refresh_cascade(x_token, refresh_token)

    async def _try_fast_path(self) -> bool:
        """Try logging in with the stored music_token + x_token."""
        assert self._session is not None
        try:
            if await self._session.login_token():
                await self._session.ensure_music_token()
                return True
        except Exception:
            self.logger.exception("Error logging in with stored x_token")
        return False

    async def _finish_without_refresh(self, has_music_token: bool, reason: str) -> bool:
        """Finalize init when no silent-refresh path is available.

        ``reason`` is used only for log clarity: ``"disabled"`` means Remember
        session is off, ``"no_x_token"`` means x_token isn't stored (e.g. a
        music_token-only config).
        """
        msg_reason = (
            "Remember session disabled"
            if reason == "disabled"
            else "no x_token available for silent refresh"
        )
        if has_music_token:
            self.logger.info("%s — running with music_token only", msg_reason)
            return True
        self.logger.warning("%s and no music_token available — cannot login", msg_reason)
        await self._cleanup_session()
        return False

    async def _try_silent_refresh_cascade(
        self, x_token: SecretStr, refresh_token: SecretStr | None
    ) -> bool:
        """Refresh music_token via x_token, falling back to refresh_token rotation."""
        assert self._session is not None
        try:
            new_music_token = await refresh_music_token(x_token)
        except LoginFailed as err:
            return await self._handle_x_token_expired(x_token, refresh_token, err)
        except ProviderUnavailableError:
            # Transient failure — let it propagate so creds aren't wiped.
            await self._cleanup_session()
            raise
        except asyncio.CancelledError:
            raise
        except Exception as err:
            self.logger.warning("Session token refresh failed (network): %s", type(err).__name__)
            await self._cleanup_session()
            raise ProviderUnavailableError(
                "Unable to refresh music token right now. Please try again later."
            ) from err

        self._session.music_token = new_music_token
        self._update_config_value(CONF_MUSIC_TOKEN, new_music_token.get_secret(), encrypted=True)
        if await self._session.login_token():
            self.logger.info("Refreshed music token from session token")
            return True
        await self._cleanup_session()
        return False

    async def _handle_x_token_expired(
        self,
        x_token: SecretStr,
        refresh_token: SecretStr | None,
        original_err: LoginFailed,
    ) -> bool:
        """React to an expired x_token: rotate via refresh_token or clear creds."""
        if refresh_token:
            try:
                await self._reauth_via_refresh_token(
                    x_token, refresh_token, original_err=original_err
                )
                return True
            except LoginFailed:
                await self._cleanup_session()
                return False
            except ProviderUnavailableError:
                # Transient — don't wipe creds, let the caller retry later.
                await self._cleanup_session()
                raise
        self.logger.warning("Session token expired, clearing credentials")
        self._update_config_value(CONF_MUSIC_TOKEN, None, encrypted=True)
        self._update_config_value(CONF_X_TOKEN, None, encrypted=True)
        self._update_config_value(CONF_REFRESH_TOKEN, None, encrypted=True)
        await self._cleanup_session()
        return False

    async def _reauth_via_refresh_token(
        self,
        x_token: SecretStr,
        refresh_token: SecretStr,
        original_err: Exception | None = None,
    ) -> None:
        """Silently rotate the full credential triple via the refresh_token.

        Device-flow accounts have a refresh_token that can mint a new
        x_token + refresh_token + music_token without user interaction.
        Persists the rotated values and updates the active :class:`YandexSession`.
        """
        try:
            new_creds = await refresh_credentials_via_passport(x_token, refresh_token)
        except LoginFailed as err2:
            self.logger.warning("Session and refresh tokens are both expired")
            self._update_config_value(CONF_MUSIC_TOKEN, None, encrypted=True)
            self._update_config_value(CONF_X_TOKEN, None, encrypted=True)
            self._update_config_value(CONF_REFRESH_TOKEN, None, encrypted=True)
            raise LoginFailed("Session expired. Please re-authenticate.") from err2

        new_music_token = new_creds.music_token
        new_refresh_token = new_creds.refresh_token
        if new_music_token is None or new_refresh_token is None:
            self._update_config_value(CONF_MUSIC_TOKEN, None, encrypted=True)
            self._update_config_value(CONF_X_TOKEN, None, encrypted=True)
            self._update_config_value(CONF_REFRESH_TOKEN, None, encrypted=True)
            raise LoginFailed(
                "Credential refresh returned an incomplete response."
            ) from original_err

        self._update_config_value(CONF_MUSIC_TOKEN, new_music_token.get_secret(), encrypted=True)
        self._update_config_value(CONF_X_TOKEN, new_creds.x_token.get_secret(), encrypted=True)
        self._update_config_value(
            CONF_REFRESH_TOKEN, new_refresh_token.get_secret(), encrypted=True
        )

        if self._session is not None:
            self._session.x_token = new_creds.x_token
            self._session.music_token = new_music_token
            self._session.refresh_token = new_refresh_token
            # Grab fresh session cookies with the new x_token. If cookies don't
            # refresh, the stored creds are still fresh but Quasar will 401 on
            # the next request — surface that to the caller instead of silently
            # reporting success.
            if not await self._session.login_token():
                raise LoginFailed(
                    "Credential refresh succeeded but session cookie refresh failed."
                ) from original_err

        self.logger.info("Re-issued credentials silently from refresh token")

    async def _silent_reauth(self) -> bool:
        """Attempt a silent re-auth after a runtime 401/403 from Quasar.

        Returns ``True`` if credentials were rotated and the session was
        refreshed so the caller can retry its operation; ``False`` if silent
        refresh isn't possible with the currently available credentials (no
        x_token, or x_token+refresh_token both rejected).

        One-retry semantics are enforced by the caller (see
        :meth:`_get_speakers_with_reauth`), not here — this method itself
        will run the refresh cascade every time it's called.
        """
        # Serialize: multiple concurrent 401s should trigger only one refresh.
        # Read tokens inside the lock so we pick up values rotated by a prior
        # waiter instead of acting on stale credentials.
        async with self._reauth_lock:
            x_token_val = self.config.get_value(CONF_X_TOKEN)
            refresh_token_val = self.config.get_value(CONF_REFRESH_TOKEN)
            if not x_token_val:
                return False
            x_token = SecretStr(str(x_token_val))
            # First try x_token → music_token refresh.
            try:
                new_music_token = await refresh_music_token(x_token)
            except LoginFailed:
                if not refresh_token_val:
                    return False
                try:
                    await self._reauth_via_refresh_token(x_token, SecretStr(str(refresh_token_val)))
                    return True
                except LoginFailed:
                    return False
            self._update_config_value(
                CONF_MUSIC_TOKEN, new_music_token.get_secret(), encrypted=True
            )
            if self._session is None:
                return True
            self._session.music_token = new_music_token

            # Refresh cookies too so non-Glagol Quasar requests keep working.
            # If cookie refresh fails (expired x_token), fall back to refresh_token
            # rotation — otherwise the caller would retry against Quasar with
            # stale cookies and hit 401 again.
            try:
                if await self._session.login_token():
                    return True
                self.logger.debug("login_token after silent reauth returned False")
            except Exception:
                self.logger.debug("login_token after silent reauth failed", exc_info=True)

            if not refresh_token_val:
                return False
            try:
                await self._reauth_via_refresh_token(x_token, SecretStr(str(refresh_token_val)))
            except LoginFailed:
                return False
            return True

    async def _cleanup_session(self) -> None:
        """Close HTTP session and PassportClient."""
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
        self._http_session = None
        self._passport_client = None
        self._session = None

    # ── Discovery ─────────────────────────────────────────────────────

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
        try:
            speakers = await self._get_speakers_with_reauth()
            self.logger.info("Found %d speakers via Quasar API", len(speakers))

            for speaker in speakers:
                if "quasar_info" not in speaker:
                    await self._quasar.load_device_config(speaker)
        except Exception:
            # Leave _discovery_done=False so MA can retry on transient API/auth errors
            self.logger.exception("Failed to load speakers from Quasar — will retry later")
            return

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

    async def _get_speakers_with_reauth(self) -> list[dict[str, Any]]:
        """Fetch Quasar speakers with one silent-reauth retry on 401/403."""
        assert self._quasar is not None
        try:
            return await self._quasar.get_speakers()
        except RuntimeError as err:
            msg = str(err)
            if ("401" in msg or "403" in msg) and await self._silent_reauth():
                self.logger.info("Retrying Quasar get_speakers after silent reauth")
                return await self._quasar.get_speakers()
            raise

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
        from zeroconf import ServiceStateChange  # noqa: PLC0415, RUF100

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
            # Register BEFORE starting Glagol.  The WS connect callback can
            # fire `update_handler` very quickly, and the resulting
            # `player.update_state()` would otherwise run for an unknown
            # player and trigger queue/state side-effects on something the
            # players controller doesn't know about yet.
            await self.mass.players.register_or_update(player)
            # Only start Glagol if host/port are available (mDNS or glagol API)
            host = device_info.get("host")
            port = device_info.get("port")
            if host and port:
                self.logger.info("Starting Glagol for %s at %s:%s", player_id, host, port)
                await player.async_setup()
            else:
                self.logger.info("No host/port for %s — cloud-only", player_id)

        except Exception:
            self.logger.exception("Failed to create player %s", player_id)
        finally:
            self._pending_discoveries.discard(player_id)

    async def unload(self, is_removed: bool = False) -> None:
        """Clean up on provider unload."""
        await self._cleanup_session()
