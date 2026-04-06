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
