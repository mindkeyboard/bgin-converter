"""Editable BGIN documents; binary bookkeeping stays inside the codec."""
from __future__ import annotations

import math
from pathlib import Path
import struct

from . import _wire
from ._wire import BginError, Limits
from .names import TYPE_NAMES
from .vocabulary import ENUMS, PROPERTY_KINDS, PROPERTY_NAMES

FILE_SIGNATURE = 0x9456A530
IDENTITY = struct.pack("<5f", 0, 0, 0, 1, 1)
MOVIE_SETTINGS = [30, 0, 3333, 0]
KIND_NAMES = {0: "empty", 2: "number", 4: "enum", 8: "path", 128: "vector", 1024: "string"}


def jet_hash(value: str) -> int:
    data = bytes(b | 0x20 for b in value.encode("utf-8"))
    result = 0xFF4F5 ^ len(data)
    index = 0
    while len(data) - index >= 4:
        chunk = int.from_bytes(data[index:index+4], "little")
        chunk = chunk * 0x5BD1E995 & 0xFFFFFFFF
        chunk ^= chunk >> 24
        chunk = chunk * 0x5BD1E995 & 0xFFFFFFFF
        result = (result * 0x5BD1E995 ^ chunk) & 0xFFFFFFFF
        index += 4
    tail = data[index:]
    if len(tail) == 3:
        result ^= tail[2] << 16
    if len(tail) >= 2:
        result ^= tail[1] << 8
    if tail:
        result ^= tail[0]
        result = result * 0x5BD1E995 & 0xFFFFFFFF
    result ^= result >> 13
    result = result * 0x5BD1E995 & 0xFFFFFFFF
    return (result ^ result >> 15) & 0xFFFFFFFF


def fail(message, path="/", offset=0):
    raise BginError(message, offset, path, "unsupported")


def _plain(value, path):
    if isinstance(value, dict):
        fail("Non-finite numbers cannot be represented in editable JSON", path)
    return [_plain(v, path) for v in value] if isinstance(value, list) else value


def _property(p, path):
    name = p.get("literal_name", PROPERTY_NAMES.get(int(p["hash"], 16)))
    if name is None:
        fail("Property spelling is absent from the vocabulary", path, p["span"]["offset"])
    kind, values = int(p["kind"], 16), p["values"]
    if kind == 4:
        converted = []
        for token in values:
            if "literal_name" in token:
                converted.append({"enum": token["literal_name"], "value": token["code"]})
                continue
            h = int(token["name_hash"], 16)
            label = PROPERTY_NAMES.get(h) or token["name"]
            if not label or h not in PROPERTY_NAMES and jet_hash(label) != h:
                fail("Enum spelling is absent from the vocabulary", path)
            value = {"enum": label}
            registered = ENUMS.get(name, {}).get(label)
            default = registered or (0, h, "")
            if registered is None or token["code"] != default[0]:
                value["value"] = token["code"]
            if token["name"] != default[2]:
                value["text"] = token["name"]
            converted.append(value)
        value = converted[0] if len(converted) == 1 else {"enums": converted}
    elif kind == 0:
        value = None if p["count"] == 0 else {"empty": p["count"]}
    else:
        values = _plain(values, path)
        value = values[0] if len(values) == 1 else values
        inferred = PROPERTY_KINDS.get(name)
        if name in ("MinSize", "MaxSize"):
            inferred = "vector" if isinstance(value, list) and values else "number"
        if inferred is None:
            inferred = "string" if isinstance(value, str) else "vector" if isinstance(value, list) else "number"
        if kind == 128 and len(values) != 1:
            value = {"vectors": values}
        elif KIND_NAMES[kind] != inferred:
            value = {KIND_NAMES[kind]: value}
    return name, value


def _properties(items, path):
    pairs = [_property(p, f"{path}/{i}") for i, p in enumerate(items)]
    return dict(pairs) if len({n for n, _ in pairs}) == len(pairs) else [{n: v} for n, v in pairs]


def _frame(f, path):
    out = {"frame": f["frame_index"]}
    for channel in ("position", "rotation", "scale"):
        if channel in f:
            source = f[channel]
            values = _plain(source["values"], path)
            out[channel] = {"value": values[0] if channel == "rotation" else values,
                            "interpolation": source["interpolation"]}
    if "string_pair" in f:
        out["strings"] = f["string_pair"]
    if "event" in f:
        e = f["event"]
        out["event"] = {"name": e["name"], "arguments": [e["value_a"], e["value_b"], e["flags"]]}
    if "color_properties" in f:
        out["colors"] = _properties(f["color_properties"], path + "/colors")
    return out


def _node(n, path):
    type_name = n.get("literal_type", TYPE_NAMES.get(int(n["type_hash"], 16)))
    if type_name is None or not n["decoded"]:
        fail("Node type is not supported by the editable format", path, n["span"]["offset"])
    out = {"type": type_name, "name": n["name"]}
    if "sprite_movie" in n:
        m = n["sprite_movie"]
        settings = [m[k] for k in ("header_a", "header_b", "header_c", "header_flags")]
        if settings != MOVIE_SETTINGS:
            out["settings"] = settings
        if m["sprite_movies"]:
            out["children"] = [_node(c, f"{path}/children/{i}") for i, c in enumerate(m["sprite_movies"])]
        tracks = []
        for i, track in enumerate(m["tracks"]):
            tp = f"{path}/tracks/{i}"
            item = _node(track["node"], tp)
            if track["marker"] != 0x65:
                item["marker"] = track["marker"]
            item["keyframes"] = [_frame(f, tp + "/keyframes") for f in track["keyframes"]]
            tracks.append(item)
        if tracks:
            out["tracks"] = tracks
    else:
        raw = bytes.fromhex(n["metadata_hex"])
        if raw != IDENTITY:
            transform = list(struct.unpack("<5f", raw))
            if not all(math.isfinite(v) for v in transform):
                fail("Non-finite transform cannot be represented in editable JSON", path)
            out["transform"] = transform
        if n["properties"]:
            out["properties"] = _properties(n["properties"], path + "/properties")
        if n["children"]:
            out["children"] = [_node(c, f"{path}/children/{i}") for i, c in enumerate(n["children"])]
    return out


def parse(data: bytes, *, dialect="auto", limits: Limits | None = None):
    """Decode to clean JSON without a source file or companion state."""
    if isinstance(data, bytes) and not data:
        if dialect not in _wire.DIALECTS:
            raise ValueError(f"dialect must be one of {_wire.DIALECTS}")
        from .drafts import empty_draft
        return empty_draft()
    wire = _wire.parse(data, dialect=dialect, limits=limits)
    header = wire["header"]
    legacy = wire.get("format") == "legacy"
    if not legacy and (int(header["file_hash"], 16) != FILE_SIGNATURE or header["directory_extra_hex"]):
        fail("Unsupported BGIN header variant")
    out = {"name": header["name"]}
    if legacy:
        out["format"] = "legacy"
    auto = {"sprites": "sprites", "widgets": "templates"}.get(header["name"].lower(), "ui")
    if wire["dialect"] != auto:
        out["dialect"] = wire["dialect"]
    screens = []
    for i, screen in enumerate(wire["screens"]):
        root = screen["root"]
        if int(screen["name_hash"], 16) != jet_hash(root["name"]):
            fail("Directory name does not match its root name", f"/screens/{i}")
        screens.append(_node(root, f"/screens/{i}"))
    out["screens"] = screens
    return out


def load(path: str | Path, *, dialect="auto", limits: Limits | None = None):
    limits = limits or Limits()
    with Path(path).open("rb") as stream:
        data = stream.read(limits.max_bytes + 1)
    return parse(data, dialect=dialect, limits=limits)
