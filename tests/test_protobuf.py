"""Tests for protobuf encoding/decoding."""

from __future__ import annotations

from provider.protobuf import dumps, loads


def test_roundtrip_simple() -> None:
    """Test that encoding and decoding a simple dict is identity."""
    data = {1: "radio_play", 2: '{"streamUrl": "http://example.com/stream.flac"}'}
    encoded = dumps(data)
    decoded = loads(encoded)
    assert decoded[1] == b"radio_play"
    assert b"streamUrl" in decoded[2]


def test_dumps_produces_bytes() -> None:
    """Test that dumps returns bytes."""
    result = dumps({1: "test"})
    assert isinstance(result, bytes)
    assert len(result) > 0
