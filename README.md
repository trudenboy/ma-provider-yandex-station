# Yandex Station Player Provider for Music Assistant


<!-- >>> ma-provider-tools sync (readme header) — DO NOT EDIT >>> -->
[![CI](https://github.com/trudenboy/ma-provider-yandex-station/actions/workflows/test.yml/badge.svg)](https://github.com/trudenboy/ma-provider-yandex-station/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/trudenboy/ma-provider-yandex-station?display_name=tag)](https://github.com/trudenboy/ma-provider-yandex-station/releases/latest)
[![License](https://img.shields.io/github/license/trudenboy/ma-provider-yandex-station)](LICENSE)
[![Music Assistant](https://img.shields.io/badge/Music%20Assistant-9070B8?logo=python&logoColor=white)](https://www.music-assistant.io/)[![stable](https://img.shields.io/endpoint?url=https%3A%2F%2Ftrudenboy.github.io%2Fma-provider-tools%2Fbadges%2Fyandex_station-stable.json)](https://github.com/music-assistant/server/releases/latest)[![beta](https://img.shields.io/endpoint?url=https%3A%2F%2Ftrudenboy.github.io%2Fma-provider-tools%2Fbadges%2Fyandex_station-beta.json)](https://github.com/music-assistant/server/releases?q=prerelease)
[![Stars](https://img.shields.io/github/stars/trudenboy/ma-provider-yandex-station?style=flat&logo=github)](https://github.com/trudenboy/ma-provider-yandex-station/stargazers)

**📖 [Documentation / Документация](https://trudenboy.github.io/ma-provider-yandex-station/)** · **🔄 [Changelog / Журнал](CHANGELOG.md)** · **🐛 [Issues / Проблемы](https://github.com/trudenboy/ma-provider-yandex-station/issues)** · **💬 [Discussions / Обсуждения](https://github.com/trudenboy/ma-provider-yandex-station/discussions)**

**Related providers:** [Yandex Smart Home](https://github.com/trudenboy/ma-provider-yandex-smarthome) · [Yandex Alice](https://github.com/trudenboy/ma-provider-yandex-alice) · [Yandex Music](https://github.com/trudenboy/ma-provider-yandex-music)
<!-- <<< ma-provider-tools sync (readme header) <<< -->

Play music on Yandex Station smart speakers via the local Glagol WebSocket protocol.

## Features

- 🔊 **Local playback** via Glagol protocol (low latency, no cloud dependency for audio)
- 🔍 **Auto-discovery** via mDNS (`_yandexio._tcp.local.`)
- 📡 **Real-time state** updates via WebSocket
- 🎵 **Lossless audio** — low-latency WAV streaming with proper Content-Length; FLAC, MP3 and AAC remain selectable
- 🎛️ **Full transport control** — play, pause, stop, seek, next/previous, volume
- 📢 **TTS announcements** — Alice speaks notification text natively
- ⚡ **Power control** — on/off via Yandex scenarios
- 🗣️ **Voice control** *(experimental)* — auto-resume after Alice voice queries

## Requirements

- Yandex Station smart speaker (any model with Alice)
- Yandex account
- Music Assistant server (2.10.0+)

## Setup

Yandex Station ships with Music Assistant itself — there is nothing to install
from this repository. It is included in every Music Assistant release since
**2.10.0**, including the Home Assistant app (add-on) and the Docker image.
Newer provider versions reach the beta channel first.

1. Update Music Assistant to 2.10.0 or newer.
2. Open **Settings → Providers**, click **Add provider** and choose **Yandex Station**.
3. Pick the Yandex account: borrow it from a configured Yandex Music provider,
   or sign in with this provider's own credentials (see [Authentication](#authentication)).
4. Stations on the same local network as Music Assistant are discovered
   automatically via mDNS and appear under **Settings → Players**.

> **По-русски.** Провайдер входит в состав Music Assistant начиная с версии
> 2.10.0 (в том числе в приложении/дополнении для Home Assistant) — отдельно
> ничего устанавливать не нужно. Обновите Music Assistant, затем откройте
> **Настройки → Провайдеры → Добавить провайдер → Yandex Station** и войдите
> в аккаунт Яндекса одним из способов ниже. Колонки в той же локальной сети
> появятся в **Настройки → Плееры** автоматически.

## Streaming and Startup Delay

WAV is the default output codec, and live sources such as Ynison prefer WAV.
This avoids the long startup delay observed with FLAC on Mini 2. WAV carries
uncompressed, lossless PCM and uses more network bandwidth than FLAC.

Existing saved codec preferences are preserved when updating. To apply the
low-latency profile, open the Station's advanced player settings, select **WAV**
as the output codec, and enable **Prefer low-latency WAV for live sources**.
Keep the default **forced content length** HTTP profile. Other codecs remain
available for devices or firmware that need them.

See the [measurements and test limitations](docs/reviews/2026-10-03-wav-latency-test.md)
for the queue and Ynison comparisons.

## Authentication

If a Yandex Music provider is already configured, choose it as the account
source and skip the login: the Station borrows that account, and token renewal
is handled there. Otherwise pick one of the login methods:

### Device code (recommended)
Open the verification URL that setup shows (on any device) and enter the short
code. A fresh code appears automatically if the old one expires.

### QR code
Scan the QR code with the Yandex app and confirm the login.

### Browser cookies (fallback)
1. Log in at [passport.yandex.ru/profile](https://passport.yandex.ru/profile) in a desktop browser.
2. Export the cookies for that page with a "Copy Cookies" style browser extension.
3. Paste the result into the setup dialog. A JSON array and a raw `name=value; …` cookie string both work.

Keep **Remember session** enabled so tokens are refreshed automatically.

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
