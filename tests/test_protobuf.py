"""Tests for protobuf encoding/decoding."""

from __future__ import annotations

import importlib

_mod = None
for _name in (
    "music_assistant.providers.yandex_station.protobuf",
    "provider.protobuf",
):
    try:
        _mod = importlib.import_module(_name)
        break
    except ModuleNotFoundError:
        continue

assert _mod is not None, "Could not import protobuf module"
dumps = _mod.dumps
loads = _mod.loads


def test_roundtrip_simple() -> None:
    """Test that encoding and decoding a simple dict is identity."""
    data = {1: "radio_play", 2: '{"streamUrl": "http://example.com/stream.flac"}'}
    encoded = dumps(data)
    decoded = loads(encoded)
    assert decoded[1] == b"radio_play"
    assert b"streamUrl" in bytes(decoded[2])


def test_dumps_produces_bytes() -> None:
    """Test that dumps returns bytes."""
    result = dumps({1: "test"})
    assert isinstance(result, bytes)
    assert len(result) > 0
