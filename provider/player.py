"""Yandex Station Player — transport control and state management."""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from music_assistant_models.enums import (
    PlayerFeature,
    PlayerType,
    PlaybackState,
)
from music_assistant_models.player import PlayerSource

from music_assistant.models.player import DeviceInfo, Player, PlayerMedia

from . import protobuf

if TYPE_CHECKING:
    from .glagol import YandexGlagol
    from .provider import YandexStationProvider

_LOGGER = logging.getLogger(__name__)


def _external_command(name: str, payload: dict[str, Any] | str | None = None) -> dict:
    """Build an externalCommandBypass command for Glagol."""
    data: dict[int, str] = {1: name}
    if payload:
        data[2] = json.dumps(payload) if isinstance(payload, dict) else payload
    return {
        "command": "externalCommandBypass",
        "data": base64.b64encode(protobuf.dumps(data)).decode(),
    }


class YandexStationPlayer(Player):
    """Represents a single Yandex Station smart speaker."""

    def __init__(
        self,
        provider: YandexStationProvider,
        player_id: str,
        device_info: dict[str, Any],
        glagol: YandexGlagol,
    ) -> None:
        """Initialize the player."""
        super().__init__(provider, player_id)
        self._device_info = device_info
        self.glagol = glagol

        # Static attributes
        self._attr_type = PlayerType.PLAYER
        self._attr_name = device_info.get("name", "Yandex Station")
        self._attr_available = False
        self._attr_powered = True  # Yandex Station is always powered on
        self._attr_needs_poll = False  # We get state from WebSocket
        self._attr_supported_features = {
            PlayerFeature.PLAY_MEDIA,
            PlayerFeature.VOLUME_SET,
            PlayerFeature.VOLUME_MUTE,
            PlayerFeature.PAUSE,
            PlayerFeature.NEXT_PREVIOUS,
            PlayerFeature.SEEK,
        }
        self._attr_device_info = DeviceInfo(
            model=device_info.get("quasar_info", {}).get("platform", "unknown"),
            manufacturer="Yandex",
        )

    async def async_setup(self) -> None:
        """Set up the Glagol WebSocket connection."""
        self.glagol.update_handler = self._on_glagol_update
        await self.glagol.start()

    def update_connection(self, host: str, port: int) -> None:
        """Update connection info when mDNS reports new IP."""
        self._device_info["host"] = host
        self._device_info["port"] = port
        self.glagol.device["host"] = host
        self.glagol.device["port"] = port
        # Trigger reconnect if needed
        self.mass.create_task(self.glagol.start())

    # ── Transport controls ───────────────────────────────────────

    async def play(self) -> None:
        """Send PLAY command."""
        await self.glagol.send({"command": "play"})

    async def pause(self) -> None:
        """Send PAUSE command."""
        await self.glagol.send({"command": "stop"})

    async def stop(self) -> None:
        """Send STOP command."""
        await self.glagol.send({"command": "stop"})

    async def next_track(self) -> None:
        """Send NEXT command."""
        await self.glagol.send({"command": "next"})

    async def previous_track(self) -> None:
        """Send PREVIOUS command."""
        await self.glagol.send({"command": "prev"})

    async def seek(self, position: int) -> None:
        """Seek to position in seconds."""
        await self.glagol.send({"command": "rewind", "position": position})

    async def volume_set(self, volume_level: int) -> None:
        """Set volume level (0-100)."""
        await self.glagol.send(
            {"command": "setVolume", "volume": round(volume_level / 100, 2)}
        )

    async def volume_mute(self, muted: bool) -> None:
        """Mute/unmute. Yandex Station doesn't have native mute, simulate with volume."""
        if muted:
            self._saved_volume = self._attr_volume_level
            await self.volume_set(0)
        elif hasattr(self, "_saved_volume"):
            await self.volume_set(self._saved_volume)

    async def play_media(self, media: PlayerMedia) -> None:
        """Play media on the Yandex Station via radio_play command."""
        stream_url = await self.provider.mass.streams.resolve_stream_url(
            self.player_id, media
        )

        payload: dict[str, Any] = {
            "streamUrl": stream_url,
            "force_restart_player": True,
        }
        if media.title:
            payload["title"] = media.title
        if media.image_url and media.image_url.startswith("https://"):
            # Yandex expects image URL without protocol prefix
            payload["imageUrl"] = media.image_url[8:]

        await self.glagol.send(_external_command("radio_play", payload))

    async def on_unload(self) -> None:
        """Clean up on player unload."""
        await super().on_unload()
        await self.glagol.stop()

    # ── State updates from Glagol WebSocket ──────────────────────

    def _on_glagol_update(self, data: dict | None) -> None:
        """Handle state update from Glagol WebSocket.

        Called from the WebSocket receive loop (already in asyncio context).
        """
        if data is None:
            # Disconnected
            self._attr_available = False
            self.update_state()
            return

        self._attr_available = True

        state = data.get("state", {})

        # Volume (0.0-1.0 → 0-100)
        if "volume" in state:
            self._attr_volume_level = round(state["volume"] * 100)

        # Player state
        player_state = state.get("playerState", {})
        playing = state.get("playing", False)

        if playing:
            self._attr_playback_state = PlaybackState.PLAYING
        elif player_state.get("progress", 0) > 0:
            self._attr_playback_state = PlaybackState.PAUSED
        else:
            self._attr_playback_state = PlaybackState.IDLE

        # Elapsed time
        progress = player_state.get("progress", 0)
        duration = player_state.get("duration", 0)

        self._attr_elapsed_time = progress
        self._attr_elapsed_time_last_updated = time.time()

        # Current media info
        title = player_state.get("title")
        subtitle = player_state.get("subtitle")

        if title or playing:
            self.set_current_media(
                uri=player_state.get("id", ""),
                title=title or "",
                artist=subtitle or "",
                duration=int(duration) if duration else None,
            )
        elif not playing:
            self._attr_current_media = None

        self.update_state()
