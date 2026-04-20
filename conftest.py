"""Root conftest: ensure provider/ is importable as music_assistant.providers.yandex_station."""

from __future__ import annotations

import contextlib
import importlib.util
import sys
import types
from pathlib import Path

# Make the provider/ directory importable as music_assistant.providers.yandex_station
_provider_path = Path(__file__).parent / "provider"

# Ensure parent namespace packages exist
for _pkg in ("music_assistant", "music_assistant.providers"):
    if _pkg not in sys.modules:
        _mod = types.ModuleType(_pkg)
        _mod.__path__ = []  # type: ignore[attr-defined]
        _mod.__package__ = _pkg
        sys.modules[_pkg] = _mod


# ── Stub MA modules that aren't installed in the test venv ───────────
def _ensure_stub(name: str, attrs: dict | None = None) -> types.ModuleType:
    """Register a stub module if the real one isn't importable.

    If the module already exists, merge any provided attrs into it.
    """
    if name in sys.modules:
        mod = sys.modules[name]
        if attrs:
            for k, v in attrs.items():
                setattr(mod, k, v)
        return mod
    mod = types.ModuleType(name)
    mod.__package__ = name
    if attrs:
        for k, v in attrs.items():
            setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# music_assistant_models stubs (only when not installed)
try:
    import music_assistant_models  # noqa: F401
except ImportError:

    class _LoginFailed(Exception):
        pass

    class _InvalidDataError(Exception):
        pass

    class _ProviderUnavailableError(Exception):
        pass

    class _ConfigEntry:
        def __init__(self, **kw: object) -> None:
            self.__dict__.update(kw)

    class _ConfigEntryType:
        LABEL = "label"
        ACTION = "action"
        SECURE_STRING = "secure_string"
        BOOLEAN = "boolean"
        STRING = "string"
        INTEGER = "integer"

    class _ProviderFeature:
        pass

    class _ProviderManifest:
        pass

    class _PlaybackState:
        IDLE = "idle"
        PLAYING = "playing"
        PAUSED = "paused"

    class _PlayerFeature:
        pass

    class _PlayerType:
        PLAYER = "player"

    class _PlayerCommandFailed(Exception):
        pass

    class _ConfigValueType:
        pass

    _ensure_stub("music_assistant_models")
    _ensure_stub(
        "music_assistant_models.errors",
        {
            "LoginFailed": _LoginFailed,
            "InvalidDataError": _InvalidDataError,
            "ProviderUnavailableError": _ProviderUnavailableError,
            "PlayerCommandFailed": _PlayerCommandFailed,
        },
    )
    _ensure_stub(
        "music_assistant_models.config_entries",
        {
            "ConfigEntry": _ConfigEntry,
            "ConfigValueType": _ConfigValueType,
            "ProviderConfig": object,
        },
    )
    _ensure_stub(
        "music_assistant_models.enums",
        {
            "ConfigEntryType": _ConfigEntryType,
            "ProviderFeature": _ProviderFeature,
            "PlaybackState": _PlaybackState,
            "PlayerFeature": _PlayerFeature,
            "PlayerType": _PlayerType,
        },
    )
    _ensure_stub("music_assistant_models.provider", {"ProviderManifest": _ProviderManifest})

# music_assistant stubs (helpers, models)
try:
    from music_assistant.helpers.auth import AuthenticationHelper  # noqa: F401
except (ImportError, AttributeError):

    class _AuthenticationHelper:  # type: ignore[no-redef]
        def __init__(self, *a: object, **kw: object) -> None:
            pass

        async def __aenter__(self) -> _AuthenticationHelper:
            return self

        async def __aexit__(self, *a: object) -> None:
            pass

        def send_url(self, url: str) -> None:
            pass

    _helpers = _ensure_stub("music_assistant.helpers")
    _helpers.__path__ = []  # type: ignore[attr-defined]
    _ensure_stub("music_assistant.helpers.auth", {"AuthenticationHelper": _AuthenticationHelper})

try:
    from music_assistant.models.player_provider import PlayerProvider  # noqa: F401
except (ImportError, AttributeError):

    class _PlayerProvider:  # type: ignore[no-redef]
        instance_id = "stub_instance"

        def __init__(self, *a: object, **kw: object) -> None:
            self.logger = __import__("logging").getLogger(__name__)
            self.mass = a[0] if a else None
            self.config = a[2] if len(a) > 2 else None

        def _update_config_value(
            self, key: str, value: object, encrypted: bool = False
        ) -> None:
            """Mirror Provider._update_config_value so tests can assert behaviour."""
            if self.mass is not None:
                self.mass.config.set_raw_provider_config_value(
                    getattr(self, "instance_id", "stub_instance"), key, value, encrypted
                )
            cfg = getattr(self, "config", None)
            values = getattr(cfg, "values", None)
            if values is not None and key in values:
                values[key].value = value

    class _Player:  # type: ignore[no-redef]
        def __init__(self, *a: object, **kw: object) -> None:
            pass

    class _PlayerMedia:  # type: ignore[no-redef]
        pass

    class _DeviceInfo:  # type: ignore[no-redef]
        pass

    _models = _ensure_stub("music_assistant.models")
    _models.__path__ = []  # type: ignore[attr-defined]
    _ensure_stub("music_assistant.models.player_provider", {"PlayerProvider": _PlayerProvider})
    _ensure_stub(
        "music_assistant.models.player",
        {"Player": _Player, "PlayerMedia": _PlayerMedia, "DeviceInfo": _DeviceInfo},
    )
    _ensure_stub("music_assistant.models", {"ProviderInstanceType": object})
    _ensure_stub(
        "music_assistant.constants",
        {
            "CONF_ENTRY_HTTP_PROFILE_DEFAULT_3": object(),
            "CONF_ENTRY_OUTPUT_CODEC": object(),
        },
    )

try:
    from music_assistant.mass import MusicAssistant  # noqa: F401
except (ImportError, AttributeError):
    _ensure_stub("music_assistant.mass", {"MusicAssistant": object})

# ── End stubs ────────────────────────────────────────────────────────

# Insert provider/ into sys.path so its modules are importable
if str(_provider_path) not in sys.path:
    sys.path.insert(0, str(_provider_path))

# Register a package alias so `from music_assistant.providers.yandex_station.X import Y` works
_spec = importlib.util.spec_from_file_location(
    "music_assistant.providers.yandex_station",
    _provider_path / "__init__.py",
    submodule_search_locations=[str(_provider_path)],
)
if _spec and "music_assistant.providers.yandex_station" not in sys.modules:
    _pkg_mod = importlib.util.module_from_spec(_spec)
    _pkg_mod.__path__ = [str(_provider_path)]  # type: ignore[attr-defined]
    _pkg_mod.__package__ = "music_assistant.providers.yandex_station"
    sys.modules["music_assistant.providers.yandex_station"] = _pkg_mod
    with contextlib.suppress(
        Exception
    ):  # provider __init__ may have MA-specific imports; best-effort
        _spec.loader.exec_module(_pkg_mod)  # type: ignore[union-attr]
