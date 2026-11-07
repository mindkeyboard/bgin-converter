"""Bounded BGIN reader. Wire shapes are independent of runtime widget policy."""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import struct
from typing import Any

from .names import PROPERTY_NAMES, TYPE_NAMES

MAGIC = 0x000C1AAA
MOVIE = 0x6E739C13
SPRITE_MOVIE = 0xBE17FA7A
MOVIE_MODULE = 0xEB9A8C92
DIALECTS = ("auto", "ui", "templates", "sprites")
LEGACY_MARKER = b"\x08\x00Database"


def _name_hash(name):
    # Imported at call time because the editable layer also uses this wire reader.
    from .parser import jet_hash
    return jet_hash(name)


class BginError(ValueError):
    """A reproducible input error, addressed by absolute byte offset and JSON path."""

    def __init__(self, message: str, offset: int, path: str, code: str = "invalid_data"):
        self.message, self.offset, self.path, self.code = message, offset, path, code
        super().__init__(f"{code} at 0x{offset:X} ({path}): {message}")

    def to_dict(self) -> dict[str, Any]:
        return dict(code=self.code, message=self.message, offset=self.offset, path=self.path)


@dataclass(frozen=True)
class Limits:
    """Whole-document budgets; limits remain fatal in preservation mode."""

    max_bytes: int = 64 * 1024 * 1024
    max_depth: int = 128
    max_nodes: int = 200_000
    max_values: int = 2_000_000

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        # Keep parsing and standard-library JSON serialization below recursion limits.
        if self.max_depth > 128:
            raise ValueError("max_depth must not exceed 128")


def _hex(value: int) -> str:
    return f"0x{value:08X}"


def _span(start: int, end: int) -> dict[str, int]:
    return {"offset": start, "length": end - start}


class _Reader:
    def __init__(self, data: bytes, start: int, end: int, path: str):
        self.data, self.pos, self.end, self.path = data, start, end, path

    def fail(self, message: str, code: str = "invalid_data", offset: int | None = None):
        raise BginError(message, self.pos if offset is None else offset, self.path, code)

    def require(self, size: int) -> None:
        if size < 0 or size > self.end - self.pos:
            self.fail(f"Need {size} bytes, have {self.end - self.pos}", "truncated")

    def raw(self, size: int) -> bytes:
        self.require(size)
        start = self.pos
        self.pos += size
        return self.data[start:self.pos]

    def number(self, fmt: str):
        size = struct.calcsize("<" + fmt)
        self.require(size)
        result = struct.unpack_from("<" + fmt, self.data, self.pos)[0]
        self.pos += size
        if isinstance(result, float) and not math.isfinite(result):
            # JSON has no NaN/Infinity. Preserve the exact IEEE representation.
            return {"non_finite": "nan" if math.isnan(result) else
                    ("+infinity" if result > 0 else "-infinity"),
                    "ieee754_le_hex": self.data[self.pos-size:self.pos].hex()}
        return result

    def u8(self) -> int:
        return self.number("B")

    def u16(self) -> int:
        return self.number("H")

    def u32(self) -> int:
        return self.number("I")

    def text(self) -> str:
        start = self.pos
        raw = self.raw(self.u16())
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as error:
            self.fail(f"Invalid UTF-8: {error.reason}", "invalid_utf8", start)


class _Parser:
    def __init__(self, data: bytes, dialect: str, preserve_unknown: bool, limits: Limits):
        self.data, self.dialect = data, dialect
        self.preserve_unknown, self.limits = preserve_unknown, limits
        self.nodes = self.values = 0
        self.legacy = data[4:14] == LEGACY_MARKER
        self.diagnostics: list[dict[str, Any]] = []

    def budget(self, count: int, reader: _Reader) -> None:
        self.values += count
        if self.values > self.limits.max_values:
            reader.fail("Value budget exceeded", "limit_exceeded")

    def properties(self, r: _Reader, path: str) -> list[dict[str, Any]]:
        count = r.u16()
        self.budget(count, r)
        r.require(count * 8)
        return [self.property(r, f"{path}/{i}") for i in range(count)]

    def property(self, r: _Reader, path: str) -> dict[str, Any]:
        old_path, r.path = r.path, path
        start = r.pos
        literal_name = r.text() if self.legacy else None
        name_hash = _name_hash(literal_name) if self.legacy else r.u32()
        kind, count = (r.u32() if self.legacy else r.u16()), r.u16()
        self.budget(count, r)
        values: list[Any] = []
        encodings = {0: "empty", 2: "f64", 4: "enum", 8: "path",
                     0x80: "f32_vector", 0x400: "string"}
        if kind not in encodings:
            r.fail(f"Unknown property kind 0x{kind:04X}", "unknown_kind", start + 4)
        for _ in range(count if kind else 0):
            if kind == 2:
                value = r.number("d")
            elif kind == 4:
                code = r.number("i")
                enum_hash = None if self.legacy else r.u32()
                label = r.text()
                value = {"code": code, "name_hash": _hex(_name_hash(label) if self.legacy else enum_hash), "name": label}
                if self.legacy:
                    value["literal_name"] = label
            elif kind in (8, 0x400):
                value = r.text()
            else:
                components = r.u8()
                self.budget(components, r)
                value = [r.number("f") for _ in range(components)]
            values.append(value)
        result = dict(hash=_hex(name_hash), name=PROPERTY_NAMES.get(name_hash),
                      kind=f"0x{kind:04X}", encoding=encodings[kind], count=count,
                      values=values, span=_span(start, r.pos), raw_hex=self.data[start:r.pos].hex())
        if self.legacy:
            result["literal_name"] = literal_name
        r.path = old_path
        return result

    def node(self, parent: _Reader, path: str, depth: int) -> dict[str, Any]:
        if depth > self.limits.max_depth:
            raise BginError("Nesting depth exceeded", parent.pos, path, "limit_exceeded")
        self.nodes += 1
        if self.nodes > self.limits.max_nodes:
            raise BginError("Node budget exceeded", parent.pos, path, "limit_exceeded")
        start = parent.pos
        h = _Reader(self.data, start, parent.end, path)
        literal_type = h.text() if self.legacy else None
        type_hash = _name_hash(literal_type) if self.legacy else h.u32()
        size = h.u32()
        h.require(size)
        end = h.pos + size
        r = _Reader(self.data, h.pos, end, path)
        node: dict[str, Any] = dict(type_hash=_hex(type_hash), type_name=TYPE_NAMES.get(type_hash),
                                    span=_span(start, end), payload_size=size, decoded=True)
        if self.legacy:
            node["literal_type"] = literal_type
        diagnostic_start = len(self.diagnostics)
        try:
            node["name"] = r.text()
            if self.dialect == "sprites" and type_hash == MOVIE:
                node["sprite_movie"] = self.movie(r, path + "/sprite_movie", depth)
            else:
                node["metadata_hex"] = r.raw(20).hex()
                node["properties"] = self.properties(r, path + "/properties")
                count = r.u16()
                r.require(count * 8)
                node["children"] = [self.node(r, f"{path}/children/{i}", depth + 1)
                                    for i in range(count)]
            if r.pos != end:
                r.fail(f"{end - r.pos} unconsumed node bytes", "trailing_bytes")
        except BginError as error:
            if not self.preserve_unknown or error.code == "limit_exceeded":
                raise
            # Recover only at an independently framed record boundary; never scan for a sync byte.
            del self.diagnostics[diagnostic_start:]
            diagnostic = error.to_dict()
            diagnostic["preserved_at"] = path
            self.diagnostics.append(diagnostic)
            node = {key: node[key] for key in ("type_hash", "type_name", "span", "payload_size")}
            node.update(decoded=False, raw_hex=self.data[start:end].hex(), error=error.to_dict())
        parent.pos = end
        return node

    def movie(self, r: _Reader, path: str, depth: int) -> dict[str, Any]:
        start = r.pos
        count = r.u16()
        r.require(count * 8)
        sprites = [self.node(r, f"{path}/sprite_movies/{i}", depth + 1) for i in range(count)]
        if any(n["type_hash"] != _hex(SPRITE_MOVIE) for n in sprites):
            r.fail("Expected SpriteMovie records", "invalid_movie")
        a, b, c, flags = r.u32(), r.u32(), r.u32(), r.u8()
        track_count = r.u32()
        self.budget(track_count, r)
        r.require(track_count * 13)
        tracks = []
        for i in range(track_count):
            track_path = f"{path}/tracks/{i}"
            r.path = track_path
            track_start, marker = r.pos, r.u8()
            node = self.node(r, track_path + "/node", depth + 1)
            if node["type_hash"] != _hex(MOVIE_MODULE):
                r.fail("Expected MovieModule record", "invalid_movie")
            frames = []
            while True:
                frame_path = f"{track_path}/keyframes/{len(frames)}"
                r.path = frame_path
                frame_start, index = r.pos, r.u32()
                if index == 0xFFFFFFFF:
                    break
                self.budget(1, r)
                frames.append(self.keyframe(r, frame_start, index, frame_path))
            tracks.append(dict(marker=marker, node=node, keyframes=frames,
                               terminator="0xFFFFFFFF", span=_span(track_start, r.pos)))
        return dict(sprite_movies=sprites, header_a=a, header_b=b, header_c=c,
                    header_flags=flags, tracks=tracks, span=_span(start, r.pos))

    def keyframe(self, r: _Reader, start: int, index: int, path: str) -> dict[str, Any]:
        flags = r.u16()
        if flags & ~0x3F:
            r.fail(f"Unknown keyframe flags 0x{flags:04X}", "unknown_flags", start + 4)
        frame: dict[str, Any] = dict(frame_index=index, flags=f"0x{flags:04X}")
        for flag, key, count in ((1, "position", 2), (2, "rotation", 1), (4, "scale", 2)):
            if flags & flag:
                frame[key] = dict(interpolation=r.u8(), values=[r.number("f") for _ in range(count)])
        # The string pair precedes the event even though its bit has a larger value.
        if flags & 0x10:
            frame["string_pair"] = [r.text(), r.text()]
        if flags & 8:
            frame["event"] = dict(name=r.text(), value_a=r.u32(), value_b=r.u32(), flags=r.u8())
        if flags & 0x20:
            frame["color_properties"] = self.properties(r, path + "/color_properties")
        frame.update(span=_span(start, r.pos), raw_hex=self.data[start:r.pos].hex())
        return frame

    def document(self) -> dict[str, Any]:
        r = _Reader(self.data, 0, len(self.data), "/header")
        magic = r.u32()
        if magic != MAGIC:
            r.fail(f"Expected BGIN magic {_hex(MAGIC)}, got {_hex(magic)}", "bad_magic", 0)
        if self.legacy:
            if r.text() != "Database":
                r.fail("Unsupported legacy document marker", "invalid_header")
            name = r.text()
            automatic = self.dialect == "auto"
            if automatic:
                self.dialect = {"sprites": "sprites", "widgets": "templates"}.get(name.lower(), "ui")
            count = r.u16()
            if not count:
                r.fail("Empty screen directory is not supported", "invalid_directory")
            if automatic and _Reader(self.data, r.pos, r.end, "/header").text() == "Sprite":
                self.dialect = "sprites"
            screens = []
            for i in range(count):
                offset = r.pos
                root = self.node(r, f"/screens/{i}/root", 1)
                screens.append(dict(name_hash=_hex(_name_hash(root["name"])), offset=offset, root=root))
            if r.pos != r.end:
                r.fail("Unconsumed legacy document bytes", "trailing_bytes")
            return dict(format="legacy", dialect=self.dialect, header=dict(name=name),
                        complete=not self.diagnostics, diagnostics=self.diagnostics, screens=screens)
        file_hash, name = r.u32(), r.text()
        automatic = self.dialect == "auto"
        if automatic:
            self.dialect = {"sprites": "sprites", "widgets": "templates"}.get(name.lower(), "ui")
        count = r.u16()
        if not count:
            r.fail("Empty screen directory is not supported", "invalid_directory")
        r.require(count * 8 + 2)
        entries = [(r.u32(), r.u32()) for _ in range(count)]
        repeated = r.u16()
        if repeated != count:
            r.fail(f"Directory counts differ: {count} and {repeated}", "invalid_directory", r.pos - 2)
        first = entries[0][1]
        if first < r.pos or first > len(self.data):
            r.fail("First root overlaps the directory or exceeds the file", "invalid_directory")
        if automatic and first+4 <= len(self.data):
            # A user-defined resource namespace need not be literally named "sprites".
            root_type = struct.unpack_from('<I',self.data,first)[0]
            if TYPE_NAMES.get(root_type)=='Sprite':
                self.dialect = 'sprites'
        extra = r.raw(first - r.pos)
        screens = []
        for i, (name_hash, offset) in enumerate(entries):
            path = f"/screens/{i}/root"
            end = entries[i + 1][1] if i + 1 < count else len(self.data)
            if not first <= offset < end <= len(self.data):
                raise BginError("Unordered or invalid root offsets", offset, path, "invalid_directory")
            root_reader = _Reader(self.data, offset, end, path)
            root = self.node(root_reader, path, 1)
            if root_reader.pos != end:
                root_reader.fail("Root does not fill its directory range", "invalid_directory")
            screens.append(dict(name_hash=_hex(name_hash), offset=offset, root=root))
        return dict(format="octane.bgin-json", version=1, dialect=self.dialect,
                    header=dict(magic=_hex(magic), file_hash=_hex(file_hash), name=name,
                                screen_count=count, directory_count=repeated,
                                directory_extra_hex=extra.hex(), span=_span(0, first)),
                    complete=not self.diagnostics, diagnostics=self.diagnostics, screens=screens)


def parse(data: bytes, *, dialect: str = "auto", preserve_unknown: bool = False,
          limits: Limits | None = None) -> dict[str, Any]:
    """Parse bytes into the versioned JSON model. Strict parsing is the default."""
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    if dialect not in DIALECTS:
        raise ValueError(f"dialect must be one of {DIALECTS}")
    limits = limits or Limits()
    if len(data) > limits.max_bytes:
        raise BginError("File size budget exceeded", 0, "/", "limit_exceeded")
    return _Parser(data, dialect, preserve_unknown, limits).document()


def load(path: str | Path, *, dialect: str = "auto", preserve_unknown: bool = False,
         limits: Limits | None = None) -> dict[str, Any]:
    """Read at most max_bytes + 1 bytes, including when the file grows during reading."""
    limits = limits or Limits()
    with Path(path).open("rb") as stream:
        data = stream.read(limits.max_bytes + 1)
    return parse(data, dialect=dialect, preserve_unknown=preserve_unknown, limits=limits)
