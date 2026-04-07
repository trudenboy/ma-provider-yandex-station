# Changelog

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
