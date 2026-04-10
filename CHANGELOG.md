# Changelog

## [1.1.0] - 2026-04-10

### 🔐 Authentication migration to `ya-passport-auth`

#### Changed
- Migrated all Yandex Passport authentication to the [`ya-passport-auth`](https://github.com/trudenboy/ya-passport-auth) library
- QR code auth, music token refresh, device token, cookie refresh — all delegated to `PassportClient`
- Tokens wrapped in `SecretStr` throughout the codebase for secret hygiene
- `YandexSession` now accepts a shared `PassportClient` instance (shared aiohttp session + cookie jar)
- `YandexGlagol` uses `PassportClient.get_glagol_device_token()` instead of direct HTTP calls
- Removed 4 hardcoded constants (`GLAGOL_TOKEN_URL`, `MUSIC_TOKEN_URL`, `MUSIC_CLIENT_ID`, `MUSIC_CLIENT_SECRET`) — now in the library
- Cookie domain normalization for browser-exported JSON cookies
- Proper `content_type` validation and `JSONDecodeError` handling in cookie auth

#### Added
- 13 unit tests for all auth functions (`test_yandex_auth.py`)
- Comprehensive MA module stubs in `conftest.py` for isolated testing

---

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

## [1.0.0] - 2026-04-07

- fix(player): import ConfigEntryType from enums for mypy (`c57d39f`)
- refactor(player): extract voice control methods, fix E402 import order (`d21da16`)
- style: apply ruff formatter (`6743a48`)
- fix: resolve ruff lint errors (line length, duplicate imports) (`7e62bb3`)
- chore: update documentation URL to music-assistant.io (`d1b2a41`)
- chore: add Alice gradient icon as provider icon (`b68da33`)
- chore: prepare v1.0.0 release — stage beta, updated README and CHANGELOG (`6c3ada3`)
- fix(player): smart voice control — distinguish commands from queries (`1ddc25b`)
- feat(player): add experimental voice control toggle (off by default) (`067351f`)
- feat(player): detect voice commands during bypass playback (`d568c7f`)
- fix(player): show correct track info during bypass playback (`eb19f80`)
- fix(player): use local radio_play for bypass pause instead of cloud sendText (`afe6bd3`)
- fix(player): implement pause/resume for externalCommandBypass playback (`39f649c`)
- fix(player): use forced_content_length HTTP profile for playback (`cd4baa1`)
- chore: update changelog for v0.3.0 [skip ci] (`fccb5cd`)

---

## [1.1.0] - 2026-04-10

- chore: bump version to 1.1.0, update changelog (`a13786f`)
- refactor(auth): migrate to ya-passport-auth library (#19) (`ae443f9`)
- chore: sync workflow wrappers from ma-provider-tools (#17) (`cac6963`)
- chore: sync workflow wrappers from ma-provider-tools (#15) (`237c322`)
- chore: sync workflow wrappers from ma-provider-tools (#13) (`57bac90`)
- chore: sync workflow wrappers from ma-provider-tools (#11) (`8ebd65f`)
- chore: sync workflow wrappers from ma-provider-tools (#8) (`01a5f7f`)
- chore: add VERSION file (0.1.2) (`18f5215`)
- chore: sync workflow wrappers from ma-provider-tools (#6) (`32c138a`)

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
