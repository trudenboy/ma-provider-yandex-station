# Changelog

## [1.0.0] - 2026-04-07

### 🎉 First stable release

#### Core
- Local playback via Glagol WebSocket `externalCommandBypass` / `radio_play`
- Auto-discovery via mDNS (`_yandexio._tcp.local.`)
- Cloud discovery fallback via Quasar IoT API + Glagol device_list API
- Real-time state updates from Glagol WebSocket

#### Authentication
- QR code authentication (scan with Yandex app)
- Cookies-based authentication (advanced fallback)
- Automatic token refresh (x_token → music_token → device_token)

#### Transport Controls
- Play / Pause / Stop / Resume
- Next / Previous track
- Seek (rewind)
- Volume set / mute
- Power on/off via Yandex scenarios

#### Playback
- FLAC lossless streaming with forced Content-Length
- Track info display (title, artist, cover, duration)
- Automatic track transitions on queue advancement
- Pause via radio_play with unreachable URL (fully local, no cloud)
- Resume via MA queue replay

#### Announcements
- Native TTS via Alice's voice (repeat_phrase)
- Audio announcement fallback via stream URL

#### Voice Control (Experimental, off by default)
- Detect Alice activation during bypass playback
- Auto-resume after informational queries (weather, etc.)
- Auto-resume after volume adjustments
- Stay paused on control commands (стоп, пауза)
- Accept native playback when Alice starts her own music

---

## [0.1.1] - 2026-04-07

- fix: remove duplicate type annotation for _auth_payload (mypy no-redef) (`a11e504`)
- fix: add --frozen to uv run in pre-commit to prevent uv.lock modification in CI (`27e7f4f`)
- fix: add changelog marker for release workflow (`0000d88`)

---

## [0.1.2] - 2026-04-07

- chore: update changelog for v0.1.1 [skip ci] (`8826bda`)

---

## [0.1.3] - 2026-04-07

- chore: set provider stage to alpha (`bff1236`)
- feat(auth): add cookies-based authentication as advanced fallback (`1ee1f42`)
- refactor: extract auth into yandex_auth.py module (`25cb48c`)
- chore: update changelog for v0.1.2 [skip ci] (`967490b`)

---

## [0.2.0] - 2026-04-07

- feat(player): add native TTS announcements via Alice voice (`2e6a806`)
- chore: update changelog for v0.1.3 [skip ci] (`0e47cfb`)

---

## [0.3.0] - 2026-04-07

- feat(player): add power control and update_form helper (`a5dc2c0`)
- chore: update changelog for v0.2.0 [skip ci] (`f2a9246`)

---

<!-- changelog entries will be added here by release workflow -->

## [0.0.1] - 2026-04-06

### Added
- Initial project structure
- Provider skeleton: `__init__.py`, `manifest.json`, `constants.py`
- Yandex Session authentication module (adapted from AlexxIT/YandexStation)
- Yandex Glagol WebSocket client for local device control
- Yandex Quasar cloud API client for device discovery
- `YandexStationProvider(PlayerProvider)` with mDNS discovery
- `YandexStationPlayer(Player)` with play/pause/stop/seek/volume/next/prev
- Protobuf utility for `externalCommandBypass` encoding
