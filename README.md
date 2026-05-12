# Yandex Station Player Provider for Music Assistant


<!-- >>> ma-provider-tools sync (readme header) — DO NOT EDIT >>> -->
[![CI](https://github.com/trudenboy/ma-provider-yandex-station/actions/workflows/test.yml/badge.svg)](https://github.com/trudenboy/ma-provider-yandex-station/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/trudenboy/ma-provider-yandex-station?display_name=tag)](https://github.com/trudenboy/ma-provider-yandex-station/releases/latest)
[![License](https://img.shields.io/github/license/trudenboy/ma-provider-yandex-station)](LICENSE)
[![Music Assistant](https://img.shields.io/badge/Music%20Assistant-9070B8?logo=python&logoColor=white)](https://www.music-assistant.io/)[![stable](https://img.shields.io/endpoint?url=https%3A%2F%2Ftrudenboy.github.io%2Fma-provider-tools%2Fbadges%2Fyandex_station-stable.json)](https://github.com/music-assistant/server/releases/latest)[![beta](https://img.shields.io/endpoint?url=https%3A%2F%2Ftrudenboy.github.io%2Fma-provider-tools%2Fbadges%2Fyandex_station-beta.json)](https://github.com/music-assistant/server/releases?q=prerelease)
[![Stars](https://img.shields.io/github/stars/trudenboy/ma-provider-yandex-station?style=flat&logo=github)](https://github.com/trudenboy/ma-provider-yandex-station/stargazers)

**📖 [Documentation / Документация](https://trudenboy.github.io/ma-provider-yandex-station/)** · **🔄 [Changelog / Журнал](CHANGELOG.md)** · **🐛 [Issues / Проблемы](https://github.com/trudenboy/ma-provider-yandex-station/issues)** · **💬 [Discussions / Обсуждения](https://github.com/trudenboy/ma-provider-yandex-station/discussions)**

**Related providers:** [Yandex Smart Home](https://github.com/trudenboy/ma-provider-yandex-smarthome) · [Yandex Alice](https://github.com/trudenboy/ma-provider-yandex-alice)
<!-- <<< ma-provider-tools sync (readme header) <<< -->

Play music on Yandex Station smart speakers via the local Glagol WebSocket protocol.

## Features

- 🔊 **Local playback** via Glagol protocol (low latency, no cloud dependency for audio)
- 🔍 **Auto-discovery** via mDNS (`_yandexio._tcp.local.`)
- 📡 **Real-time state** updates via WebSocket
- 🎵 **Lossless audio** — FLAC streaming with proper Content-Length
- 🎛️ **Full transport control** — play, pause, stop, seek, next/previous, volume
- 📢 **TTS announcements** — Alice speaks notification text natively
- ⚡ **Power control** — on/off via Yandex scenarios
- 🗣️ **Voice control** *(experimental)* — auto-resume after Alice voice queries

## Requirements

- Yandex Station smart speaker (any model with Alice)
- Yandex account
- Music Assistant server (2.9+)

## Setup

1. Install the provider in Music Assistant
2. Authenticate via QR code (scan with Yandex app) or paste cookies
3. Yandex Station devices will be auto-discovered on the local network

## Authentication

### QR Code (recommended)
During setup, a QR code is displayed. Scan it with the Yandex app or camera to log in.

### Cookies (advanced fallback)
Paste Yandex session cookies as a JSON array from browser dev tools. See [detailed guide](docs/cookies-auth.md).

## Voice Control (Experimental)

When enabled in player advanced settings, the provider detects when you talk to Alice during playback:

- **"Алиса, стоп"** — pauses MA queue (resume via UI)
- **"Алиса, какая погода?"** — pauses, Alice answers, then auto-resumes playback
- **"Алиса, громче/тише"** — adjusts volume and auto-resumes

> ⚠️ Disabled by default. Enable in **Settings → Players → [Your Station] → Show advanced → Voice control integration**.

## Known Limitations

- Voice commands "дальше"/"назад" cannot advance the MA queue (Alice doesn't see bypass streams)
- Seek via voice is not supported
- Requires HTTP (not HTTPS) for local streaming — station rejects HTTPS on LAN
- Station requires `Content-Length` header (chunked encoding = silence)

## Credits

- [AlexxIT/YandexStation](https://github.com/AlexxIT/YandexStation) — reverse-engineered Glagol protocol and Yandex authentication
- [Music Assistant](https://music-assistant.io/) — the music platform

## License

MIT
