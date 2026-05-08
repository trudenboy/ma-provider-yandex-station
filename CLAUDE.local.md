# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Music Assistant (MA) Player Provider for Yandex Station smart speakers. Streams music to Yandex Station via the local Glagol WebSocket protocol. Adapted from AlexxIT/YandexStation.

## Architecture

```
MA Core --play_media()--> YandexStationPlayer --radio_play--> Glagol WS --> Yandex Station
                                                                        <-- state updates
```

**Provider** (`provider/`): MA Player Provider with Glagol WebSocket client.
- `__init__.py` — `setup()`, `get_config_entries()` (x_token, music_token)
- `provider.py` — `YandexStationProvider(PlayerProvider)`: mDNS discovery, Quasar API fallback, player lifecycle
- `player.py` — `YandexStationPlayer(Player)`: transport controls (play/pause/stop/seek/volume/next/prev), state updates from Glagol WS, `play_media()` via `radio_play` command
- `glagol.py` — `YandexGlagol`: persistent WebSocket client with auto-reconnect, command send/receive, device token management
- `quasar.py` — `YandexQuasar`: cloud API for device list, device config, fallback commands
- `session.py` — `YandexSession`: Yandex Passport auth (x_token → music_token → cookies → CSRF), HTTP client with retry/auth refresh
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
2. `resolve_stream_url()` → `http://192.168.x.x:8097/streams/{id}.flac`
3. Build `radio_play` payload: `{streamUrl, title, imageUrl, force_restart_player}`
4. Encode via `externalCommandBypass` (protobuf) → send via Glagol WS
5. Station fetches stream URL and plays audio

**State Updates:**
1. Glagol WS sends state every 1-5 seconds
2. `_on_glagol_update()` parses `playerState` (progress, duration, title, playing)
3. Updates MA player attributes, calls `update_state()`

## Development Setup

```bash
# Clone MA server fork alongside this project
cd /tmp && git clone https://github.com/trudenboy/ma-server.git

# Setup venv, install deps, symlink provider
./scripts/link-to-ma.sh  # (when available, after wrapper distribution)

# Or manual setup:
cd /tmp/ma-server && python -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
ln -s /path/to/ma-provider-yandex-station/provider .venv/lib/python3.12/site-packages/music_assistant/providers/yandex_station
```

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
- **`stop` command**: Glagol's "stop" is actually "pause". Use it for both pause() and stop().
