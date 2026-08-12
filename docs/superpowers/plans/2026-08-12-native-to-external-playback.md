# Yandex Station Audio Client Playback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore Music Assistant URL playback on current Yandex Station firmware while preserving legacy firmware compatibility.

**Architecture:** Learn the `audio_client` capability from Glagol updates and route external media through a pure command builder. Current firmware receives `audio_play`; devices without the capability retain `radio_play`. Session state records the selected directive so play, pause, stop, announcements, and state confirmation use matching semantics.

**Tech Stack:** Python 3.14, asyncio, pytest, Music Assistant player API, Glagol WebSocket, protobuf wire encoding.

## Global Constraints

- Keep `ya-passport-auth[ma]` pinned to `1.8.0` in normal and test Compose environments.
- Do not change the protobuf wire format used by `externalCommandBypass`.
- Do not send native `stop` before `audio_play` or `radio_play` track changes.
- Retain `radio_play` only as fallback when `audio_client` is not advertised.
- Treat the live-stream five-minute limitation as separate follow-up work.

---

### Task 1: Feature-gated stream command builder

**Files:**
- Modify: `provider/player.py:51`
- Test: `tests/test_protobuf.py`

**Interfaces:**
- Consumes: `_external_command(name: str, payload: dict[str, Any] | str | None)`.
- Produces: `_stream_command(url: str, media: PlayerMedia | None, audio_client: bool) -> dict[str, Any]`.

- [ ] **Step 1: Write failing payload tests**

Add tests that decode the real protobuf and compare the directive and payload
against hand-written literals. Cover FLAC as `MP3/Track`, `.m3u8` as
`HLS/FmRadio`, metadata, and legacy `radio_play`.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_protobuf.py -q`

Expected: collection fails because `_stream_command` does not exist.

- [ ] **Step 3: Implement the pure builder**

Use `urlsplit(url).path.lower().endswith(".m3u8")`; emit the exact nested
`audio_play` payload when `audio_client` is true and the existing flat
`radio_play` payload otherwise. Strip only an `https://` prefix from artwork.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/test_protobuf.py -q`

Expected: all protobuf tests pass.

### Task 2: Capability discovery and playback selection

**Files:**
- Modify: `provider/player.py:120-430,1068-1140`
- Test: `tests/test_player_state.py`

**Interfaces:**
- Consumes: top-level `data["supported_features"]` from `_on_glagol_update`.
- Produces: `_audio_client: bool` and `_external_audio_client: bool` session state.

- [ ] **Step 1: Write failing capability and command-selection tests**

Test that a valid feature list enables `_audio_client`, absent/malformed values
preserve the learned value, `play_media` emits `audio_play` with no preceding
stop, and a player without the feature emits legacy `radio_play`.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_player_state.py -q`

Expected: tests fail on missing state and legacy payload selection.

- [ ] **Step 3: Implement capability and session tracking**

Initialize both flags to false. Update `_audio_client` only from a list, tuple,
set, or frozenset. Set `_external_audio_client` before sending a stream command,
reset it on failure/session cleanup, and remove the preliminary native stop.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/test_player_state.py -q`

Expected: all player-state tests pass.

### Task 3: Matching stop, pause, announcements, and confirmation

**Files:**
- Modify: `provider/player.py:300-475,1020-1060`
- Test: `tests/test_player_state.py`

**Interfaces:**
- Consumes: `_external_audio_client` established by `play_media`.
- Produces: native stop for audio-client sessions, legacy invalid-URL stop for
  radio sessions, and feature-gated announcement playback.

- [ ] **Step 1: Write failing lifecycle tests**

Test native stop for audio-client pause/stop, legacy replacement for old
sessions, audio-client announcement payload, and immediate confirmation from an
`audio_play` `playing=True` update.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_player_state.py -q`

Expected: lifecycle assertions fail against the legacy-only implementation.

- [ ] **Step 3: Implement matching lifecycle behavior**

Choose the stop command from session mode, use `_stream_command` for
announcements, and require the old stop-observed guard only for legacy sessions.
Keep current replay behavior after pause.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/test_player_state.py -q`

Expected: all player-state tests pass.

### Task 4: Static and runtime verification

**Files:**
- No additional production files.

**Interfaces:**
- Consumes: completed provider and regression suite.
- Produces: fresh automated and Compose runtime evidence.

- [ ] **Step 1: Run the full automated suite**

Run: `uv run pytest -q`

- [ ] **Step 2: Run static checks**

Run: `uv run ruff check provider tests && uv run mypy provider`

- [ ] **Step 3: Run repository hooks**

Run: `uv run pre-commit run --all-files`

- [ ] **Step 4: Rebuild and restart the test service**

Run: `docker compose -f docker-compose.dev.yml up -d --build --force-recreate`

- [ ] **Step 5: Inspect startup and playback logs**

Run: `docker compose -f docker-compose.dev.yml logs --since=5m --no-color`

Expected after a playback attempt: `audio_play` returns `SUCCESS`, the station
requests port 8097, and `playerState` reports the requested track rather than a
Yandex radio station.
