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
2. Claim the playback generation before awaiting `resolve_stream_url()`; discard the resolved URL if a newer play, pause, or stop has superseded the request
3. Build `audio_play` when the Station advertises `audio_client`; otherwise use legacy `radio_play`
4. Encode via `externalCommandBypass` (protobuf) → send via Glagol WS
5. Station fetches the HTTP stream URL and plays audio; WAV is the default, with explicit saved codec preferences preserved
6. Publish the command result only while the same generation still owns an active external session

**Authentication:**
1. Guided setup selects a linked Yandex Music instance or the provider's own credentials
2. Own mode uses the shared credential cascade; borrowed mode uses `BorrowedCredentialSource.resolve_credentials()` for a consistent pair of current owner tokens
3. The linked Yandex Music instance owns persisted token rotation; Station never writes its borrowed credentials
4. If the selected instance is missing, wait once on the domain-ready event, then resolve once and let MA retry a transient failure

**State Updates:**
1. Glagol WS sends state every 1-5 seconds
2. `_on_glagol_update()` learns firmware capabilities and parses `playerState` (progress, duration, title, playing)
3. Updates MA player attributes, calls `update_state()`
4. Audio-client sessions distinguish track completion from physical pause and reject stale source state during startup

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
- **HTTP only for local**: Station may reject HTTPS for local network URLs
- **IP, not hostname**: Station prefers IP addresses over DNS names
- **Infinite loop**: Station replays URL endlessly. MA stream endpoint closes after track ends, solving this naturally.
- **Volume scale**: Glagol uses 0.0-1.0, MA uses 0-100. Convert in player.
- **Pause/stop**: Audio-client sessions use Glagol `stop`; legacy external sessions need an invalid `radio_play` URL to replace the stream.
- **Request ordering**: MA can proceed without its player lock after a 30-second timeout. Playback generation guards must cover URL resolution as well as command acknowledgements; stale cleanup must preserve a newer request.
