# Yandex Station Player Provider for Music Assistant

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
