# Yandex Station Player Provider for Music Assistant

Play music on Yandex Station smart speakers via the local Glagol WebSocket protocol.

## Features

- 🔊 **Local playback** via Glagol protocol (low latency, no cloud dependency for commands)
- 🔍 **Auto-discovery** via mDNS (`_yandexio._tcp.local.`)
- 📡 **Real-time state** updates via WebSocket (play/pause, progress, volume)
- 🎵 **FLAC support** for lossless audio streaming
- 🎛️ **Full transport control**: play, pause, stop, seek, next/previous, volume

## Requirements

- Yandex Station smart speaker (any model with Alice)
- Yandex account with x-token
- Music Assistant server

## Setup

1. Install the provider in Music Assistant
2. Configure with your Yandex x-token
3. Yandex Station devices will be auto-discovered on the local network

## How to get x-token

The x-token is a long-lived authentication token (~1 year). You can obtain it from:
- [AlexxIT/YandexStation](https://github.com/AlexxIT/YandexStation) Home Assistant integration
- Browser developer tools on passport.yandex.ru

## Credits

- [AlexxIT/YandexStation](https://github.com/AlexxIT/YandexStation) — reverse-engineered Glagol protocol and Yandex authentication
- [Music Assistant](https://music-assistant.io/) — the music platform

## License

MIT
