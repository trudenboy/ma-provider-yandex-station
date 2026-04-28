# Changelog

## [Unreleased]

## [1.3.3] - 2026-04-28

### Fixed
- **Auth regression introduced in 1.3.2**: switching the dedicated `ClientSession` to MA's `create_clientsession()` helper broke Yandex Passport's session refresh — every `refresh_passport_cookies()` call now hit `HTTP 400 from redirect chain`, flooding logs and preventing player creation. Reverted to a bare `aiohttp.ClientSession(cookie_jar=CookieJar(quote_cookie=False))`. The exact incompatibility (custom connector / SSL context / `_default_headers` override) wasn't isolated, but the symptom was reproducible on every station and disappeared on rollback.

## [1.3.2] - 2026-04-28

### Changed
- **Player identifiers** (upstream PR review): `DeviceInfo.identifiers` now carries `IP_ADDRESS` and `UUID` (Yandex `device_id`) so MA can auto-link the player with other protocols on the same speaker. The IP identifier is refreshed in `update_connection()` when mDNS reports a new address. MAC isn't published by mDNS or Quasar, so it isn't surfaced.
- **Log levels** (upstream PR review): demoted high-frequency per-event logs to `DEBUG` — `play_media`, voice-interrupt / voice-end / physical-pause / native-player-after-voice transitions, and post-voice queue auto-resume. `INFO` is now reserved for provider-level milestones.
- **HTTP session via MA helper** (upstream PR review): the dedicated Yandex `ClientSession` is now built through `music_assistant.helpers.aiohttp_client.create_clientsession()` instead of a bare `aiohttp.ClientSession(...)`, so it picks up MA's connector pool, `MusicAssistant/<ver>` User-Agent, and `MassClientResponse`. Kept a private `CookieJar(quote_cookie=False)` because Yandex Passport rejects percent-encoded cookies (a `CookieJar` constructor-only kwarg, can't be applied to `mass.http_session`).

## [1.3.1] - 2026-04-22

### Fixed
- **Physical pause sync**: pressing pause on the Yandex Station speaker while MA was streaming via `radio_play` no longer leaves MA stuck in `PLAYING`. The player now distinguishes the startup window from real pause events (Glagol `playing=False` + `aliceState="IDLE"`) and propagates `PAUSED` to MA, arming a re-play for the next `play()`.
- **`_init_session()` concurrency race** (upstream PR review): concurrent calls from `discover_players()` and mDNS-triggered `_create_player()` could close another task's freshly created `ClientSession` in the orphan-cleanup branch. Wrapped session init in a dedicated `asyncio.Lock` so only one cascade runs at a time.

### Security
- **Glagol WS peer restriction** (upstream PR review): the Glagol WebSocket uses a self-signed device cert and therefore runs with `ssl=False`. Combined with untrusted mDNS input this allowed a spoofed record to redirect the `conversationToken` to an arbitrary host. `start()` now rejects any host that isn't in the private/link-local/loopback range.

## [1.3.0] - 2026-04-20

### 🔐 Refactored authentication (Device Flow + auto-refresh cascade)

Aligned the auth surface with `ma-provider-yandex-music`: Device Flow is now the recommended primary login method, credential refresh is silent end-to-end, and a `Remember session` toggle lets users opt out of long-lived tokens.

#### Added
- **Device Flow login** (recommended): opens a short code + verification URL on an MA-hosted page; yields the full `(x_token, music_token, refresh_token)` triple for silent auto-refresh.
- **Refresh token storage** (`CONF_REFRESH_TOKEN`) — Device-Flow accounts can silently rotate the full credential triple when `x_token` expires.
- **Remember session toggle** (`CONF_REMEMBER_SESSION`, default `True`) — when `False`, only `music_token` is persisted; no silent refresh path.
- **Credential cascade in `_init_session`**: fast path → `x_token → music_token` refresh → `refresh_token → triple` rotation → terminal clear.
- **Runtime silent re-auth** on Quasar 401/403: `_silent_reauth()` retries the failed call after rotating credentials.
- `refresh_credentials_via_passport()` helper and `perform_device_auth()` auth flow.
- New tests: `tests/test_provider_cascade.py` (12 cases) + expanded `tests/test_auth.py` Device Flow + `refresh_credentials_via_passport` scenarios.

#### Changed
- Renamed `provider/yandex_auth.py` → `provider/auth.py` and `tests/test_yandex_auth.py` → `tests/test_auth.py` for parity with `ma-provider-yandex-music`.
- Validation errors in `get_config_entries()` (missing `session_id`, empty/invalid cookies) now raise `InvalidDataError` instead of `LoginFailed`; `LoginFailed` is reserved for real Passport failures and `setup()`.
- `setup()` no longer requires `x_token` — either `music_token` or `x_token` is enough.
- `YandexSession.__init__` gained an optional `refresh_token` parameter so the cascade can rotate it in place.

#### Dependencies
- Bumped `ya-passport-auth` from `>=1.2.3` to `~=1.3.0` (Device Flow + `refresh_credentials` API).

## [1.2.0] - 2026-04-11

### 🔧 Upgrade ya-passport-auth to 1.2.0

#### Fixed
- **Quasar IoT 401 errors**: library's `refresh_passport_cookies` now follows redirect chain, setting cookies on `.yandex.ru` domain (no code changes needed)

#### Changed
- Replaced ~90 lines of custom cookie→x_token HTTP exchange with `PassportClient.login_cookies()` (~15 lines)
- Removed `_PASSPORT_CLIENT_ID`, `_PASSPORT_CLIENT_SECRET` hardcoded credentials (now in library)
- Removed `PASSPORT_API_URL` constant (no longer needed)
- Removed `aiohttp` direct import from `yandex_auth.py`
- Rewrote cookie login tests to mock `PassportClient.login_cookies()` instead of raw `aiohttp`

#### Added
- `test_login_with_cookies_auth_error_raises_login_failed` test (16 total)

---

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

## [1.2.1] - 2026-04-16

- Bump version from 1.2.0 to 1.2.1 (`b05e71d`)
- chore: sync workflow wrappers from ma-provider-tools (#32) (`74e649c`)
- fix: surface errors in power() and handle empty cookie domain on restore (`a4546c7`)
- style: auto-fix ruff (`949f8d6`)
- fix(player): raise on failed Glagol sends and fix audio announcement wait (`5b5da85`)
- chore: sync workflow wrappers from ma-provider-tools (#30) (`c40e82d`)
- style: auto-fix ruff (`305d35c`)
- chore: sync workflow wrappers from ma-provider-tools (#27) (`59e8be7`)
- style: auto-fix ruff (`c8973a6`)
- fix(glagol): move class attributes to instance attributes (`60d7c56`)
- style: auto-fix ruff (`b17c946`)
- fix(session): strip leading dot from cookie domain in serialization (`c0d0492`)
- fix(auth): remove unnecessary type: ignore comment (`214f8d0`)
- style: auto-fix ruff (`de305df`)
- fix(auth): add type: ignore for mypy compat with older ya-passport-auth (`8f41a3a`)
- style: auto-fix ruff (`88c1dcf`)
- fix(player): block play_announcement until playback finishes (`94f36f8`)
- chore(deps): bump ya-passport-auth to 1.2.3 (`543a6df`)
- fix(provider): disable cookie quoting for Yandex compatibility (`bfc02f6`)
- fix(session): delegate login_token() back to ya-passport-auth 1.2.2 (`3a05750`)
- fix(session): pass track_id as query param, not header (`a99f900`)
- fix(session): use library refresh_passport_cookies (ya-passport-auth 1.2.1) (`f6f2a2a`)

---

## [1.3.2] - 2026-04-28

- test: patch create_clientsession in cascade tests (`b13f12e`)
- style: auto-fix ruff (`c46a231`)
- fix: address upstream PR #3605 review (Marvin) (`e869697`)
- style: auto-fix ruff (`621112e`)
- style: auto-fix ruff (`c13bfd2`)
- test: appease upstream mypy on test_provider_cascade.py (`d14e5e0`)
- style: auto-fix ruff (`a4febf3`)
- fix: address upstream PR #3605 Copilot review (`454f215`)
- style: auto-fix ruff (`2456b83`)

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
