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

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from music_assistant_models.enums import PlayerFeature

from music_assistant.providers.yandex_station.constants import (
    CONF_INTERCEPT_ENABLED,
    CONF_INTERCEPT_TARGET,
)
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
    player._intercept_self_stop_until = 0.0
    player._intercept_lock = asyncio.Lock()
    player._alice_active_pause_sent = False

    # Mock provider config (master switch) and player config (per-player toggle)
    provider_config = MagicMock()
    provider_config.get_value = MagicMock(return_value=feature_enabled)
    provider = MagicMock()
    provider.config = provider_config
    player._provider = provider

    def _player_cfg_get(key: str, default: object = None) -> object:
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
    # Default: target player exists (intercept pre-validation passes).
    mass.players.get_player = MagicMock(return_value=MagicMock(name="target_player_obj"))
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
    alice_state: str = "IDLE",
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Build a (state, player_state, playing) tuple for _handle_intercept_tick."""
    player_state = {"id": track_id, "progress": progress, "title": "Some Track"}
    state: dict[str, Any] = {
        "playerState": player_state,
        "playing": playing,
        "aliceState": alice_state,
    }
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


async def test_intercept_resolve_failure_does_not_silence_station() -> None:
    """If get_item raises, the Station is left playing — never silenced."""
    player = _make_intercept_player()
    player.mass.music.get_item = AsyncMock(side_effect=RuntimeError("not found"))
    state, player_state, playing = _state()

    await player._handle_intercept_tick(state, player_state, playing)

    # Resolve happens FIRST — failure means the Station stays playing.
    player.glagol.send.assert_not_awaited()
    player.mass.player_queues.play_media.assert_not_awaited()
    assert player._intercept_active is False


async def test_intercept_resolved_track_without_uri_skips_handoff() -> None:
    """Resolved track with no uri → log warning, leave Station playing."""
    player = _make_intercept_player()
    bad_track = MagicMock(name="track_no_uri")
    bad_track.uri = None
    player.mass.music.get_item = AsyncMock(return_value=bad_track)
    state, player_state, playing = _state()

    await player._handle_intercept_tick(state, player_state, playing)

    player.glagol.send.assert_not_awaited()
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


async def test_session_survives_lingering_playing_false() -> None:
    """playing=False after intercept must not end the session.

    The Station stays stopped after our intercept; subsequent state updates
    arrive with ``playing=False`` indefinitely.  Treating those as
    "user paused" would kill the session and break the contract that intercept
    survives Alice queries / quiet periods until the next track arrives.
    """
    player = _make_intercept_player()
    player._intercept_active = True
    state, player_state, _ = _state(track_id="X", playing=False)

    await player._handle_intercept_tick(state, player_state, False)

    player.mass.players.cmd_pause.assert_not_awaited()
    assert player._intercept_active is True


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


async def test_alice_speaks_during_intercept_pauses_target_via_dispatcher() -> None:
    """Alice activity arrives via Glagol state — dispatcher pauses target.

    This drives ``_handle_intercept_tick`` (the actual entry point), not the
    bypass-only ``_handle_voice_interrupt`` helper.  The intercept session
    must remain active so a follow-up Alice-initiated track resumes it.
    """
    player = _make_intercept_player()
    player._intercept_active = True

    # Same track_id as last_intercepted → debounce skips re-intercept;
    # Alice activity must still pause the target.
    player._last_intercepted_track_id = "12345"
    player._last_intercept_time = time.time()
    state, player_state, _ = _state(track_id="12345", alice_state="LISTENING")

    await player._handle_intercept_tick(state, player_state, True)

    player.mass.players.cmd_pause.assert_awaited_with("target_player")
    # Session stays open so the next Alice track can resume it
    assert player._intercept_active is True


async def test_alice_idle_during_intercept_does_not_pause_target() -> None:
    """No Alice activity → no spurious pause on the target."""
    player = _make_intercept_player()
    player._intercept_active = True
    player._last_intercepted_track_id = "12345"
    player._last_intercept_time = time.time()
    state, player_state, _ = _state(track_id="12345", alice_state="IDLE")

    await player._handle_intercept_tick(state, player_state, True)

    player.mass.players.cmd_pause.assert_not_awaited()


# ── Stale session / debounce on failure / serialisation ──────────────


async def test_failed_intercept_debounces_to_avoid_log_spam() -> None:
    """Repeated WS ticks for the same failing track → only one resolve attempt.

    Failed lookups must update the debounce timestamp; otherwise every Glagol
    tick (~1Hz) would re-run get_item and emit a fresh warning.
    """
    player = _make_intercept_player()
    player.mass.music.get_item = AsyncMock(side_effect=RuntimeError("not found"))
    state, player_state, _ = _state(track_id="bad")

    await player._handle_intercept_tick(state, player_state, True)
    await player._handle_intercept_tick(state, player_state, True)
    await player._handle_intercept_tick(state, player_state, True)

    assert player.mass.music.get_item.await_count == 1


async def test_target_player_unavailable_does_not_silence_station() -> None:
    """Pre-validation: if get_player(target) returns None, no Glagol stop."""
    player = _make_intercept_player()
    player.mass.players.get_player = MagicMock(return_value=None)
    state, player_state, _ = _state()

    await player._handle_intercept_tick(state, player_state, True)

    player.glagol.send.assert_not_awaited()
    player.mass.player_queues.play_media.assert_not_awaited()


async def test_failed_intercept_on_new_track_ends_stale_session() -> None:
    """A new track that fails to resolve must pause the target from the prior session.

    Otherwise mirror updates from the Station's native fallback playback would
    keep being forwarded to the target that's still on the previous track.
    """
    player = _make_intercept_player()
    # Simulate a prior successful intercept on track A.
    player._intercept_active = True
    player._last_intercepted_track_id = "A"
    player._last_intercept_time = 0.0  # well outside debounce
    # New track B fails to resolve.
    player.mass.music.get_item = AsyncMock(side_effect=RuntimeError("nope"))
    state, player_state, _ = _state(track_id="B")

    await player._handle_intercept_tick(state, player_state, True)

    player.mass.players.cmd_pause.assert_awaited_with("target_player")
    assert player._intercept_active is False


async def test_handoff_failure_clears_intercept_active() -> None:
    """Failed handoff after stop must clear intercept_active.

    Otherwise mirror code would forward state to a target that isn't playing.
    """
    player = _make_intercept_player()
    player.mass.player_queues.play_media = AsyncMock(side_effect=RuntimeError("boom"))
    state, player_state, _ = _state()

    await player._handle_intercept_tick(state, player_state, True)

    # Stop did fire (resolve succeeded), but handoff failed.
    player.glagol.send.assert_awaited_once()
    assert player._intercept_active is False


async def test_session_end_clears_debounce_for_quick_resume() -> None:
    """End of session must clear the debounce for quick same-track resumes.

    Otherwise a follow-up of the same track within 5s would be debounced and
    left playing on the Station instead of being handed back to the target.
    """
    player = _make_intercept_player()
    player._intercept_active = True
    player._last_intercepted_track_id = "X"
    player._last_intercept_time = time.time()

    await player._pause_target(clear_session=True, clear_debounce=True)

    assert player._intercept_active is False
    assert player._last_intercepted_track_id is None
    assert player._last_intercept_time == 0.0


async def test_concurrent_ticks_do_not_double_handoff() -> None:
    """Two near-simultaneous WS ticks for the same track must only stop+play once.

    Without the lock both tasks would pass the dedup check, both would call
    glagol.send(stop) and play_media.  The lock + early debounce-mark serialise
    them so the second one short-circuits.
    """
    player = _make_intercept_player()
    state, player_state, _ = _state(track_id="X")

    # Make get_item slow so the second tick definitely arrives mid-handoff.
    resolve_started = asyncio.Event()
    resolve_release = asyncio.Event()

    async def slow_get_item(**_kwargs: Any) -> Any:
        resolve_started.set()
        await resolve_release.wait()
        return MagicMock(uri="yandex_music://track/X")

    player.mass.music.get_item = AsyncMock(side_effect=slow_get_item)

    t1 = asyncio.create_task(player._handle_intercept_tick(state, player_state, True))
    await resolve_started.wait()
    # Second tick fires while first is still inside _maybe_intercept's lock.
    t2 = asyncio.create_task(player._handle_intercept_tick(state, player_state, True))
    # Give t2 a chance to acquire the lock and hit the dedup check.
    await asyncio.sleep(0)
    resolve_release.set()
    await asyncio.gather(t1, t2)

    assert player.glagol.send.await_count == 1
    assert player.mass.player_queues.play_media.await_count == 1


# ── Real entrypoint ──────────────────────────────────────────────────


async def test_on_glagol_update_dispatches_intercept_tick_via_create_task() -> None:
    """_on_glagol_update must hand intercept work off through mass.create_task.

    This covers the integration boundary the other tests bypass by calling
    _handle_intercept_tick directly.
    """
    player = _make_intercept_player()
    # Stub out _update_playback_state and friends so we only observe the
    # intercept dispatch.
    player._update_playback_state = MagicMock()
    player.update_state = MagicMock()
    player.set_current_media = MagicMock()
    player._attr_available = False
    player._attr_powered = True
    player._attr_volume_level = 0
    player._attr_playback_state = None
    player._attr_elapsed_time = 0
    player._attr_elapsed_time_last_updated = 0.0
    player._attr_current_media = None
    player._prev_alice_state = ""
    player._voice_resume_task = None
    player._voice_control_enabled_cache = False  # not the real attr but harmless

    captured: list[Any] = []
    player.mass.create_task = MagicMock(side_effect=captured.append)

    raw_state = {
        "state": {
            "playerState": {"id": "12345", "title": "X", "progress": 0, "duration": 60},
            "playing": True,
            "volume": 0.5,
            "aliceState": "IDLE",
        }
    }
    player._on_glagol_update(raw_state)

    # At least one create_task call must be the intercept tick coroutine.
    coro_names = [getattr(c, "__name__", "") for c in captured]
    assert "_handle_intercept_tick" in coro_names, coro_names
    # Cleanup never-awaited coroutines so pytest doesn't warn.
    for coro in captured:
        if hasattr(coro, "close"):
            coro.close()


# ── Round 3: alice handling, target.available, debounce preservation ─


async def test_alice_pause_is_idempotent_across_ticks() -> None:
    """Alice talks for several WS ticks → only one cmd_pause to the target."""
    player = _make_intercept_player()
    player._intercept_active = True
    state, player_state, _ = _state(track_id="X", alice_state="LISTENING")

    await player._handle_intercept_tick(state, player_state, True)
    await player._handle_intercept_tick(state, player_state, True)
    await player._handle_intercept_tick(state, player_state, True)

    assert player.mass.players.cmd_pause.await_count == 1
    # Session stays open so the next Alice track resumes it
    assert player._intercept_active is True
    assert player._alice_active_pause_sent is True


async def test_alice_pause_flag_clears_on_idle() -> None:
    """After alice goes IDLE, the pause-flag resets so the next interaction repauses."""
    player = _make_intercept_player()
    player._intercept_active = True
    player._alice_active_pause_sent = True

    state_idle, ps_idle, _ = _state(track_id="X", alice_state="IDLE")
    await player._handle_intercept_tick(state_idle, ps_idle, True)
    assert player._alice_active_pause_sent is False


async def test_alice_voice_clears_debounce() -> None:
    """After voice-pause, a same-track resume must not be blocked by debounce."""
    player = _make_intercept_player()
    player._intercept_active = True
    player._last_intercepted_track_id = "Y"
    player._last_intercept_time = time.time()
    state, player_state, _ = _state(track_id="Y", alice_state="LISTENING")

    await player._handle_intercept_tick(state, player_state, True)

    assert player._last_intercepted_track_id is None
    assert player._last_intercept_time == 0.0


async def test_alice_active_blocks_new_handoff_in_same_tick() -> None:
    """A fresh playerState.id arriving alongside alice activity must not start a handoff."""
    player = _make_intercept_player()
    player._intercept_active = True
    # Same tick: alice listening AND a new track id appeared.
    state, player_state, _ = _state(track_id="NEW", alice_state="LISTENING")

    await player._handle_intercept_tick(state, player_state, True)

    # Target paused for alice, but no handoff started for the new track.
    player.mass.players.cmd_pause.assert_awaited()
    player.glagol.send.assert_not_awaited()
    player.mass.music.get_item.assert_not_awaited()
    player.mass.player_queues.play_media.assert_not_awaited()


async def test_target_with_available_false_is_rejected() -> None:
    """get_player can return an object with available=False — must not silence Station."""
    player = _make_intercept_player()
    unavailable = MagicMock()
    unavailable.available = False
    player.mass.players.get_player = MagicMock(return_value=unavailable)
    state, player_state, _ = _state()

    await player._handle_intercept_tick(state, player_state, True)

    player.glagol.send.assert_not_awaited()
    player.mass.player_queues.play_media.assert_not_awaited()


async def test_failed_intercept_on_new_track_preserves_debounce() -> None:
    """New-track failure pauses old session but keeps the new track's debounce."""
    player = _make_intercept_player()
    player._intercept_active = True
    player._last_intercepted_track_id = "OLD"
    player._last_intercept_time = 0.0  # well outside the 5s window
    player.mass.music.get_item = AsyncMock(side_effect=RuntimeError("nope"))
    state, player_state, _ = _state(track_id="NEW")

    await player._handle_intercept_tick(state, player_state, True)
    # Old session ended
    player.mass.players.cmd_pause.assert_awaited()
    assert player._intercept_active is False
    # NEW track's debounce stamp survives so the next tick is a no-op
    assert player._last_intercepted_track_id == "NEW"

    await player._handle_intercept_tick(state, player_state, True)
    # Still only one resolve attempt — second tick was debounced
    assert player.mass.music.get_item.await_count == 1


async def test_pause_target_helper_flag_combinations() -> None:
    """The two flags on _pause_target are independent."""
    player = _make_intercept_player()
    player._intercept_active = True
    player._last_intercepted_track_id = "X"
    player._last_intercept_time = time.time()

    # clear_session=False, clear_debounce=True → keeps active, clears debounce
    await player._pause_target(clear_session=False, clear_debounce=True)
    assert player._intercept_active is True
    assert player._last_intercepted_track_id is None

    # Re-establish state
    player._last_intercepted_track_id = "Y"
    player._last_intercept_time = time.time()

    # clear_session=True, clear_debounce=False → clears active, keeps debounce
    await player._pause_target(clear_session=True, clear_debounce=False)
    assert player._intercept_active is False
    assert player._last_intercepted_track_id == "Y"


# ── Round 4: serialisation, fault tolerance, dropdown filter ──────────


async def test_concurrent_alice_ticks_send_one_pause() -> None:
    """Two parallel LISTENING ticks → only one cmd_pause to the target.

    Without the tick-level lock, both tasks would see
    `_alice_active_pause_sent=False` before either await completes and both
    would issue cmd_pause.  With the lock + flag-set-before-await, the second
    task sees the flag set and short-circuits.
    """
    player = _make_intercept_player()
    player._intercept_active = True
    state, player_state, _ = _state(track_id="X", alice_state="LISTENING")

    pause_started = asyncio.Event()
    pause_release = asyncio.Event()

    async def slow_pause(*_args: Any, **_kwargs: Any) -> None:
        pause_started.set()
        await pause_release.wait()

    player.mass.players.cmd_pause = AsyncMock(side_effect=slow_pause)

    t1 = asyncio.create_task(player._handle_intercept_tick(state, player_state, True))
    await pause_started.wait()
    # T2 fires while T1 is still inside cmd_pause holding the lock.
    t2 = asyncio.create_task(player._handle_intercept_tick(state, player_state, True))
    await asyncio.sleep(0)  # let t2 try to acquire the lock
    pause_release.set()
    await asyncio.gather(t1, t2)

    assert player.mass.players.cmd_pause.await_count == 1


async def test_pause_target_cleanup_runs_when_cmd_pause_raises() -> None:
    """If cmd_pause raises, the state-cleanup must still happen.

    Otherwise _intercept_active stays stale and every later WS update retries
    the failing path forever.
    """
    player = _make_intercept_player()
    player._intercept_active = True
    player._last_intercepted_track_id = "X"
    player._last_intercept_time = time.time()
    player.mass.players.cmd_pause = AsyncMock(side_effect=RuntimeError("gone"))

    await player._pause_target(clear_session=True, clear_debounce=True)

    # Despite the raise, both flags were cleared in `finally`.
    assert player._intercept_active is False
    assert player._last_intercepted_track_id is None


async def test_target_dropdown_filters_by_required_features() -> None:
    """Players missing PAUSE / VOLUME_SET / SEEK / PLAY_MEDIA must not appear."""
    player = _make_intercept_player()

    full = MagicMock()
    full.player_id = "full"
    full.display_name = "Full"
    full.supported_features = {
        PlayerFeature.PLAY_MEDIA,
        PlayerFeature.PAUSE,
        PlayerFeature.VOLUME_SET,
        PlayerFeature.SEEK,
    }
    no_seek = MagicMock()
    no_seek.player_id = "no_seek"
    no_seek.display_name = "No Seek"
    no_seek.supported_features = {
        PlayerFeature.PLAY_MEDIA,
        PlayerFeature.PAUSE,
        PlayerFeature.VOLUME_SET,
    }
    self_player = MagicMock()
    self_player.player_id = player.player_id
    self_player.display_name = "Self"
    self_player.supported_features = {
        PlayerFeature.PLAY_MEDIA,
        PlayerFeature.PAUSE,
        PlayerFeature.VOLUME_SET,
        PlayerFeature.SEEK,
    }
    player.mass.players.all_players = MagicMock(
        return_value=[full, no_seek, self_player]
    )

    entries = await YandexStationPlayer.get_config_entries(player)
    target_entry = next(
        e for e in entries if getattr(e, "key", None) == CONF_INTERCEPT_TARGET
    )
    listed_ids = [opt.value for opt in target_entry.options]

    assert listed_ids == ["full"]


async def test_concurrent_mirror_volume_serialised() -> None:
    """Back-to-back volume updates must be applied in order.

    Without the tick-level lock, an older volume task could finish after a
    newer one and leave the target stale.  With the lock, the second tick
    blocks until the first finishes — guaranteeing in-order application.
    """
    player = _make_intercept_player()
    player._intercept_active = True
    player._last_intercepted_track_id = "X"
    player._last_intercept_time = time.time()

    applied: list[int] = []
    first_started = asyncio.Event()
    first_release = asyncio.Event()

    async def slow_first(*_args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        applied.append(_args[1])  # type: ignore[index]
        first_started.set()
        await first_release.wait()

    async def fast(*_args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        applied.append(_args[1])  # type: ignore[index]

    cmds = AsyncMock(side_effect=slow_first)
    player.mass.players.cmd_volume_set = cmds

    state1, ps1, _ = _state(track_id="X", volume=0.3)
    t1 = asyncio.create_task(player._handle_intercept_tick(state1, ps1, True))
    await first_started.wait()
    cmds.side_effect = fast  # next call uses the fast handler
    state2, ps2, _ = _state(track_id="X", volume=0.6)
    t2 = asyncio.create_task(player._handle_intercept_tick(state2, ps2, True))
    await asyncio.sleep(0)
    first_release.set()
    await asyncio.gather(t1, t2)

    # In-order application: 30 then 60 (not the reverse).
    assert applied == [30, 60]
