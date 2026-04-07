# Changelog

## [0.1.1] - 2026-04-07

- fix: remove duplicate type annotation for _auth_payload (mypy no-redef) (`a11e504`)
- fix: add --frozen to uv run in pre-commit to prevent uv.lock modification in CI (`27e7f4f`)
- fix: add changelog marker for release workflow (`0000d88`)

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
