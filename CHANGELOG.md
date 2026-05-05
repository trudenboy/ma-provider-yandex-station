# Changelog

## [Unreleased]

## [1.4.17] - 2026-05-05

### Fixed
- **Target audio no longer stutters every ~5 seconds during continuous-mode intercept** (live-station bug report): Glagol emits `playerState` ~1Hz with the same `id` for the *entire* track duration (3-5min). The 5-second failure-debounce we kept from one-shot intercept expired mid-track, and every subsequent tick fired a fresh `play_media(REPLACE)` on the target — manifesting as repeated `StreamEnd`/`StreamStart` cycles and audible stuttering in the live MA logs. The same-track guard is now: skip the handoff if `_intercept_active=True` *regardless of time elapsed*; only apply the 5-second debounce to failed prior attempts (where `_intercept_active=False`). New regression test `test_same_track_during_active_session_is_no_op` pins down the contract.

## [1.4.16] - 2026-05-05

### Fixed
- **`setattr()` for method-assign in `test_provider_cascade` fallback tests** (upstream MA PR #3605 CI): mypy strict mode flagged 6 `[method-assign]` errors on direct `AsyncMock` assignment to provider methods (`_init_session`, `_silent_reauth`, `_create_player`). Same pattern previously applied to `test_intercept.py` — switched to `setattr(..., noqa: B010)`. Tests still green.

## [1.4.15] - 2026-05-05

### Fixed
- **`discover_players` falls back to Glagol `device_list` when Quasar fails** (upstream MA PR #3605, Copilot): the cloud `get_speakers` call uses cookie/CSRF auth while `get_local_speakers` uses Glagol/music_token auth — these are independent paths. Previously, a failing Quasar call (stale cookies, transient API issue) returned early and never tried the local list, leaving users with an empty integration even when their `music_token` was still valid and the Glagol API would have surfaced their devices. We now build a synthetic speaker list from the Glagol response (with `quasar_info` containing `device_id` + `platform`) so registration still succeeds. If both paths fail, `_discovery_done` stays `False` for MA's retry loop.

## [1.4.14] - 2026-05-04

### Changed
- **Intercept now keeps the Station playing silently in the background, enabling track-by-track continuous handoff for the whole Alice session.** Previously sent `setVolume(0)` followed by `{"command":"stop"}`. The `stop` command halts the Station's queue and stops `playerState` updates — so only one Alice-initiated track played on the target before silence, and every subsequent track required a fresh "Алиса, включи..." command. Now we send `setVolume(0)` only; the Station continues its own playlist silently and emits `playerState` ticks with each new track ID, which we forward to the target on every change. Mirrors AlexxIT/YandexStation's `sync_mute` approach.

### Added
- **Mute lifecycle around Alice activity**: when Alice transitions to LISTENING/SPEAKING during an active session, the Station is unmuted so her reply is audible; on transition back to IDLE the Station is re-muted. Covers "Алиса, что играет?" / "Алиса, погода" without bleeding native music.
- **Pause-mirror on Station `playing=False`** (gated on an established session): physical pause / "Алиса, пауза" during a session pauses the target; same-track resume re-triggers handoff via cleared debounce.
- **Volume mirror skips `vol=0` during a session**: the self-induced mute no longer silences the target. A user-initiated unmute (`vol > 0` differing from the saved baseline via Yandex app or "Алиса, громче") clears the self-mute flag and updates the saved baseline.
- **`on_unload` ends any active intercept session** so the Station's volume is restored before the integration tears down — users disabling the integration mid-session no longer leave their Station stuck at vol=0.
- **Single funnel `_end_intercept_session` for session-end side effects** (volume restore + flag reset). Reduces the previous handful of inline cleanup paths to one consistent helper.

### Fixed
- **Volume restore deferred to session end** instead of after every handoff. Previously every handoff scheduled a background `setVolume(saved)` task that raced the next handoff's mute, leaving timing-dependent audio leaks. The restore now fires once, in `_end_intercept_session`.
- **Re-mute conditional on `_station_muted_by_intercept`** so back-to-back track handoffs don't spam the WS with redundant `setVolume(0)` commands. Re-mute still fires after an alice-active unmute so the next handoff re-silences the Station.
- **`_handle_intercept_tick` now receives `prev_alice_state` via parameter** (PR #57, Copilot): `_on_glagol_update` overwrites `self._prev_alice_state` with the current `aliceState` *before* scheduling the tick via `mass.create_task` — so the tick used to read the post-assignment value, making the `LISTENING/SPEAKING → IDLE` edge re-mute branch dead code in production (passing only in tests that manually preset the field). The dispatcher now snapshots the field before assignment and threads it in.
- **`playing=False` during a session ends the session** (PR #57, Copilot): previously kept `_intercept_active=True` and only cleared debounce, which left the Station stuck at `vol=0` indefinitely on end-of-queue or any `playing=False` not followed by a same-track resume. We can't reliably distinguish "transient pause" from "queue ended" in a single event, so always end the session — accepting ~one WS round-trip of native audio leak on quick resume (matches v1.4.7 baseline).

## [1.4.13] - 2026-05-04

### Changed
- **Surface intercept settings out of "advanced"**: dropped `advanced=True` from `CONF_INTERCEPT_FEATURE_ENABLED` (provider-level master switch) and from the per-player `CONF_INTERCEPT_ENABLED` / `CONF_INTERCEPT_TARGET`. Hiding them in the advanced section made the feature hard to discover for users who explicitly want to configure it. They remain `default_value=False` and labeled "Experimental:" so the opt-in nature is clear at the top level too.

## [1.4.12] - 2026-05-04

### Fixed
- **`CONF_INTERCEPT_TARGET` description matches the actual filter** (upstream MA PR #3605, Copilot): the dropdown's description still read "Lists every player that supports play_media" from before the v1.4.11 filter relaxation. Updated to "Lists every registered player except this Station" so users aren't misled when picking a target. The mirror-helpers caveat ("pause / volume_set / seek mirrors gracefully no-op on players that don't support them") is preserved.

## [1.4.11] - 2026-05-04

### Fixed
- **Intercept target dropdown was still hiding many legitimate players.** v1.4.7 relaxed the filter from "PLAY_MEDIA + PAUSE + VOLUME_SET + SEEK" to just `PLAY_MEDIA`, but in practice that still hid AirPlay / DLNA / BT-bridge players that don't advertise `PLAY_MEDIA` even though queue-routed playback works for them. Intercept dispatches via `mass.player_queues.play_media(queue_id=...)` which routes through the per-player queue, so any registered player is a valid target — feature filtering at the picker only ends up hiding usable targets. The dropdown now lists every registered player except the Station itself, sorted alphabetically by display name. Mirror helpers (volume / pause / seek) already catch `UnsupportedFeaturedException` and gracefully no-op when the target lacks them.

## [1.4.10] - 2026-05-04

### Security
- **Glagol `send()` no longer logs full outbound payloads at DEBUG** (upstream MA PR #3605, Copilot): the previous `=> local | %s` line dumped the whole `payload` dict, which for `externalCommandBypass` includes the base64-encoded JSON containing `streamUrl`. MA stream URLs embed session IDs / tokens; logging them at DEBUG would leak credentials into log files. The line now logs only the command name and the names (not values) of accompanying keys: `=> local | radio_play (extras: ['data'])`.

## [1.4.9] - 2026-05-04

### Fixed
- **Mirror functions actually no-op on unsupported targets** (upstream MA PR #3605, Copilot): the v1.4.7 dropdown change documented that `pause / volume / seek` "gracefully no-op" when the target lacks support, but `_maybe_mirror_volume` and `_maybe_mirror_seek` called `mass.players.cmd_volume_set` / `cmd_seek` unguarded — and MA raises `UnsupportedFeaturedException` for those, which would crash the background intercept task on every WS tick. Both helpers now catch `UnsupportedFeaturedException` and log at DEBUG. (`_pause_target` was already wrapped in `try/except` so it was unaffected.)

## [1.4.8] - 2026-05-04

### Changed
- **Mute the Station before the intercept stop to mask the brief native-playback blip.** When intercept handoff fires, the Station has already started playing the track Alice asked for (we react to the Glagol `playing=True` notification, which arrives after audio output begins). The user previously heard a short burst of native audio between Alice's command and our `stop` command arriving over the WebSocket. We now send `setVolume(0)` immediately before the `stop` so the Station goes silent as fast as the WS round-trip allows. Saved volume is restored in the background after the target handoff completes (and on handoff failure) so the next non-intercepted native playback isn't muted.

## [1.4.7] - 2026-05-04

### Fixed
- **Intercept target dropdown was empty in many real-world setups**: the previous filter required `PLAY_MEDIA + PAUSE + VOLUME_SET + SEEK` simultaneously, which excluded common players (some Chromecasts and DLNA receivers don't expose `SEEK`; some media renderers don't expose `VOLUME_SET`). The dropdown now lists every player that supports `PLAY_MEDIA` (the only essential capability) and includes currently-unavailable players so a target can be preselected before it comes online. The mirror commands (pause / volume / seek) gracefully no-op when the target doesn't support them.

## [1.4.6] - 2026-05-04

### Fixed
- **`update_connection()` no longer triggers a duplicate `glagol.start()`** (upstream MA PR #3605, Copilot): the helper used to schedule a background reconnect, but the mDNS handler in `provider.py` also called `await async_setup()` (which itself awaits `glagol.start()`) for the not-connected branch — so a single mDNS update could trigger concurrent/duplicate reconnect attempts and potentially drop early WS updates before `update_handler` was set. The helper is now pure mutation (host/port + identifier); callers decide whether to (re)connect via `async_setup()`. For an already-connected player, Glagol's auto-reconnect loop handles a stale endpoint when it fails.
- **Removed dead `_encode_uid` / `MASK_EN` / `MASK_RU`** from `quasar.py` (upstream MA PR #3605, Copilot): unused helpers (originally for Yandex scenario-trigger UID encoding) — dropped to keep the module focused on what's actually called.
- **`_request_glagol()` error includes HTTP status** (upstream MA PR #3605, Copilot): the terminal-failure `RuntimeError` previously read just `"<url> returned error"`. Now `"<url> returned HTTP <status> (<reason>)"` so auth vs. network vs. server failures are distinguishable in logs.

## [1.4.5] - 2026-05-04

### Fixed
- **Remove dead `_intercept_self_stop_until` field** (upstream MA PR #3605, Copilot): the field was set right before `glagol.send({"command": "stop"})` to suppress mirror-pause on the resulting `playing=False`, but its only reader (the auto-end-session branch in `_handle_intercept_tick`) was removed in v1.4.0 (round 4 of the source-PR review) when the auto-end behaviour was found to break the contract that intercept survives Alice queries. With no reader, the field was just noise that made the state machine harder to reason about. Removed from `__init__`, from the lone write site, and from both test fixtures.

## [1.4.4] - 2026-05-04

### Fixed
- **Player registration race in `_create_player`** (upstream MA PR #3605, Copilot): the Glagol WS connect callback can fire `update_handler` very quickly, and the resulting `player.update_state()` would otherwise run before `mass.players.register_or_update(player)` had completed — triggering queue/state side-effects on a player the controller doesn't know about yet. Now register the player first, then start Glagol.
- **`refresh_cookies()` no longer raises on non-JSON responses** (upstream MA PR #3605, Copilot): when Yandex answered with an HTML error/redirect page (typical for stale cookies), the unconditional `await r.json()` raised `aiohttp.ContentTypeError` and broke the `_request()` 401 retry/reauth flow. Now treat any non-200 response or non-JSON body as "cookies invalid" and fall back to `login_token()`.

## [1.4.3] - 2026-05-04

### Fixed
- **Remaining mypy strict-mode errors in `test_on_glagol_update_dispatches_intercept_tick_via_create_task`** (upstream MA PR #3605 CI):
  - Use `setattr(player, "update_state", ...)` / `setattr(player, "set_current_media", ...)` to dodge `[misc] Cannot assign to final attribute`.
  - Initialise `_attr_playback_state` to `PlaybackState.IDLE` instead of `None` (matches the declared type).
  - Drop `# type: ignore[index]` from the `slow_first` / `fast` helpers in `test_concurrent_mirror_volume_serialised` — the strict-mode mypy doesn't need them and flagged them as `unused-ignore`.

## [1.4.2] - 2026-05-04

### Fixed
- **`_raise_if_failed` now also raises on non-`SUCCESS` status** (upstream MA PR #3605, Copilot): Glagol responses can carry `status: "ERROR"` (with an optional `message`) without populating an `error` key. The transport helpers (`play`, `pause`, `stop`, `next/prev_track`, `seek`, `volume_set`, `power`) all rely on `_raise_if_failed`, so a device-side rejection used to silently succeed in MA. The check now mirrors the previously inline logic in `play_media`. Bonus: `play_media` was deduplicated to call `_raise_if_failed` instead of repeating the same checks.
- **Portable coroutine introspection in `test_on_glagol_update_dispatches_intercept_tick_via_create_task`** (upstream MA PR #3605, Copilot): the test used `getattr(c, "__name__", "")` which is brittle across Python versions. Switched to `getattr(c.cr_code, "co_name", "")` which works for any coroutine object regardless of Python version.

## [1.4.1] - 2026-05-04

### Fixed
- **`tests/test_intercept.py`: silence mypy strict-mode noise from MagicMock-based tests** (upstream MA PR #3605 CI): added `# mypy: disable-error-code="attr-defined,method-assign,unreachable"` at the top of the file. The errors are intrinsic to using `MagicMock` / `AsyncMock` (assert-awaited helpers, mock reassignment) plus the `_intercept_enabled is False` branch in `test_intercept_master_switch_off` which mypy correctly proves unreachable. None affect runtime behaviour or actual type safety of the code under test.

## [1.4.0] - 2026-05-04

### Added
- **Experimental: intercept Alice playback to a target MA player.** When Alice starts music on a Yandex Station, the provider can stop the Station's native player, resolve the track via the `yandex_music` MA music provider, and start playback on a chosen target player. Volume / seek / pause / Alice-speech mirror from the Station to the target while intercept is active. Gated by two switches, both default OFF: a provider-level master toggle (`intercept_feature_enabled`) and a per-player toggle + target dropdown.

### Fixed
PR #45 review (Copilot) hardening before the feature ships:
- **Resolve before silencing the Station**: previously the stop command was sent first, so any failed lookup left the user with no audio. The Station is now muted only after a working track URI is in hand.
- **Self-stop window**: the `playing=False` produced by our own stop command no longer bounces back through pause-mirror and pauses the target we just started. The window timer is set right before `glagol.send({"command": "stop"})` rather than at tick-start, so a slow `get_item` doesn't burn most of it.
- **Alice voice activity actually pauses the target**: the original branch lived in `_handle_voice_interrupt` which is only reachable while `_external_playing=True` — meaning intercept-mode voice handling never fired. Moved into `_handle_intercept_tick`. The intercept session stays open so a follow-up Alice track resumes it; the same-track debounce is cleared so a quick same-song resume after a question triggers a fresh intercept; cmd_pause is issued once per Alice interaction rather than every WS tick; and a fresh `playerState.id` arriving in the same tick as alice activity does NOT start a new handoff over Alice's speech.
- **Serialise concurrent handoffs**: `_on_glagol_update` schedules `_handle_intercept_tick` as a background task on every WS message; two near-simultaneous `playing=True` updates could race and issue duplicate `stop`/`play_media` for the same track. `_maybe_intercept` is wrapped in an `asyncio.Lock`, stamps the debounce state up-front, and re-reads `time.time()` inside the lock so a slow handoff doesn't leave the next task with a stale timestamp that bypasses debounce.
- **Debounce failed attempts**: the 5-second debounce was only stamped after a successful handoff; missing `yandex_music` / lookup failures / no-URI tracks re-ran on every WS tick and spammed `WARNING` logs. The debounce timestamp is now updated on every attempt regardless of outcome.
- **Pre-validate target player before silencing the Station**: `_maybe_intercept` now checks `mass.players.get_player(target_id)` AND that the returned player has `available=True`, so a vanished or unavailable target doesn't trigger the stop.
- **End stale session on failed re-intercept**: when a new track fails mid-session, the previous target is paused and `_intercept_active` is cleared so seek/volume from the Station's native fallback playback don't leak to the stale target. The new track's debounce stamp is preserved so the failure isn't retried on every WS tick.
- **Clear `_intercept_active` on handoff failure**: when `play_media` raises after the Station was silenced, the active flag is cleared so mirror code stops forwarding to a target that isn't playing.
- **Clear debounce on session end**: physical-pause / end-of-queue now resets `_last_intercepted_track_id` and `_last_intercept_time` too, so a quick same-track resume isn't blocked.
- **Seek baseline anchored at play start**, not tick start — a slow handoff used to make every progress update look like a backwards seek.
- **Decoupled session vs debounce flags** in the pause helper (`_pause_target(clear_session=..., clear_debounce=...)`): callers can independently end the session or clear the debounce instead of always doing both.
- **Intercept track_id log demoted to DEBUG** — used to be INFO on every intercepted track, which would dominate the log once the format had been verified.
- **Serialise the whole intercept tick, not just `_maybe_intercept`**: the dispatcher schedules every WS message as a background task, so back-to-back updates could apply mirror operations out of order — an older `cmd_volume_set` finishing after a newer one would leave the target stale, and two near-simultaneous `LISTENING` ticks could race past `_alice_active_pause_sent` and send duplicate pauses. `_handle_intercept_tick` now holds `_intercept_lock` for the whole tick; `_maybe_intercept` is no longer self-locking (caller holds it).
- **Don't tear down the session on lingering `playing=False`**: after intercept the Station stays stopped, so every later state update arrives with `playing=False`. The previous design treated those (after the 3-second self-stop window) as user-initiated pauses, ending the session and breaking the contract that intercept survives Alice queries until the next track. The auto-end-session branch was removed; the session ends instead via the next intercepted track (success or clean failure) or provider unload.
- **`_pause_target` cleanup runs even if `cmd_pause` raises**: the state-cleanup (`_intercept_active`, debounce reset) is now in a `finally` block, so a target that went unavailable after the handoff doesn't leave the stale flags that would cause every later WS update to retry the failing path.
- **Filter intercept target dropdown by required PlayerFeatures** (PLAY_MEDIA, PAUSE, VOLUME_SET, SEEK): players that can't service the mirror commands no longer appear in the picker, so the incompatibility surfaces at config time rather than silently at runtime.
- **Honest copy in intercept config entries**: the labels now say "native Station playback" instead of "Alice playback" — the trigger is any native Yandex Music playback with a `playerState.id`, which is *typically* Alice but also fires for touch-UI starts.

## [1.3.4] - 2026-04-28

### Fixed
- **Announcements spoke the literal word "Announcement"** (upstream PR review, Copilot): `play_announcement` was reading `announcement.title` and synthesising it via Alice TTS, but MA core hard-codes that title to `"Announcement"` regardless of the original audio source — so every announcement on this provider TTS'd that one word instead of playing the requested clip. Removed the TTS branch entirely; announcements now stream the MA-hosted `announcement.uri` (which already includes the optional pre-announce chime). The dependent `_announcement_done` / `_announcement_phase` / `_check_announcement_done` machinery was dropped along with it.

### Security
- **`perform_qr_auth` session_id validation** (upstream PR review, Copilot): `session_id` was forwarded to `AuthenticationHelper`, which registers a callback route containing that value, without sanitisation. An attacker-controlled value with slashes / traversal sequences could have created an unintended route path. Now validated against the same `_SAFE_SESSION_ID_RE = ^[A-Za-z0-9_-]{1,64}$` pattern that already guarded `perform_device_auth`. Mirrored test added in `tests/test_auth.py`.

## [1.3.3] - 2026-04-28

### Fixed
- **Auth regression introduced in 1.3.2**: switching the dedicated `ClientSession` to MA's `create_clientsession()` helper broke Yandex Passport's session refresh — every `refresh_passport_cookies()` call now hit `HTTP 400 from redirect chain`, flooding logs and preventing player creation. Reverted to a bare `aiohttp.ClientSession(cookie_jar=CookieJar(quote_cookie=False))`. The exact incompatibility (custom connector / SSL context / `_default_headers` override) wasn't isolated, but the symptom was reproducible on every station and disappeared on rollback.

## [1.3.2] - 2026-04-28

### Changed
- **Player identifiers** (upstream PR review): `DeviceInfo.identifiers` now carries `IP_ADDRESS` and `UUID` (Yandex `device_id`) so MA can auto-link the player with other protocols on the same speaker. The IP identifier is refreshed in `update_connection()` when mDNS reports a new address.
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

## [1.3.3] - 2026-04-28

- fix: revert create_clientsession switch — Passport refresh 400s (`3ed2795`)
- Update ya-passport-auth requirement version (`858ce0d`)
- chore: update changelog for v1.3.2 [skip ci] (`e74d309`)

---

## [1.3.4] - 2026-04-28

- fix: address upstream PR #3605 review (Copilot) (`dfd3282`)
- docs: drop the "MAC not surfaced" caveat (`bf7f786`)
- chore: update changelog for v1.3.3 [skip ci] (`a0e5bd1`)

---

## [1.4.1] - 2026-05-04

- chore: bump version to 1.4.1 — mypy pragma for upstream CI (`36b981f`)
- test: silence mypy strict-mode noise in test_intercept (`a34183c`)
- style: auto-fix ruff (`52716fd`)

---

## [1.4.3] - 2026-05-04

- fix: residual mypy strict-mode errors in upstream PR #3605 CI (`c25a600`)
- style: auto-fix ruff (`bb1fe3f`)

---

## [1.4.4] - 2026-05-04

- fix: address upstream PR #3605 review (Copilot) (`e36c6d6`)
- chore: update changelog for v1.4.3 [skip ci] (`89cfc52`)

---

## [1.4.6] - 2026-05-04

- fix: address upstream PR #3605 review (Copilot) (`7305cf3`)
- style: auto-fix ruff (`396674f`)

---

## [1.4.7] - 2026-05-04

- style: codespell — fix preselect spelling (`2a5382a`)
- fix: intercept target dropdown was empty in real setups (`3fd292a`)
- chore: update changelog for v1.4.6 [skip ci] (`dc9e636`)

---

## [1.4.8] - 2026-05-04

- style: codespell — rephrase auto-changelog entry (`03a04fe`)
- style: auto-fix ruff (`3eaf7c7`)
- fix: mute Station before intercept stop to mask native-playback blip (`6730c5f`)
- chore: update changelog for v1.4.7 [skip ci] (`8cf195a`)

---

## [1.4.10] - 2026-05-04

- fix(security): redact Glagol send() debug log (`3c531df`)
- style: auto-fix ruff (`7b29f6d`)

---

## [1.4.12] - 2026-05-04

- chore: bump VERSION to 1.4.12 to sync description fix to upstream (`f6efc93`)
- fix: align CONF_INTERCEPT_TARGET description with actual filter (`19e75bb`)
- style: auto-fix ruff (`633401b`)

---

## [1.4.13] - 2026-05-04

- feat: surface intercept settings out of "advanced" section (`b787972`)
- chore: update changelog for v1.4.12 [skip ci] (`e61b20b`)

---

## [1.4.16] - 2026-05-05

- chore: bump VERSION to 1.4.16 to push setattr test fix to upstream (`22bf95b`)
- fix: setattr() for method-assign in test_provider_cascade fallback tests (`a01f085`)
- style: auto-fix ruff (`b282fcd`)

---

## [1.4.17] - 2026-05-05

- fix: same-track no-op during active intercept session (`6c95228`)
- chore: update changelog for v1.4.16 [skip ci] (`c6813f1`)

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
