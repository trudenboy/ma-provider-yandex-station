"""Tests for the experimental Alice-playback intercept feature.

When Alice (Yandex voice assistant) starts music on a Station, the intercept
feature stops the Station's native player, resolves the track via the
``yandex_music`` MA music provider, and starts playback on a configured target
player.  Volume / seek / pause changes on the Station mirror to the target.

The feature is gated by two switches: a provider-level master toggle
(``intercept_feature_enabled``, default OFF) and a per-player toggle
(``intercept_enabled``).  Both must be ON for any intercept action to happen.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from music_assistant.providers.yandex_station.player import (
    YandexStationPlayer,
    _parse_yandex_track_id,
)

# ── Fixtures ──────────────────────────────────────────────────────────


def _make_intercept_player(
    *,
    feature_enabled: bool = True,
    per_player_enabled: bool = True,
    target_player_id: str | None = "target_player",
    yandex_music_present: bool = True,
    external_playing: bool = False,
) -> YandexStationPlayer:
    """Build a player with intercept-related state and mocked mass."""
    player = YandexStationPlayer.__new__(YandexStationPlayer)
    player._player_id = "yandex_station_1"
    player._external_playing = external_playing
    player._external_media = None
    player._intercept_active = False
    player._last_intercepted_track_id = None
    player._last_intercept_time = 0.0
    player._last_mirrored_volume = None
    player._last_progress = 0
    player._last_progress_wall = 0.0

    # Mock provider config (master switch) and player config (per-player toggle)
    provider_config = MagicMock()
    provider_config.get_value = MagicMock(return_value=feature_enabled)
    provider = MagicMock()
    provider.config = provider_config
    player._provider = provider

    def _player_cfg_get(key: str, default: object = None) -> object:
        from music_assistant.providers.yandex_station.constants import (
            CONF_INTERCEPT_ENABLED,
            CONF_INTERCEPT_TARGET,
        )
        if key == CONF_INTERCEPT_ENABLED:
            return per_player_enabled
        if key == CONF_INTERCEPT_TARGET:
            return target_player_id
        return default

    player_config = MagicMock()
    player_config.get_value = MagicMock(side_effect=_player_cfg_get)
    player._config = player_config

    # Mock mass with the four touchpoints intercept uses
    mass = MagicMock()
    mass.get_provider = MagicMock(
        return_value=MagicMock() if yandex_music_present else None
    )
    fake_track = MagicMock(name="resolved_track")
    mass.music = MagicMock()
    mass.music.get_item = AsyncMock(return_value=fake_track)
    mass.player_queues = MagicMock()
    mass.player_queues.play_media = AsyncMock()
    mass.players = MagicMock()
    mass.players.cmd_pause = AsyncMock()
    mass.players.cmd_volume_set = AsyncMock()
    mass.players.cmd_seek = AsyncMock()
    player.mass = mass

    # Mock glagol with successful stop
    player.glagol = MagicMock()
    player.glagol.send = AsyncMock(return_value={"status": "SUCCESS"})

    return player


def _state(
    *,
    track_id: str = "12345",
    playing: bool = True,
    volume: float | None = 0.5,
    progress: int = 0,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Build a (state, player_state, playing) tuple for _handle_intercept_tick."""
    player_state = {"id": track_id, "progress": progress, "title": "Some Track"}
    state: dict[str, Any] = {"playerState": player_state, "playing": playing}
    if volume is not None:
        state["volume"] = volume
    return state, player_state, playing


# ── Helper: track_id parser ───────────────────────────────────────────


def test_parse_yandex_track_id_plain() -> None:
    """Plain numeric ID passes through unchanged."""
    assert _parse_yandex_track_id("12345") == "12345"


def test_parse_yandex_track_id_with_album_suffix() -> None:
    """`track:album` form drops the album suffix."""
    assert _parse_yandex_track_id("12345:67890") == "12345"


def test_parse_yandex_track_id_strips_whitespace() -> None:
    """Surrounding whitespace is trimmed."""
    assert _parse_yandex_track_id(" 12345 ") == "12345"


def test_parse_yandex_track_id_empty() -> None:
    """Empty input maps to empty string (callers must guard)."""
    assert _parse_yandex_track_id("") == ""


# ── Toggle / kill switch behaviour ────────────────────────────────────


async def test_intercept_triggers_on_alice_play() -> None:
    """Both switches ON, target set, yandex_music present → full intercept flow."""
    player = _make_intercept_player()
    state, player_state, playing = _state(track_id="12345")

    await player._handle_intercept_tick(state, player_state, playing)

    player.glagol.send.assert_awaited_once_with({"command": "stop"})
    player.mass.music.get_item.assert_awaited_once()
    kwargs = player.mass.music.get_item.await_args.kwargs
    assert kwargs["item_id"] == "12345"
    assert kwargs["provider_instance_id_or_domain"] == "yandex_music"
    player.mass.player_queues.play_media.assert_awaited_once()
    play_kwargs = player.mass.player_queues.play_media.await_args.kwargs
    assert play_kwargs["queue_id"] == "target_player"
    assert player._intercept_active is True
    assert player._last_intercepted_track_id == "12345"


async def test_intercept_master_switch_off() -> None:
    """Provider master toggle OFF → no action, even with per-player ON."""
    player = _make_intercept_player(feature_enabled=False)
    state, player_state, playing = _state()

    # Real entrypoint guard is in _on_glagol_update, but verify _intercept_enabled
    assert player._intercept_enabled is False

    # Simulate the guard explicitly: tick should not be dispatched
    if player._intercept_enabled and player._intercept_target_player_id:
        await player._handle_intercept_tick(state, player_state, playing)

    player.glagol.send.assert_not_awaited()
    player.mass.music.get_item.assert_not_awaited()
    player.mass.player_queues.play_media.assert_not_awaited()


async def test_intercept_disabled_per_player() -> None:
    """Master toggle ON, per-player OFF → no action."""
    player = _make_intercept_player(per_player_enabled=False)

    assert player._intercept_enabled is False


# ── Failure paths ─────────────────────────────────────────────────────


async def test_intercept_no_yandex_music_provider() -> None:
    """Missing yandex_music provider → no stop, no play, just log."""
    player = _make_intercept_player(yandex_music_present=False)
    state, player_state, playing = _state()

    await player._handle_intercept_tick(state, player_state, playing)

    player.glagol.send.assert_not_awaited()
    player.mass.music.get_item.assert_not_awaited()
    player.mass.player_queues.play_media.assert_not_awaited()
    assert player._intercept_active is False


async def test_intercept_no_target_configured() -> None:
    """Target player_id unset → no action."""
    player = _make_intercept_player(target_player_id=None)
    state, player_state, playing = _state()

    await player._handle_intercept_tick(state, player_state, playing)

    player.glagol.send.assert_not_awaited()
    assert player._intercept_active is False


async def test_intercept_during_external_playing() -> None:
    """Our own bypass stream is playing → never intercept (anti-loop)."""
    player = _make_intercept_player(external_playing=True)
    state, player_state, playing = _state()

    await player._handle_intercept_tick(state, player_state, playing)

    player.glagol.send.assert_not_awaited()
    player.mass.music.get_item.assert_not_awaited()


async def test_intercept_dedup_same_track_within_window() -> None:
    """Same track_id within 5s → second call is a no-op."""
    player = _make_intercept_player()
    state, player_state, playing = _state(track_id="999")

    await player._handle_intercept_tick(state, player_state, playing)
    await player._handle_intercept_tick(state, player_state, playing)

    assert player.mass.player_queues.play_media.await_count == 1
    assert player.glagol.send.await_count == 1


async def test_intercept_resolve_failure_keeps_inactive() -> None:
    """If get_item raises, intercept_active stays False so we can retry later."""
    player = _make_intercept_player()
    player.mass.music.get_item = AsyncMock(side_effect=RuntimeError("not found"))
    state, player_state, playing = _state()

    await player._handle_intercept_tick(state, player_state, playing)

    # Stop was sent before the resolve attempt; that's OK
    player.glagol.send.assert_awaited_once()
    player.mass.player_queues.play_media.assert_not_awaited()
    assert player._intercept_active is False


# ── Mirroring ─────────────────────────────────────────────────────────


async def test_volume_mirror_after_intercept() -> None:
    """Volume changes on the Station mirror to the target while active."""
    player = _make_intercept_player()
    state, player_state, _ = _state(track_id="1", volume=0.4)

    # First tick triggers intercept
    await player._handle_intercept_tick(state, player_state, True)
    assert player._intercept_active is True
    # Volume mirror happens in same tick
    player.mass.players.cmd_volume_set.assert_awaited_with("target_player", 40)

    # New tick with same track_id (within debounce) and different volume
    state2, ps2, _ = _state(track_id="1", volume=0.7)
    await player._handle_intercept_tick(state2, ps2, True)
    player.mass.players.cmd_volume_set.assert_awaited_with("target_player", 70)


async def test_volume_mirror_skipped_when_unchanged() -> None:
    """Identical volume in consecutive ticks → only one cmd_volume_set call."""
    player = _make_intercept_player()
    state, player_state, _ = _state(track_id="1", volume=0.5)

    await player._handle_intercept_tick(state, player_state, True)
    await player._handle_intercept_tick(state, player_state, True)

    # exactly one volume command for the value 50
    calls = [c.args for c in player.mass.players.cmd_volume_set.await_args_list]
    assert calls == [("target_player", 50)]


async def test_pause_mirror_on_native_stop() -> None:
    """Native player stops (playing=False) while intercept_active → pause target."""
    player = _make_intercept_player()
    player._intercept_active = True

    state, player_state, _ = _state(track_id="1", playing=False)
    await player._handle_intercept_tick(state, player_state, False)

    player.mass.players.cmd_pause.assert_awaited_once_with("target_player")
    assert player._intercept_active is False


async def test_seek_mirror_on_progress_jump() -> None:
    """Progress jumps far ahead of wall-clock prediction → cmd_seek on target."""
    player = _make_intercept_player()
    # First tick establishes intercept and the progress baseline
    state1, ps1, _ = _state(track_id="1", progress=10)
    await player._handle_intercept_tick(state1, ps1, True)
    assert player._intercept_active is True

    # Same track, but progress jumped to 60 — must be detected as a seek
    state2, ps2, _ = _state(track_id="1", progress=60)
    await player._handle_intercept_tick(state2, ps2, True)

    player.mass.players.cmd_seek.assert_awaited_with("target_player", 60)


# ── Voice interrupt + intercept ───────────────────────────────────────


def test_voice_interrupt_during_intercept_pauses_target() -> None:
    """Alice activates while intercept is active → pause target via cmd_pause."""
    player = _make_intercept_player()
    player._intercept_active = True
    player._attr_volume_level = 30
    captured: list[Any] = []
    player.mass.create_task = MagicMock(side_effect=lambda coro: captured.append(coro))

    player._handle_voice_interrupt("LISTENING")

    # cmd_pause(target) was scheduled via mass.create_task
    player.mass.create_task.assert_called_once()
    # Did NOT touch bypass-related state (since we returned early)
    assert player._external_playing is False
    # Cleanup the never-awaited coroutine to silence warnings
    for coro in captured:
        coro.close()
