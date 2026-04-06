"""Lightweight protobuf encoder/decoder for Yandex externalCommandBypass.

Adapted from AlexxIT/YandexStation (MIT license).
"""

from __future__ import annotations

import base64


class Protobuf:
    """Minimal protobuf wire-format parser."""

    def __init__(self, raw: str | bytes) -> None:
        self.raw = base64.b64decode(raw) if isinstance(raw, str) else raw
        self.pos = 0

    def read(self, length: int) -> bytes:
        self.pos += length
        return self.raw[self.pos - length : self.pos]

    def read_byte(self) -> int:
        res = self.raw[self.pos]
        self.pos += 1
        return res

    def read_varint(self) -> int:
        res = 0
        shift = 0
        while True:
            b = self.read_byte()
            res += (b & 0x7F) << shift
            if b & 0x80 == 0:
                break
            shift += 7
        return res

    def read_bytes(self) -> bytes:
        length = self.read_varint()
        return self.read(length)

    def read_dict(self) -> dict:
        res: dict = {}
        while self.pos < len(self.raw):
            b = self.read_varint()
            typ = b & 0b111
            tag = b >> 3

            if typ == 0:  # VARINT
                v: object = self.read_varint()
            elif typ == 1:  # I64
                v = self.read(8)
            elif typ == 2:  # LEN
                raw_bytes = self.read_bytes()
                try:
                    v = Protobuf(raw_bytes).read_dict()
                except Exception:
                    v = raw_bytes
            elif typ == 5:  # I32
                v = self.read(4)
            else:
                msg = f"Unsupported protobuf wire type: {typ}"
                raise NotImplementedError(msg)

            if tag in res:
                if isinstance(res[tag], list):
                    res[tag].append(v)
                else:
                    res[tag] = [res[tag], v]
            else:
                res[tag] = v

        return res


def _append_varint(b: bytearray, i: int) -> None:
    while i >= 0x80:
        b.append(0x80 | (i & 0x7F))
        i >>= 7
    b.append(i)


def loads(raw: str | bytes) -> dict:
    """Decode protobuf wire format to dict."""
    return Protobuf(raw).read_dict()


def dumps(data: dict[int, str]) -> bytes:
    """Encode dict to protobuf wire format (string values only)."""
    b = bytearray()
    for tag, value in data.items():
        if not isinstance(tag, int) or not isinstance(value, str):
            msg = f"Only int→str mappings supported, got {type(tag)}→{type(value)}"
            raise TypeError(msg)
        b.append(tag << 3 | 2)
        encoded = value.encode()
        _append_varint(b, len(encoded))
        b.extend(encoded)
    return bytes(b)
