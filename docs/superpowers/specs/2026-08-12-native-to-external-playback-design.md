# Yandex Station audio client playback

## Problem

Station firmware built since approximately 2026-07-17 acknowledges the legacy
`externalCommandBypass/radio_play` directive but ignores its `streamUrl`. The
station makes no HTTP request and starts a Yandex radio station instead. Sending
a native `stop` before `radio_play` cannot repair a directive whose payload is
discarded.

## Design

The player records whether the station advertises `audio_client` in the
top-level `supported_features` of Glagol state messages. That capability selects
the playback directive:

- `audio_client` present: send `audio_play` using the cloud-compatible nested
  stream payload.
- capability absent: retain the existing `radio_play` payload for old firmware.

For finite files, `audio_play` uses `format: MP3`, `type: Track`, and
`offset_ms: 0`. Firmware detects AAC, FLAC, MP3 and WAV codecs from the body.
For an URL whose path ends in `.m3u8`, it uses `format: HLS` and
`type: FmRadio`. `set_pause` is always false. Metadata contains title,
subtitle, and a schemeless HTTPS artwork URL when available.

The generic protobuf builder remains unchanged. `play_media` sends the selected
directive directly without a preliminary stop because `audio_play` replaces the
active source. Audio announcements use the same feature-gated builder.

## Playback lifecycle

The player remembers which external directive started the current session.
Native `stop` is used for `audio_play` sessions, whose state is exposed through
Glagol. Legacy `radio_play` sessions retain the invalid-URL replacement because
old firmware does not reliably stop bypass playback with native `stop`.

`audio_play` reports metadata and progress in `playerState`; the provider may
therefore accept `playing=True` directly as confirmation. Legacy sessions keep
the optimistic state model and physical-pause handling already required by
`radio_play`.

## Error handling and compatibility

- Missing `audio_client` always selects `radio_play`.
- An unsuccessful Glagol response resets the pending external session and
  raises the existing `PlayerCommandFailed` error.
- A malformed or missing `supported_features` value does not remove a capability
  learned from earlier valid state messages.
- `ya-passport-auth[ma]` remains pinned to `1.8.0` in production and test
  Compose environments.
- Infinite live streams have a reported model-dependent five-minute limitation
  under `audio_play`; reconnect behavior is outside this finite-track fix.

## Test plan

- Decode protobuf output and assert literal `audio_play` payloads for FLAC and
  HLS, including metadata normalization.
- Assert `audio_client` capability discovery and legacy fallback.
- Assert `play_media` sends no preliminary stop and chooses the correct
  directive.
- Assert pause and stop use native `stop` for audio-client sessions and preserve
  legacy behavior otherwise.
- Assert announcements use the same feature gate.
- Run unit tests, lint, typing and pre-commit checks.
- Rebuild the test Compose service, initiate playback, and verify the station
  requests the Music Assistant URL instead of starting Yandex radio.
