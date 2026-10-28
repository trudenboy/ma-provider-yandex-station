# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Music Assistant (MA) Player Provider for Yandex Station smart speakers, requiring MA 2.10.0 or newer. Glagol WebSocket controls playback; the Station fetches audio from MA over HTTP. Adapted from AlexxIT/YandexStation.

## Architecture

```
MA Core --play_media()--> YandexStationPlayer --audio_play/radio_play--> Glagol WS --> Yandex Station
                                                                        <-- state updates
```

**Provider** (`provider/`): MA Player Provider with Glagol WebSocket client.
- `__init__.py` — `setup()` and credential gating
- `setup_flow.py` — guided account selection, device-code/QR/cookie login
- `auth.py` — wrappers over shared `ya_passport_auth.ma` login and token maintenance
- `provider.py` — `YandexStationProvider(PlayerProvider)`: mDNS discovery, Quasar API fallback, player lifecycle
- `player.py` — `YandexStationPlayer(Player)`: transport controls, announcements, Glagol state updates, experimental voice control and intercept handoff
- `alice.py` — `AliceTracker`: Alice's activity (idle, request, server-action phrase) from the reported `aliceState`
- `voice.py` — `VoiceRecovery`: resuming MA playback an Alice request stopped or delayed
- `glagol.py` — `YandexGlagol`: persistent WebSocket client with auto-reconnect, command send/receive, device token management
- `quasar.py` — `YandexQuasar`: cloud API for device list, device config, fallback commands
- `session.py` — `YandexSession`: HTTP requests and cookies, with Passport authentication delegated to the shared client
- `protobuf.py` — minimal protobuf encoder/decoder for `externalCommandBypass` payload
- `constants.py` — API URLs, config keys, protocol constants
- `manifest.json` — provider metadata for MA

### Key Flows

**Discovery:**
1. MA core discovers `_yandexio._tcp.local.` via mDNS → `on_mdns_service_state_change()`
2. Provider extracts deviceId, platform, host, port from mDNS properties
3. Enriches with Quasar cloud data (device name, model, house)
4. Creates `YandexGlagol` + `YandexStationPlayer`, registers with MA

**Playback:**
1. MA Queue Controller → `player.play_media(media)`
2. Claim the playback generation before awaiting `resolve_stream_url()`; discard the resolved URL if a newer play_media, pause, or stop, or the Station stopping the stream, has superseded the request. With voice control on, a URL resolved while Alice handles a request is not sent; the queue is resumed once she is done
3. Build `audio_play` when the Station advertises `audio_client`; otherwise use legacy `radio_play`
4. Encode via `externalCommandBypass` (protobuf) → send via Glagol WS
5. Station fetches the HTTP stream URL and plays audio; WAV is the default, with explicit saved codec preferences preserved
6. Publish the command result only while the same generation still owns an active external session
7. While the stream plays the player does not advertise `PlayerFeature.PAUSE` (the Station cannot pause it), so the core stops it and resumes the queue on play

**Authentication:**
1. Guided setup selects a linked Yandex Music instance or the provider's own credentials
2. Own mode uses the shared credential cascade; borrowed mode uses `BorrowedCredentialSource.resolve_credentials()` for a consistent pair of current owner tokens
3. The linked Yandex Music instance owns persisted token rotation; Station never writes its borrowed credentials
4. If the selected instance is missing, wait once on the domain-ready event, then resolve once and let MA retry a transient failure

**State Updates:**
1. Glagol WS sends state every 1-5 seconds
2. `_on_glagol_update()` learns firmware capabilities and parses `playerState` (progress, duration, title, playing)
3. Updates MA player attributes, calls `update_state()`
4. The Station reports an empty `playerState.id` for a stream handed over with `audio_play` and the Yandex Music track id for its own playback. That id, never the title, attributes a report: it confirms our stream's start, and a non-empty id after confirmation means the Station's own playback replaced the stream (no stopped report in between). A stream that replaces another MA stream (both report an empty id) and legacy `radio_play` (no id) are only attributed after a stopped report. Outside a session an empty id is a stream that already ended (the Station keeps reporting it for a moment after a stop), never the Station's own playback
5. A stream the Station stopped (finished, stopped on the speaker, or by Alice) ends the session and reports IDLE; the core resumes the queue on the next play
6. The Station's own playback is reported as the `yandex_station` source (`can_play_pause`), so it takes over from the MA queue

## Invariants

Rules that review found broken once. `tests/standalone/test_architecture_invariants.py` enforces them.

- **The Station's reports decide the state.** `play()`, `pause()` and `stop()` change no reported state (`_attr_*`, the external session) before the Station accepted them, and record only what it confirmed afterwards. A rejected or cancelled command leaves nothing to roll back; a stale report during a command is just the Station's state at that moment.
- **The core owns the queue.** The provider never calls `player_queues.resume/pause/stop/...` for its own player. A stream the Station cannot pause is expressed by not advertising `PlayerFeature.PAUSE` while it plays; the core then stops it and resumes the queue on play. The auto-resume after Alice goes through `mass.players.cmd_resume(player_id, source=player_id)`, scheduled with `mass.call_later(..., task_id=...)`; a user's transport command cancels it.
- **Only `alice.py` reads `aliceState`.** The same values mean different things in context (NONE is Alice's answer inside a request, a server-action phrase on its own). Voice control and intercept consume `AliceTracker` updates; `_on_glagol_update()` feeds the tracker once per report and hands the update to the intercept tick, which runs later.
- **Voice resume is one state machine.** `provider/voice.py` `VoiceRecovery` follows interrupted playback through awaiting Alice's answer, a scheduled resume and a running resume; the player only schedules the timer and calls the core. While it holds playback the player reports PAUSED (the core forwards stop and pause only to a player that is not idle), play resumes the owning queue at once, and a new request takes the decision over with its own volume baseline. Pausing while it holds playback is stopping (IDLE), so play resumes the queue. A running resume cannot be recalled from the core: if the Station's own playback takes over, or a new Alice request starts, meanwhile, the stream the resume asks for is dropped in `play_media()` and the new request decides; if Alice answers it, the running resume plays again rather than a second one being scheduled (the core's `call_later` starts its task with `abort_existing` under the same task id and would cancel the running resume midway). The owning queue is `PlayerMedia.source_id` (a group's queue for a group stream).
- **Current media goes through `_publish_media()`.** The core's `set_current_media` merges into the previous media; the helper passes every field and clears the media when the URI changes.
- **No bare `asyncio.create_task` in the player.** Use the core scheduler (`mass.create_task`, `mass.call_later` with a `task_id`), which keeps references, cancels on unload and logs failures.
- **Authorization belongs to the core.** Never read `user.player_filter` or re-implement access rules: full-access users ignore their filter and a client may use its own player. Ask the core with `self.mass.players.get_player_state(player_id)`, which raises `InsufficientPermissions` under the running core's rules (MA 2.10 and later).
- **Provider API commands do not bump `API_SCHEMA_VERSION`.** They exist only while the provider is configured, so clients detect them through the provider, not the schema version. Upstream provider commands (FastMCP, AI Radio, Music Quiz, party) follow the same practice.

## Development Setup

```bash
# From this provider repository; Python requirements are in pyproject.toml
rtk proxy ./scripts/setup.sh
```

The root `conftest.py` supplies MA stubs for standalone tests. To validate the real
installed MA classes as well, preload them before pytest:

```bash
rtk proxy .venv/bin/python -c 'import music_assistant.models.player; import music_assistant.models.player_provider; import music_assistant.helpers.config_entries; import pytest; raise SystemExit(pytest.main(["-q", "tests/test_player_state.py"]))'
```

If imports fail because a core path imports another provider's dependency, use
the version from `requirements_all.txt` at the MA revision pinned in `uv.lock`.
The standalone project's dependency set does not include every MA provider.

## Code Standards

- **Python**: PEP 8, type hints on all functions, `from __future__ import annotations`
- **Commits**: `type(scope): description` — types: feat, fix, docs, style, refactor, test, chore
- **Async**: All I/O uses async/await (aiohttp)
- **MA conventions**: Follow patterns from Chromecast and `_demo_player_provider`
- **DO NOT use subagents (Task tool) without explicit user instruction or confirmation!**

## Key Files Reference (MA Server)

| Path | Purpose |
|------|---------|
| `music_assistant/models/player.py` | `Player` base class |
| `music_assistant/models/player_provider.py` | `PlayerProvider` base class |
| `music_assistant/providers/_demo_player_provider/` | Template provider |
| `music_assistant/providers/chromecast/` | Reference: mDNS + socket + callbacks |

## Gotchas

- **URL format**: Yandex Station requires file extension in stream URL (`.flac`, `.mp3`). MA's `resolve_stream_url()` already provides this.
- **HTTP for local streams**: the firmware's libcurl client picks HTTP or HTTPS from the URL scheme and has no certificate pinning, but it verifies certificates normally, so an HTTPS URL with a self-signed or LAN-only certificate fails. Use plain HTTP for LAN stream URLs
- **Commands without the wake word**: the Station recognizes about 25 commands locally without "Алиса" ("стоп", "громче", …). They never move `aliceState` off `IDLE`, so voice-control and intercept logic must not rely on `LISTENING`/`SPEAKING` to see them; they show up only as `playing`/`volume` changes
- **`aliceState=NONE`**: reported while the Station speaks a server-action phrase (`repeat_phrase`, `yandex_station/say`); the music is only ducked and `playing` stays true. From IDLE it is `AliceActivity.PHRASE`, not a voice request
- **Voice requests duck, not stop**: during "Алиса, …" requests the Station goes LISTENING → BUSY → NONE (answer) → IDLE with `playing=True` throughout and the MA stream only ducked. An external session is interrupted only when `playing` turns false. `AliceTracker` keeps BUSY, and NONE inside a request, in the request; a NONE inside it is Alice's answer and counts as speech for the auto-resume. During an intercept session a standalone NONE unmutes the Station for the phrase (some firmware ties Alice's speech to the Station volume) and mutes it again at IDLE, without pausing the target
- **Alice's speech follows the Station volume** (verified on yandexmini_2): at volume 0 a `say` phrase is inaudible, so intercept unmutes the Station for a standalone phrase. The Station's ducked music is audible for about half a second after the phrase, until the IDLE report triggers the re-mute; accepted
- **The Station's own track as a Yandex Music item**: with a linked Yandex Music instance that is loaded and available (`linked_music_instance`, looked up with `return_unavailable=True` because the core otherwise falls back to another instance of the domain) a reported `type=Track` becomes `<instance>://track/<id>`, so the core's "add currently playing to favorites" likes it on the Station's account. `extra.coverURI` is a template (`…/%%`) turned into `https://…/400x400`
- **IP, not hostname**: Station prefers IP addresses over DNS names
- **Infinite loop**: Station replays URL endlessly. MA stream endpoint closes after track ends, solving this naturally.
- **Volume scale**: Glagol uses 0.0-1.0, MA uses 0-100. Convert in player.
- **Pause/stop**: Glagol `stop` pauses the Station's own playback (`play` resumes it) but ends an MA stream for good; legacy external sessions need an invalid `radio_play` URL to replace the stream.
- **Request ordering**: MA can proceed without its player lock after a 30-second timeout. Playback generation guards must cover URL resolution as well as command acknowledgements; stale cleanup must preserve a newer request.
