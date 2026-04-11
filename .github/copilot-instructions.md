# Copilot Instructions

## Project Overview

Music Assistant (MA) Player Provider for Yandex Station smart speakers. Streams audio to Yandex Station devices via the local Glagol WebSocket protocol, adapted from AlexxIT/YandexStation.

## Architecture

```
MA Core ──play_media()──> YandexStationPlayer ──radio_play──> Glagol WS ──> Yandex Station
                                                                         <── state updates
```

All provider code lives in `provider/`. The module is installed into MA as `music_assistant.providers.yandex_station`.

**Key modules:**
- `provider.py` — `YandexStationProvider(PlayerProvider)`: mDNS + Quasar cloud discovery, player lifecycle
- `player.py` — `YandexStationPlayer(Player)`: transport controls, state from Glagol WS, playback via `externalCommandBypass` → `radio_play`
- `glagol.py` — `YandexGlagol`: persistent WebSocket client with auto-reconnect and command send/receive
- `quasar.py` — `YandexQuasar`: Quasar cloud API for device list and local IP/port resolution
- `session.py` — `YandexSession`: HTTP client with x_token → music_token → cookies → CSRF auth chain
- `protobuf.py` — minimal protobuf encoder/decoder for `externalCommandBypass` payload
- `__init__.py` — `setup()` + `get_config_entries()` (QR code and cookie auth flows)

**Discovery flow:** mDNS (`_yandexio._tcp.local.`) → enrich with Quasar cloud data → create `YandexGlagol` + `YandexStationPlayer` → register with MA.

**Playback flow:** `play_media()` → `resolve_stream_url()` → build `radio_play` payload → encode via `externalCommandBypass` (protobuf + base64) → send over Glagol WS → station fetches stream URL.

## Build, Test, and Lint

```bash
# Lint (ruff with ALL rules enabled, line-length=100, target py312)
uv run ruff check provider/ tests/
uv run ruff format --check provider/ tests/

# Type checking
uv run mypy --ignore-missing-imports provider

# Run all tests
uv run pytest

# Run a single test
uv run pytest tests/test_protobuf.py::test_roundtrip_simple -v

# All pre-commit hooks (ruff, mypy, codespell, etc.)
uv run pre-commit run --all-files
```

Tests use `asyncio_mode = "auto"` — async test functions are detected automatically, no `@pytest.mark.asyncio` needed.

## Code Conventions

- Every file starts with `from __future__ import annotations`
- All functions have type hints
- All I/O is async/await using aiohttp (no sync HTTP calls)
- Ruff uses `select = ["ALL"]` with a specific ignore list — check `ruff.toml` before suppressing a new rule
- `isort` treats `music_assistant` as first-party
- Commit messages: `type(scope): description` — types: feat, fix, docs, style, refactor, test, chore
- Follow MA provider patterns from Chromecast and `_demo_player_provider` in the MA server codebase

## Gotchas

- **Volume scale**: Glagol uses 0.0–1.0, MA uses 0–100. Convert in player (`round(volume / 100, 2)`)
- **Stop ≠ stop**: Glagol `stop` command is actually "pause". To stop `externalCommandBypass` playback, send `radio_play` with unreachable URL (`http://0.0.0.0/stop.flac`)
- **URL format**: Station requires a file extension in the stream URL (`.flac`, `.mp3`)
- **HTTP only**: Station rejects HTTPS for local network URLs; use IP addresses, not hostnames
- **Content-Length required**: Station does NOT support `Transfer-Encoding: chunked` — must send `Content-Length` header
- **Infinite replay**: Station replays a stream URL endlessly; MA's stream endpoint closing after track end solves this
- **State tracking for bypass**: Glagol doesn't report `playerState` for `externalCommandBypass` playback — the player tracks this optimistically via `_external_playing` / `_external_media`

## Testing

The `conftest.py` at repo root sets up namespace package aliases so `from music_assistant.providers.yandex_station.X import Y` works without a full MA server installation. Tests in `tests/` can import provider modules directly.
