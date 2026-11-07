"""
Shared binary Reader/Writer for BGIN byte-level operations.

Replaces ad-hoc struct.unpack_from / struct.pack calls in format.py
and codec.py with reusable, bounds-checked primitives.
"""

from __future__ import annotations

import struct
from typing import IO


class BginError(ValueError):
    """Raised when BGIN binary data cannot be parsed safely."""


class ByteReader:
    """Little-endian binary reader with bounds checking."""

    __slots__ = ("data", "pos", "limit")

    def __init__(self, data: bytes, offset: int = 0, limit: int | None = None) -> None:
        self.data = data
        self.pos = offset
        self.limit = len(data) if limit is None else limit

    def require(self, size: int) -> None:
        if size < 0 or self.pos + size > self.limit:
            raise BginError(
                f"Unexpected end of data at 0x{self.pos:x} (needs {size} bytes, "
                f"have {self.limit - self.pos})"
            )

    # -- Unsigned integers --

    def u8(self) -> int:
        self.require(1)
        value = self.data[self.pos]
        self.pos += 1
        return value

    def u16(self) -> int:
        self.require(2)
        value = struct.unpack_from("<H", self.data, self.pos)[0]
        self.pos += 2
        return value

    def u32(self) -> int:
        self.require(4)
        value = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return value

    def u64(self) -> int:
        self.require(8)
        value = struct.unpack_from("<Q", self.data, self.pos)[0]
        self.pos += 8
        return value

    # -- Signed integers --

    def s8(self) -> int:
        self.require(1)
        value = struct.unpack_from("<b", self.data, self.pos)[0]
        self.pos += 1
        return value

    def s16(self) -> int:
        self.require(2)
        value = struct.unpack_from("<h", self.data, self.pos)[0]
        self.pos += 2
        return value

    def s32(self) -> int:
        self.require(4)
        value = struct.unpack_from("<i", self.data, self.pos)[0]
        self.pos += 4
        return value

    # -- Floats --

    def f32(self) -> float:
        self.require(4)
        value = struct.unpack_from("<f", self.data, self.pos)[0]
        self.pos += 4
        return value

    def f64(self) -> float:
        self.require(8)
        value = struct.unpack_from("<d", self.data, self.pos)[0]
        self.pos += 8
        return value

    # -- Bytes & strings --

    def bytes(self, size: int) -> bytes:
        self.require(size)
        value = self.data[self.pos:self.pos + size]
        self.pos += size
        return value

    def skip(self, size: int) -> None:
        self.require(size)
        self.pos += size

    def peek(self, size: int) -> bytes:
        self.require(size)
        return self.data[self.pos:self.pos + size]

    def text(self) -> str:
        """Read a BGIN string: u16 length prefix + UTF-8 data."""
        size = self.u16()
        raw = self.bytes(size)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise BginError(
                f"Invalid UTF-8 string at 0x{self.pos - 2 - size:x}"
            ) from error

    def remaining(self) -> int:
        return self.limit - self.pos

    def eof(self) -> bool:
        return self.pos >= self.limit


class ByteWriter:
    """Little-endian binary writer. Accumulates bytes incrementally."""

    def __init__(self) -> None:
        self._buf = bytearray()

    # -- Unsigned integers --

    def u8(self, value: int) -> ByteWriter:
        self._validate_u(value, 1)
        self._buf.append(value & 0xFF)
        return self

    def u16(self, value: int) -> ByteWriter:
        self._validate_u(value, 2)
        self._buf += struct.pack("<H", value)
        return self

    def u32(self, value: int) -> ByteWriter:
        self._validate_u(value, 4)
        self._buf += struct.pack("<I", value)
        return self

    def u64(self, value: int) -> ByteWriter:
        self._validate_u(value, 8)
        self._buf += struct.pack("<Q", value)
        return self

    # -- Signed integers --

    def s8(self, value: int) -> ByteWriter:
        self._validate_s(value, 1)
        self._buf += struct.pack("<b", value)
        return self

    def s16(self, value: int) -> ByteWriter:
        self._validate_s(value, 2)
        self._buf += struct.pack("<h", value)
        return self

    def s32(self, value: int) -> ByteWriter:
        self._validate_s(value, 4)
        self._buf += struct.pack("<i", value)
        return self

    # -- Floats --

    def f32(self, value: float) -> ByteWriter:
        self._buf += struct.pack("<f", value)
        return self

    def f64(self, value: float) -> ByteWriter:
        self._buf += struct.pack("<d", value)
        return self

    # -- Bytes & strings --

    def bytes(self, data: bytes) -> ByteWriter:
        self._buf += data
        return self

    def text(self, value: str) -> ByteWriter:
        """Write a BGIN string: u16 length prefix + UTF-8 data."""
        raw = value.encode("utf-8")
        self.u16(len(raw))
        self._buf += raw
        return self

    def build(self) -> bytes:
        return bytes(self._buf)

    def __len__(self) -> int:
        return len(self._buf)

    # -- Validation helpers --

    @staticmethod
    def _validate_u(value: int, bytes_: int) -> None:
        max_val = (1 << (bytes_ * 8)) - 1
        if not 0 <= value <= max_val:
            raise BginError(
                f"Unsigned value {value} does not fit in {bytes_} byte(s)"
            )

    @staticmethod
    def _validate_s(value: int, bytes_: int) -> None:
        bits = bytes_ * 8
        min_val = -(1 << (bits - 1))
        max_val = (1 << (bits - 1)) - 1
        if not min_val <= value <= max_val:
            raise BginError(
                f"Signed value {value} does not fit in {bytes_} byte(s)"
            )
