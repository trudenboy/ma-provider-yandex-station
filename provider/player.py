"""Yandex Station Player — transport control and state management."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from music_assistant_models.config_entries import ConfigEntry, ConfigValueType
from music_assistant_models.enums import (
    ConfigEntryType,
    PlaybackState,
    PlayerFeature,
    PlayerType,
)

from music_assistant.constants import CONF_ENTRY_HTTP_PROFILE_DEFAULT_3, CONF_ENTRY_OUTPUT_CODEC
from music_assistant.models.player import DeviceInfo, Player, PlayerMedia

from . import protobuf
from .constants import CONF_VOICE_CONTROL

CONF_ENTRY_VOICE_CONTROL = ConfigEntry(
    key=CONF_VOICE_CONTROL,
    type=ConfigEntryType.BOOLEAN,
    label="Experimental: Voice control integration",
    description=(
        "Auto-resume MA queue after voice commands like 'Алиса, стоп' or 'Алиса, дальше'. "
        "Experimental — may cause unexpected behavior."
    ),
    default_value=False,
    required=False,
    advanced=True,
)

if TYPE_CHECKING:
    from .glagol import YandexGlagol
    from .provider import YandexStationProvider

PROV_LOGGER_BASE = "music_assistant.Yandex Station"
_LOGGER = logging.getLogger(f"{PROV_LOGGER_BASE}.player")


def _external_command(name: str, payload: dict[str, Any] | str | None = None) -> dict[str, Any]:
    """Build an externalCommandBypass command for Glagol."""
    data: dict[int, str] = {1: name}
    if payload:
        data[2] = json.dumps(payload) if isinstance(payload, dict) else payload
    return {
        "command": "externalCommandBypass",
        "data": base64.b64encode(protobuf.dumps(data)).decode(),
    }


def _update_form(name: str, **kwargs: str) -> dict[str, Any]:
    """Build a serverAction command to invoke a named form/scenario."""
    return {
        "command": "serverAction",
        "serverActionEventPayload": {
            "type": "server_action",
            "name": "update_form",
            "payload": {
                "form_update": {
                    "name": name,
                    "slots": [{"type": "string", "name": k, "value": v} for k, v in kwargs.items()],
                },
                "resubmit": True,
            },
        },
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

        # Track external (radio_play) playback since Glagol doesn't report it
        self._external_playing = False
        self._external_media: PlayerMedia | None = None
        # Set after pause of external playback — play() must re-trigger queue
        self._needs_replay = False
        # Track previous alice state to detect LISTENING→IDLE transitions
        self._prev_alice_state: str = ""
        # Timer for auto-resume after voice command
        self._voice_resume_task: asyncio.Task[None] | None = None
        # Voice command analysis: did Alice speak? Was volume changed?
        self._alice_spoke: bool = False
        self._pre_voice_volume: int = 0

        # Static attributes
        self._attr_type = PlayerType.PLAYER
        self._attr_name = device_info.get("name", "Yandex Station")
        self._attr_available = False
        self._attr_powered = True
        self._attr_needs_poll = False  # We get state from WebSocket
        self._attr_supported_features = {
            PlayerFeature.POWER,
            PlayerFeature.PLAY_MEDIA,
            PlayerFeature.PLAY_ANNOUNCEMENT,
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

    async def get_config_entries(
        self,
        action: str | None = None,
        values: dict[str, ConfigValueType] | None = None,
    ) -> list[ConfigEntry]:
        """Return player-specific config entries.

        Yandex Station requires Content-Length in HTTP responses (no chunked encoding),
        so we default to forced_content_length HTTP profile.
        """
        return [
            CONF_ENTRY_OUTPUT_CODEC,
            CONF_ENTRY_HTTP_PROFILE_DEFAULT_3,
            CONF_ENTRY_VOICE_CONTROL,
        ]

    @property
    def _voice_control_enabled(self) -> bool:
        """Whether experimental voice control integration is enabled."""
        return bool(self._config.get_value(CONF_VOICE_CONTROL))

    def update_connection(self, host: str, port: int) -> None:
        """Update connection info when mDNS reports new IP."""
        self._device_info["host"] = host
        self._device_info["port"] = port
        self.glagol.device["host"] = host
        self.glagol.device["port"] = port
        # Trigger reconnect if needed
        self.mass.create_task(self.glagol.start())

    # ── Transport controls ───────────────────────────────────────

    async def power(self, powered: bool) -> None:
        """Power on/off the station.

        Power on: resumes playback via player_continue scenario.
        Power off: sends station to home screen via go_home scenario.
        """
        if powered:
            await self.glagol.send(_update_form("personal_assistant.scenarios.player_continue"))
        else:
            await self.glagol.send(_update_form("personal_assistant.scenarios.quasar.go_home"))
        self._attr_powered = powered
        self.update_state()

    async def play(self) -> None:
        """Send PLAY command.

        After external playback was stopped via Alice, native 'play' has nothing
        to resume.  Re-trigger queue playback through MA instead.
        """
        if self._needs_replay:
            self._needs_replay = False
            queue = self.mass.player_queues.get_active_queue(self.player_id)
            if queue:
                await self.mass.player_queues.resume(queue.queue_id)
                return
        await self.glagol.send({"command": "play"})

    async def pause(self) -> None:
        """Send PAUSE command.

        Glagol 'stop' only affects the native player, not externalCommandBypass.
        Send a radio_play with invalid URL to replace current bypass stream —
        the station will fail to fetch it and stop. Fully local, no cloud needed.
        """
        if self._external_playing:
            await self.glagol.send(
                _external_command("radio_play", {"streamUrl": "http://0.0.0.0/stop.flac"})
            )
            self._needs_replay = True
        else:
            await self.glagol.send({"command": "stop"})
        self._external_playing = False
        self._external_media = None
        self._attr_playback_state = PlaybackState.PAUSED
        self.update_state()

    async def stop(self) -> None:
        """Send STOP command."""
        if self._external_playing:
            await self.glagol.send(
                _external_command("radio_play", {"streamUrl": "http://0.0.0.0/stop.flac"})
            )
        else:
            await self.glagol.send({"command": "stop"})
        self._external_playing = False
        self._external_media = None
        self._attr_playback_state = PlaybackState.IDLE
        self.update_state()

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
        await self.glagol.send({"command": "setVolume", "volume": round(volume_level / 100, 2)})

    async def volume_mute(self, muted: bool) -> None:
        """Mute/unmute. Yandex Station doesn't have native mute, simulate with volume."""
        if muted:
            self._saved_volume = self._attr_volume_level or 0
            await self.volume_set(0)
        elif hasattr(self, "_saved_volume"):
            await self.volume_set(self._saved_volume)
        self._attr_volume_muted = muted
        self.update_state()

    async def play_media(self, media: PlayerMedia) -> None:
        """Play media on the Yandex Station via radio_play command."""
        self._needs_replay = False
        _LOGGER.info("[%s] play_media called: %s", self.player_id, media.title or media.uri)
        stream_url = await self.provider.mass.streams.resolve_stream_url(self.player_id, media)
        _LOGGER.debug("[%s] Stream URL: %s", self.player_id, stream_url)

        payload: dict[str, Any] = {
            "streamUrl": stream_url,
            "force_restart_player": True,
        }

        result = await self.glagol.send(_external_command("radio_play", payload))
        _LOGGER.debug("[%s] radio_play result: %s", self.player_id, result)

        if result and result.get("status") == "SUCCESS":
            # Glagol doesn't update playerState for externalCommandBypass playback,
            # so we set state optimistically.
            self._external_playing = True
            self._external_media = media
            self._attr_playback_state = PlaybackState.PLAYING
            self._attr_powered = True
            self._attr_elapsed_time = 0
            self._attr_elapsed_time_last_updated = time.time()
            self.set_current_media(
                uri=media.uri or "",
                title=media.title or "",
                artist=media.artist or "",
                duration=media.duration or None,
                image_url=media.image_url or None,
            )
            self.update_state()

    async def play_announcement(
        self, announcement: PlayerMedia, volume_level: int | None = None
    ) -> None:
        """Play announcement using Alice's native TTS.

        Extracts text from announcement title and speaks it via repeat_phrase.
        Falls back to streaming the audio URL if no title is available.
        """
        # Adjust volume before announcement if requested
        saved_volume: int | None = None
        if volume_level is not None and volume_level != self._attr_volume_level:
            saved_volume = self._attr_volume_level
            await self.volume_set(volume_level)

        text = announcement.title
        if text:
            _LOGGER.debug("[%s] TTS announcement: %s", self.player_id, text)
            await self.glagol.send_tts(text)
        else:
            # No text available — stream the audio URL directly
            _LOGGER.debug("[%s] Audio announcement: %s", self.player_id, announcement.uri)
            await self.glagol.send(
                _external_command(
                    "radio_play",
                    {"streamUrl": announcement.uri, "force_restart_player": True},
                )
            )

        # Restore volume after a brief delay for TTS to start
        if saved_volume is not None:
            await asyncio.sleep(3)
            await self.volume_set(saved_volume)

    async def on_unload(self) -> None:
        """Clean up on player unload."""
        if self._voice_resume_task:
            self._voice_resume_task.cancel()
        await super().on_unload()
        await self.glagol.stop()

    async def _delayed_resume(self) -> None:
        """Auto-resume MA queue after a voice command that didn't start native player."""
        try:
            await asyncio.sleep(3)
            if self._needs_replay:
                _LOGGER.info("[%s] Auto-resuming MA queue after voice command", self.player_id)
                self._needs_replay = False
                queue = self.mass.player_queues.get_active_queue(self.player_id)
                if queue:
                    await self.mass.player_queues.resume(queue.queue_id)
        except asyncio.CancelledError:
            pass
        finally:
            self._voice_resume_task = None

    # ── State updates from Glagol WebSocket ──────────────────────

    def _handle_voice_interrupt(self, alice_state: str) -> None:
        """Handle Alice activation during bypass playback."""
        _LOGGER.info(
            "[%s] Alice active (%s) during bypass — pausing MA queue",
            self.player_id,
            alice_state,
        )
        self._external_playing = False
        self._external_media = None
        self._needs_replay = True
        self._attr_playback_state = PlaybackState.PAUSED
        self._alice_spoke = False
        self._pre_voice_volume = self._attr_volume_level or 0
        if self._voice_resume_task:
            self._voice_resume_task.cancel()
            self._voice_resume_task = None

    def _handle_voice_end(self, alice_state: str) -> None:
        """Handle end of voice interaction — decide whether to auto-resume."""
        if alice_state == "SPEAKING":
            self._alice_spoke = True

        if (
            self._prev_alice_state in ("LISTENING", "SPEAKING")
            and alice_state == "IDLE"
            and not self._voice_resume_task
        ):
            current_volume = self._attr_volume_level or 0
            volume_changed = current_volume != self._pre_voice_volume

            if self._alice_spoke or volume_changed:
                reason = "speech" if self._alice_spoke else "volume change"
                _LOGGER.info(
                    "[%s] Voice command ended (%s) — scheduling auto-resume",
                    self.player_id,
                    reason,
                )
                self._voice_resume_task = asyncio.create_task(self._delayed_resume())
            else:
                _LOGGER.info("[%s] Silent voice command — staying paused", self.player_id)
                self._needs_replay = True

    def _update_playback_state(self, playing: bool, alice_state: str) -> None:
        """Update playback state from Glagol data."""
        if self._external_playing:
            if self._voice_control_enabled and alice_state not in ("IDLE", ""):
                self._handle_voice_interrupt(alice_state)
            else:
                self._attr_playback_state = PlaybackState.PLAYING
                self._attr_powered = True
        elif playing:
            if self._needs_replay:
                _LOGGER.info(
                    "[%s] Native player active after voice cmd — accepting",
                    self.player_id,
                )
                self._needs_replay = False
                if self._voice_resume_task:
                    self._voice_resume_task.cancel()
                    self._voice_resume_task = None
            self._attr_playback_state = PlaybackState.PLAYING
            self._attr_powered = True
        else:
            if self._voice_control_enabled and self._needs_replay:
                self._handle_voice_end(alice_state)
            if self._attr_playback_state == PlaybackState.PLAYING:
                self._attr_playback_state = PlaybackState.IDLE

    def _on_glagol_update(self, data: dict[str, Any] | None) -> None:
        """Handle state update from Glagol WebSocket.

        Called from the WebSocket receive loop (already in asyncio context).
        """
        if data is None:
            self._attr_available = False
            self.update_state()
            return

        self._attr_available = True

        state = data.get("state", {})
        if not state:
            _LOGGER.debug(
                "[%s] No 'state' in Glagol data, keys: %s", self.player_id, list(data.keys())
            )
            return

        player_state = state.get("playerState", {})
        playing = state.get("playing", False)
        extra = player_state.get("extra", {})

        _LOGGER.debug(
            "[%s] playing=%s vol=%s prog=%s dur=%s title=%s extra=%s alice=%s",
            self.player_id,
            playing,
            state.get("volume"),
            player_state.get("progress"),
            player_state.get("duration"),
            (player_state.get("title", "") or "")[:30],
            list(extra.keys()) if extra else None,
            state.get("aliceState"),
        )

        # Volume (0.0-1.0 → 0-100)
        if "volume" in state:
            self._attr_volume_level = round(state["volume"] * 100)

        alice_state = state.get("aliceState", "")

        self._update_playback_state(playing, alice_state)

        self._prev_alice_state = alice_state

        # Power detection from alice state (only when not in external playback)
        if not self._external_playing:
            if alice_state == "IDLE" and not playing:
                self._attr_powered = self._attr_powered  # keep user-set value
            else:
                self._attr_powered = True

        # Elapsed time
        progress = player_state.get("progress", 0)
        duration = player_state.get("duration", 0)

        if self._external_playing and self._external_media:
            # Glagol reports stale progress/media from native player.
            # Keep our optimistic elapsed_time ticking and use external media info.
            self.set_current_media(
                uri=self._external_media.uri or "",
                title=self._external_media.title or "",
                artist=self._external_media.artist or "",
                duration=self._external_media.duration or None,
                image_url=self._external_media.image_url or None,
            )
        else:
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
