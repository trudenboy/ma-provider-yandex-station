# Yandex Station Playback Startup Latency Implementation Plan

> **For agentic workers:** Execute each task in order and keep the RED/GREEN
> evidence. Do not parallelize these edits because both tasks modify the player
> state/config surface.

**Goal:** Remove the false pause during `audio_play` handoff and test whether an
MP3 default materially reduces the measured six-second startup delay.

**Architecture:** Attribute Glagol transitions to the requested media before
confirming or pausing an external session. Override only the player-specific
default codec, then validate the optimization against runtime timestamps and
revert it if the measurement does not improve.

**Tech Stack:** Python 3.14, asyncio, pytest, Music Assistant player API,
Glagol WebSocket, Docker Compose.

---

### Task 1: Reproduce and repair audio-client handoff attribution

**Files:**
- Modify: `tests/test_player_state.py`
- Modify: `provider/player.py`

- [x] Add a failing regression test with the observed old-title `playing=True`
  → new-title `playing=False` → new-title `playing=True` sequence.
- [x] Assert the intermediate update stays optimistic, does not set
  `_needs_replay`, and preserves `_external_media`.
- [x] Run `uv run pytest tests/test_player_state.py -q` and capture RED.
- [x] Derive a tri-state media-title match in `_on_glagol_update` and pass it
  into `_update_playback_state`.
- [x] Require matching/unknown handoff evidence before confirming an
  audio-client session; ignore known stale mismatches for pause detection.
- [x] Run the focused tests and capture GREEN.

### Task 2: Make MP3 the Station-specific default

**Files:**
- Modify: `tests/test_player_state.py`
- Modify: `provider/player.py`

- [x] Add a failing test that calls `get_config_entries`, finds
  `output_codec`, and expects `mp3` while the shared constant stays `flac`.
- [x] Run the focused test and capture RED.
- [x] Create the Station entry with `dataclasses.replace` and return it from
  `get_config_entries`.
- [x] Run the focused tests and capture GREEN.

### Task 3: Automated verification

**Files:** No additional production files.

- [x] Run `uv run pytest -q`.
- [x] Run `uv run ruff check provider tests`.
- [x] Run `uv run mypy provider`.
- [x] Run `uv run pre-commit run --all-files`.
- [x] Review the diff for unrelated changes and verify both Compose files keep
  `ya-passport-auth[ma]==1.8.0`.

### Task 4: Runtime A/B validation

**Files:** Runtime configuration only.

- [x] Rebuild with
  `docker compose -f docker-compose.dev.yml up -d --build --force-recreate`.
- [x] Confirm the effective player stream URL/codec is MP3.
- [x] Start several tracks and measure `play_media called` → first matching
  `playing=True`; compare with the 6.3-second FLAC baseline.
- [x] Confirm the logs no longer contain `Physical pause detected` during
  ordinary startup or track switches.
- [x] If MP3 does not materially improve latency, revert only the codec-default
  change and rerun its affected tests; retain the handoff-state correction.
