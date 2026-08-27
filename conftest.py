"""Root conftest: ensure provider/ is importable as music_assistant.providers.yandex_station."""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiohttp

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
    """
    Register a stub module if the real one isn't importable.

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
        POWER = "power"
        PLAY_MEDIA = "play_media"
        PLAY_ANNOUNCEMENT = "play_announcement"
        VOLUME_SET = "volume_set"
        VOLUME_MUTE = "volume_mute"
        PAUSE = "pause"
        NEXT_PREVIOUS = "next_previous"
        SEEK = "seek"

    class _PlayerType:
        PLAYER = "player"
        STEREO_PAIR = "stereo_pair"
        GROUP = "group"

    class _IdentifierType:
        MAC_ADDRESS = "mac_address"
        SERIAL_NUMBER = "serial_number"
        UUID = "uuid"
        CAST_UUID = "cast_uuid"
        AIRPLAY_ID = "airplay_id"
        IP_ADDRESS = "ip_address"
        UNKNOWN = "unknown"

    class _PlayerCommandFailed(Exception):
        pass

    class _UnsupportedFeaturedException(Exception):
        pass

    class _ConfigValueType:
        pass

    class _ConfigValueOption:
        # Mirrors music_assistant_models.config_entries.ConfigValueOption:
        # ``value`` is the first positional field, ``title`` is optional and
        # resolved from translations when omitted.
        def __init__(self, value: object, title: str | None = None) -> None:
            self.value = value
            self.title = title

    class _MediaType:
        TRACK = "track"
        ALBUM = "album"
        ARTIST = "artist"
        PLAYLIST = "playlist"
        RADIO = "radio"

    class _QueueOption:
        REPLACE = "replace"
        PLAY = "play"
        ADD = "add"
        NEXT = "next"

    _ensure_stub("music_assistant_models")
    _ensure_stub(
        "music_assistant_models.errors",
        {
            "LoginFailed": _LoginFailed,
            "InvalidDataError": _InvalidDataError,
            "ProviderUnavailableError": _ProviderUnavailableError,
            "PlayerCommandFailed": _PlayerCommandFailed,
            "UnsupportedFeaturedException": _UnsupportedFeaturedException,
        },
    )
    _ensure_stub(
        "music_assistant_models.config_entries",
        {
            "ConfigEntry": _ConfigEntry,
            "ConfigValueType": _ConfigValueType,
            "ConfigValueOption": _ConfigValueOption,
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
            "IdentifierType": _IdentifierType,
            "MediaType": _MediaType,
            "QueueOption": _QueueOption,
        },
    )
    _ensure_stub("music_assistant_models.provider", {"ProviderManifest": _ProviderManifest})

_playback_target_player_type = getattr(
    importlib.import_module("music_assistant_models.enums"), "PlayerType"
)

# music_assistant stubs (helpers, models)
try:
    import music_assistant.helpers  # noqa: F401
except (ImportError, AttributeError):
    _helpers = _ensure_stub("music_assistant.helpers")
    _helpers.__path__ = []  # type: ignore[attr-defined]
    _ensure_stub(
        "music_assistant.helpers.config_entries",
        {
            "PLAYBACK_TARGET_TYPES": {
                _playback_target_player_type.PLAYER,
                _playback_target_player_type.STEREO_PAIR,
                _playback_target_player_type.GROUP,
            }
        },
    )

    def _create_clientsession(_mass: object, **kwargs: object) -> object:
        return aiohttp.ClientSession(**kwargs)  # type: ignore[arg-type]

    _ensure_stub(
        "music_assistant.helpers.aiohttp_client",
        {"create_clientsession": _create_clientsession},
    )

try:
    from music_assistant.models.player_provider import PlayerProvider  # noqa: F401
except (ImportError, AttributeError):

    class _PlayerProvider:  # type: ignore[no-redef]
        instance_id = "stub_instance"

        def __init__(self, *a: object, **kw: object) -> None:
            self.logger = __import__("logging").getLogger(__name__)
            self.mass = a[0] if a else None
            self.config = a[2] if len(a) > 2 else None

        def _update_config_value(self, key: str, value: object, encrypted: bool = False) -> None:
            """Mirror Provider._update_config_value so tests can assert behaviour."""
            if self.mass is not None:
                self.mass.config.set_raw_provider_config_value(
                    getattr(self, "instance_id", "stub_instance"), key, value, encrypted
                )
            cfg = getattr(self, "config", None)
            values = getattr(cfg, "values", None)
            if values is not None and key in values:
                values[key].value = value

        def get_setup_value(self, key: str, default: object = None) -> object:
            """Mirror Provider.get_setup_value for the lightweight test harness."""
            setup_data = getattr(self.config, "setup_data", {})
            if key in setup_data:
                return setup_data[key]
            return self.config.get_value(key, default)

        def _update_setup_data(
            self, key: str, value: object, immediate: bool = True
        ) -> None:
            """Mirror Provider._update_setup_data for the lightweight test harness."""
            if self.mass is not None:
                self.mass.config.set_raw_provider_config_value(
                    getattr(self, "instance_id", "stub_instance"),
                    key,
                    value,
                    True,
                    immediate,
                )
            self.config.setup_data[key] = value

    class _Player:  # type: ignore[no-redef]
        def __init__(self, *a: object, **kw: object) -> None:
            pass

        @property
        def provider(self) -> object:
            """Return the owning provider, matching the read-only core property."""
            return self._provider

        @property
        def player_id(self) -> str:
            return getattr(self, "_player_id", "")

    class _PlayerMedia:  # type: ignore[no-redef]
        pass

    class _DeviceInfo:  # type: ignore[no-redef]
        def __init__(self, **kw: object) -> None:
            self.__dict__.update(kw)
            self.identifiers: dict[str, str] = {}

        def add_identifier(self, identifier_type: str, value: str | None) -> None:
            if not value:
                self.identifiers.pop(identifier_type, None)
                return
            self.identifiers[identifier_type] = value

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

    class _SetupFlowError(Exception):
        def __init__(self, message: str, translation_key: str | None = None) -> None:
            super().__init__(message)
            self.translation_key = translation_key

    class _StepExpiredError(Exception):
        pass

    class _AbortFlow(Exception):
        def __init__(self, reason: str = "aborted") -> None:
            super().__init__(reason)
            self.reason = reason

    @dataclass(kw_only=True)
    class _SetupFlowContext:
        kind: str
        reason: str
        domain: str
        instance_id: str | None = None
        player_id: str | None = None
        setup_data: dict[str, Any] = field(default_factory=dict)
        values: dict[str, Any] = field(default_factory=dict)

    class _SetupSession:
        """Minimal coroutine-driven setup session used by provider unit tests."""

        def __init__(
            self,
            mass: Any,
            flow_id: str,
            context: _SetupFlowContext,
            finish_handler: Any,
        ) -> None:
            self.mass = mass
            self.flow_id = flow_id
            self.context = context
            self.current_step: Any = None
            self.finished = False
            self._finish_handler = finish_handler
            self._input_future: asyncio.Future[dict[str, Any]] | None = None

        async def form(
            self,
            entries: list[Any],
            *,
            step_id: str = "user",
            errors: dict[str, str] | None = None,
            **_kwargs: Any,
        ) -> dict[str, Any]:
            from music_assistant_models.enums import FlowStepType

            self.current_step = types.SimpleNamespace(
                type=FlowStepType.FORM,
                step_id=step_id,
                entries=entries,
                errors=errors or {},
            )
            self._input_future = asyncio.get_running_loop().create_future()
            return await self._input_future

        def handle_submit(self, values: dict[str, Any]) -> None:
            if self._input_future is None or self._input_future.done():
                raise RuntimeError("No setup form is awaiting input")
            self._input_future.set_result(values)

        async def progress_until(self, awaitable: Any, **_kwargs: Any) -> Any:
            return await awaitable

        async def finish(self, values: dict[str, Any]) -> None:
            await self._finish_handler(self, values)
            self.finished = True

    _ensure_stub(
        "music_assistant.models.setup_flow",
        {
            "AbortFlow": _AbortFlow,
            "SetupFlowError": _SetupFlowError,
            "SetupFlowContext": _SetupFlowContext,
            "SetupSession": _SetupSession,
            "StepExpiredError": _StepExpiredError,
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
