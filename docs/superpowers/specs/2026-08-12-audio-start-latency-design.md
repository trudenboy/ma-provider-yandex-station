# Yandex Station playback startup latency

## Problem

Runtime measurements show that `play_media` reaches Glagol in 7–21 ms and the
station opens the Music Assistant Queue Flow URL after 90–155 ms. Glagol does
not report the requested stream as playing until roughly 6.3 seconds later.
The active player configuration uses FLAC, while Music Assistant feeds Queue
Flow through FFmpeg with a five-second initial burst. The remaining delay is
therefore in receiver-side stream probing and buffering, not authentication,
URL resolution, or command delivery.

The same traces expose a separate state bug. Immediately after `audio_play`, a
stale `playing=True` update for the previous source confirms the new external
session. The following startup `playing=False` update for the requested track
is then misclassified as a physical pause and clears the external session.

## Design

### Audio-client handoff state

For an `audio_play` session, Glagol state is attributed to the requested media
using `playerState.title` and the title sent in `audio_play` metadata:

1. A `playing=True` update whose non-empty title differs from the requested
   title is stale and must not confirm the external session.
2. A `playing=False` update matching the requested title marks the handoff as
   observed but remains an optimistic Music Assistant `PLAYING` state.
3. A matching `playing=True` update confirms the session.
4. Only a matching `playing=False` received after confirmation is treated as a
   physical pause.

When either the requested title or reported title is unavailable, the player
falls back to the existing stop-then-play transition guard. Legacy
`radio_play` behavior remains unchanged because its state does not reliably
carry external metadata.

The implementation extends the playback-state transition function with a
tri-state match value: true for matching media, false for a known mismatch,
and `None` when identity cannot be established. This keeps Glagol parsing at
the boundary and the state machine independently testable.

### Startup codec experiment

MP3 was tested as a Yandex Station-specific default because it is the format
declared to the firmware by the working `audio_play` directive. Runtime A/B
measurements did not support retaining the change: five MP3 launches took
approximately 6.3–7.0 seconds from command to `playing=True`, compared with the
FLAC baseline of approximately 6.3 seconds. The shared Music Assistant FLAC
default is therefore retained, avoiding a lossy transcode with no measured
latency benefit.

The forced-content-length HTTP profile and Queue Flow behavior are retained.
Advertising `ENQUEUE` would be incorrect because the station has no provider
enqueue command. Sending finite tracks as `FmRadio` is also excluded because
it loses track semantics and differs from the firmware-compatible payload.

## Compatibility and failure handling

- Devices without `audio_client` retain the existing `radio_play` path.
- FLAC remains the default; explicit AAC, MP3, or WAV settings remain valid.
- Title mismatch affects only startup attribution; it never sends an extra
  transport command or stops playback.
- Physical pause continues to set `_needs_replay` after the requested session
  has been confirmed.
- `ya-passport-auth[ma]` remains pinned to `1.8.0` in production and test
  Compose environments.

## Verification

- Add a regression test reproducing the observed sequence: stale old-track
  `playing=True`, requested-track `playing=False`, requested-track
  `playing=True`.
- Assert that no physical pause is produced, external session fields survive,
  and the final update confirms playback.
- Retain a test for a real matching pause after confirmation.
- A/B-test MP3 and retain it only if startup latency materially improves.
- Run focused tests, the full suite, Ruff, mypy, and pre-commit.
- Rebuild the development Compose service and compare runtime startup timing
  with the captured FLAC baseline of approximately 6.3 seconds. The measured
  MP3 result did not improve it, so the experiment was reverted.
