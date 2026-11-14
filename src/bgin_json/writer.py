"""Compile edited data, regenerating record sizes and screen directory entries."""
from __future__ import annotations

import math
import struct

from . import _wire
from .parser import FILE_SIGNATURE, IDENTITY, MOVIE_SETTINGS, BginError, Limits, jet_hash
from .engine_params import LEGACY_NAMES
from .names import TYPE_NAMES
from .vocabulary import PROPERTY_KINDS, PROPERTY_NAMES, ENUMS
from .profiles import FORMATS, normalize_format, hash_reference, identifier

NAMES = {**LEGACY_NAMES, **{name: h for h, name in PROPERTY_NAMES.items()}}
TYPES = {name: h for h, name in TYPE_NAMES.items()}
KINDS = {"empty": 0, "number": 2, "enum": 4, "path": 8, "vector": 128, "string": 1024}


def error(message, path):
    raise BginError(message, 0, path, "invalid_json")


def object_keys(value, allowed, path):
    if not isinstance(value, dict):
        error("Expected an object", path)
    unexpected = value.keys() - set(allowed)
    if unexpected:
        error("Unknown fields: " + ", ".join(sorted(unexpected)), path)


def integer(value, maximum, path, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        error(f"Expected an integer from {minimum} to {maximum}", path)
    return value


def array(value, path):
    if not isinstance(value, list):
        error("Expected an array", path)
    return value


def text(value, path):
    if not isinstance(value, str):
        error("Expected a string", path)
    try:
        raw = value.encode("utf-8")
    except UnicodeEncodeError:
        error("Invalid Unicode string", path)
    if len(raw) > 65535:
        error("UTF-8 string exceeds 65535 bytes", path)
    return struct.pack("<H", len(raw)) + raw


def floating(value, fmt, path):
    if type(value) not in (int, float):
        error("Expected a finite number", path)
    try:
        if not math.isfinite(value):
            error("Expected a finite number", path)
        return struct.pack("<" + fmt, value)
    except (OverflowError, struct.error):
        error("Number is outside the binary representation", path)


class _Writer:
    def __init__(self, dialect, limits, profile="a8-1.6.0"):
        self.dialect, self.limits = dialect, limits
        self.profile = profile
        self.legacy = profile == "a8-0.0.2"
        self.modern = profile == "a8-5.8.0"
        self.nodes = self.values = 0
        self.output_size = 0

    def reserve(self, size, path):
        self.output_size += size
        if self.output_size > self.limits.max_bytes:
            raise BginError("Output size budget exceeded", 0, path, "limit_exceeded")

    def budget(self, count, path):
        self.values += count
        if self.values > self.limits.max_values:
            raise BginError("Value budget exceeded", 0, path, "limit_exceeded")

    def counted(self, items, path):
        return struct.pack("<H", integer(len(items), 65535, path))

    def properties(self, source, path):
        if isinstance(source, list):
            pairs = []
            for i, item in enumerate(source):
                if not isinstance(item, dict) or len(item) != 1:
                    error("Repeated properties use one-name objects", f"{path}/{i}")
                pairs.extend(item.items())
        elif isinstance(source, dict):
            pairs = list(source.items())
        else:
            error("Expected a property object or list", path)
        self.budget(len(pairs), path)
        return self.counted(pairs, path) + b"".join(self.property(k, v, path + "/" + str(k)) for k, v in pairs)

    def token(self, name, token, path):
        if self.legacy:
            object_keys(token, ("enum", "value"), path)
            label = token.get("enum")
            if hash_reference(label) is not None:
                error("The ~0.0.2 format requires the actual enum spelling", path)
            default = ENUMS.get(name, {}).get(label)
            if "value" not in token and default is None:
                error("Unregistered legacy enum choice requires an explicit value", path)
            code = integer(token.get("value", default[0] if default else 0), 2147483647, path, -2147483648)
            return struct.pack("<i", code) + text(label, path)
        object_keys(token, ("enum", "value", "text"), path)
        label = token.get("enum")
        if not isinstance(label, str):
            error("Expected an enum name", path)
        reference = hash_reference(label)
        if label not in NAMES and reference is None and token.get("text") != label:
            error("Unknown enum name needs matching text", path)
        if label not in ENUMS.get(name, {}) and "value" not in token:
            error("Unregistered enum choice requires an explicit value", path)
        default = ENUMS.get(name, {}).get(label, (0, identifier(label, NAMES, jet_hash), ""))
        code = integer(token.get("value", default[0]), 2147483647, path, -2147483648)
        return struct.pack("<iI", code, default[1]) + text(token.get("text", default[2]), path)

    def property(self, name, value, path, *, count_output=True):
        if not isinstance(name, str) or not self.legacy and name not in NAMES and hash_reference(name) is None:
            error("Property name is absent from the supported vocabulary", path)
        variants = []
        if isinstance(value, dict) and "variants" in value:
            object_keys(value, ("value", "variants"), path)
            if not self.modern:
                error("Property variants require the ~5.8.0 format", path + "/variants")
            variants = array(value["variants"], path + "/variants")
            value = value.get("value")
        kind = PROPERTY_KINDS.get(name)
        if name in ("MinSize", "MaxSize"):
            kind = "vector" if isinstance(value, list) else "number"
        multiple_vectors = multiple_enums = False
        if value is None:
            kind, value = "empty", 0
        elif isinstance(value, dict):
            if "enum" in value:
                kind = "enum"
            elif len(value) == 1 and next(iter(value)) in (*KINDS, "vectors", "enums"):
                tag, value = next(iter(value.items()))
                multiple_vectors, multiple_enums = tag == "vectors", tag == "enums"
                kind = {"vectors": "vector", "enums": "enum"}.get(tag, tag)
            else:
                error("Expected a named enum or explicit value type", path)
        if kind is None:
            kind = "string" if isinstance(value, str) else "vector" if isinstance(value, list) else "number"
        if kind == "empty":
            count, payload = integer(value, 65535, path), b""
        else:
            if kind == "vector":
                values = array(value, path) if multiple_vectors else [array(value, path)]
            elif kind == "enum":
                values = array(value, path) if multiple_enums else [value]
            else:
                values = value if isinstance(value, list) else [value]
            self.budget(len(values), path)
            count = integer(len(values), 65535, path)
            chunks = []
            chunk_size = 0
            for item in values:
                if kind == "number":
                    chunks.append(floating(item, "d", path))
                elif kind in ("string", "path"):
                    chunks.append(text(item, path))
                elif kind == "enum":
                    chunks.append(self.token(name, item, path))
                else:
                    components = array(item, path)
                    self.budget(len(components), path)
                    chunks.append(bytes([integer(len(components), 255, path)]) +
                                  b"".join(floating(v, "f", path) for v in components))
                chunk_size += len(chunks[-1])
                if chunk_size > self.limits.max_bytes:
                    raise BginError("Property size budget exceeded", 0, path, "limit_exceeded")
            payload = b"".join(chunks)
        if self.legacy and hash_reference(name) is not None:
            error("The ~0.0.2 format requires the actual property spelling", path)
        header = (text(name, path) + struct.pack("<IH", KINDS[kind], count) if self.legacy else
                  struct.pack("<IHB" if self.modern else "<IHH", identifier(name, NAMES, jet_hash), KINDS[kind],
                              integer(count, 255 if self.modern else 65535, path)))
        if self.modern:
            suffix = bytes([integer(len(variants), 255, path + "/variants")])
            for i, variant in enumerate(variants):
                vp = f"{path}/variants/{i}"
                object_keys(variant, ("key", "value"), vp)
                if isinstance(variant.get("value"), dict) and "variants" in variant["value"]:
                    error("Property variants cannot contain nested variants", vp + "/value")
                key = variant.get("key")
                if not isinstance(key, str):
                    error("Variant key must be a name or #XXXXXXXX identifier", vp + "/key")
                # Reuse the typed encoder, but retain only count and value bytes;
                # each alternative inherits the original property's wire kind.
                compiled = self.property(name, variant.get("value"), vp + "/value", count_output=False)
                if struct.unpack_from("<H", compiled, 4)[0] != KINDS[kind]:
                    error("Variant value kind differs from its property", vp + "/value")
                suffix += struct.pack("<I", identifier(key, NAMES, jet_hash)) + compiled[6:-1]
            payload += suffix
        if count_output:
            self.reserve(len(header) + len(payload), path)
        return header + payload

    def frame(self, source, path):
        object_keys(source, ("frame", "position", "rotation", "scale", "strings", "event", "colors", "color_channels"), path)
        index = integer(source.get("frame"), 0xFFFFFFFE, path + "/frame")
        flags, payload = 0, b""
        for flag, channel, count in ((1, "position", 2), (2, "rotation", 1), (4, "scale", 2)):
            if channel in source:
                flags |= flag
                item = source[channel]
                object_keys(item, ("value", "interpolation"), path + "/" + channel)
                values = [item.get("value")] if count == 1 else array(item.get("value"), path)
                if len(values) != count:
                    error(f"{channel} needs {count} values", path)
                payload += bytes([integer(item.get("interpolation", 0), 255, path)])
                payload += b"".join(floating(v, "f", path) for v in values)
        if "strings" in source:
            flags |= 0x10
            values = array(source["strings"], path)
            if len(values) != 2:
                error("strings needs two strings", path)
            payload += b"".join(text(v, path) for v in values)
        if "event" in source:
            flags |= 8
            item = source["event"]
            object_keys(item, ("name", "arguments"), path)
            values = array(item.get("arguments"), path)
            if len(values) != 3:
                error("event needs three arguments", path)
            payload += text(item.get("name"), path)
            payload += struct.pack("<IIB", *(integer(v, m, path) for v, m in zip(values, (0xFFFFFFFF, 0xFFFFFFFF, 255))))
        colors_size = 0
        if "colors" in source:
            if self.modern:
                error("The ~5.8.0 format uses color_channels, not old color properties", path + "/colors")
            flags |= 0x20
            colors = self.properties(source["colors"], path + "/colors")
            colors_size = len(colors) - 2
            payload += colors
        if "color_channels" in source:
            if not self.modern:
                error("Color channels require the ~5.8.0 format", path + "/color_channels")
            flags |= 0x20
            channels = array(source["color_channels"], path + "/color_channels")
            payload += self.counted(channels, path)
            for i, item in enumerate(channels):
                cp = f"{path}/color_channels/{i}"
                object_keys(item, ("key", "interpolation", "value"), cp)
                key = item.get("key")
                if not isinstance(key, str):
                    error("Channel key must be a name or #XXXXXXXX identifier", cp + "/key")
                values = array(item.get("value"), cp + "/value")
                self.budget(len(values), cp)
                payload += struct.pack("<IBB", identifier(key, NAMES, jet_hash),
                                       integer(item.get("interpolation", 0), 255, cp),
                                       integer(len(values), 255, cp))
                payload += b"".join(floating(v, "f", cp) for v in values)
        self.budget(1, path)
        self.reserve(6 + len(payload) - colors_size, path)
        return struct.pack("<IH", index, flags) + payload

    def node(self, source, path, depth=1, track=False):
        if depth > self.limits.max_depth:
            raise BginError("Nesting depth exceeded", 0, path, "limit_exceeded")
        self.nodes += 1
        if self.nodes > self.limits.max_nodes:
            raise BginError("Node budget exceeded", 0, path, "limit_exceeded")
        fields = ("type", "name", "transform", "properties", "children", "tracks", "settings")
        object_keys(source, fields + (("marker", "keyframes") if track else ()), path)
        type_name = source.get("type")
        if not isinstance(type_name, str) or not self.legacy and type_name not in TYPES and hash_reference(type_name) is None:
            error("Unknown node type", path + "/type")
        if self.legacy and hash_reference(type_name) is not None:
            error("The ~0.0.2 format requires the actual type spelling", path + "/type")
        payload = text(source.get("name"), path + "/name")
        self.reserve((len(text(type_name, path)) + 4 if self.legacy else 8) + len(payload), path)
        children = array(source.get("children", []), path + "/children")
        if self.dialect == "sprites" and type_name == "Movie":
            self.reserve(19, path)
            if "properties" in source or "transform" in source:
                error("Sprite Movie cannot have ordinary properties or transform", path)
            if any(not isinstance(c, dict) or c.get("type") != "SpriteMovie" for c in children):
                error("Sprite Movie children must be SpriteMovie", path)
            payload += self.counted(children, path)
            payload += b"".join(self.node(c, f"{path}/children/{i}", depth + 1) for i, c in enumerate(children))
            settings = array(source.get("settings", MOVIE_SETTINGS), path + "/settings")
            if len(settings) != 4:
                error("settings needs four integers", path)
            payload += struct.pack("<IIIB", *(integer(v, m, path) for v, m in zip(settings, (0xFFFFFFFF,)*3 + (255,))))
            tracks = array(source.get("tracks", []), path + "/tracks")
            self.budget(len(tracks), path)
            payload += struct.pack("<I", integer(len(tracks), 0xFFFFFFFF, path))
            for i, item in enumerate(tracks):
                self.reserve(5, path)
                tp = f"{path}/tracks/{i}"
                if not isinstance(item, dict) or item.get("type") != "MovieModule":
                    error("Track type must be MovieModule", tp)
                payload += bytes([integer(item.get("marker", 0x65), 255, tp)])
                payload += self.node(item, tp, depth + 1, track=True)
                frames = array(item.get("keyframes", []), tp + "/keyframes")
                payload += b"".join(self.frame(f, f"{tp}/keyframes/{j}") for j, f in enumerate(frames))
                payload += struct.pack("<I", 0xFFFFFFFF)
        else:
            self.reserve(4 if self.modern else 24, path)
            if "tracks" in source or "settings" in source:
                error("Only a sprite Movie has tracks or settings", path)
            if "transform" in source:
                values = array(source["transform"], path + "/transform")
                if len(values) != 5:
                    error("transform needs five numbers", path)
                encoded_transform = b"".join(floating(v, "f", path) for v in values)
                if self.modern:
                    if encoded_transform != IDENTITY:
                        error("Nonidentity transform cannot be represented in ~5.8.0", path + "/transform")
                else:
                    payload += encoded_transform
            elif not self.modern:
                payload += IDENTITY
            payload += self.properties(source.get("properties", {}), path + "/properties")
            payload += self.counted(children, path)
            payload += b"".join(self.node(c, f"{path}/children/{i}", depth + 1) for i, c in enumerate(children))
        if len(payload) > self.limits.max_bytes:
            raise BginError("Output size budget exceeded", 0, path, "limit_exceeded")
        header = text(type_name, path) + struct.pack("<I", len(payload)) if self.legacy else struct.pack("<II", identifier(type_name, TYPES, jet_hash), len(payload))
        return header + payload


def encode(document: dict, *, limits: Limits | None = None) -> bytes:
    """Compile without an original BGIN, sidecar, or workspace dependency."""
    limits = limits or Limits()
    object_keys(document, ("name", "dialect", "screens", "format"), "/")
    try:
        profile = normalize_format(document.get("format"))
    except ValueError as exc:
        error(str(exc), "/format")
    legacy = profile == "a8-0.0.2"
    extended = profile in ("a8-3.7.0", "a8-5.8.0")
    if "name" not in document and document.get("screens") == []:
        if "format" in document:
            error("An unnamed empty draft has no binary format yet", "/format")
        if document.get("dialect", "ui") != "ui":
            error("An unnamed empty draft must use the ui dialect", "/dialect")
        return b""
    name = document.get("name")
    name_bytes = text(name, "/name")
    if not name.strip():
        error("Document name must not be blank", "/name")
    dialect = document.get("dialect", {"sprites": "sprites", "widgets": "templates"}.get(name.lower(), "ui"))
    if dialect not in ("ui", "templates", "sprites"):
        error("Unknown dialect", "/dialect")
    screens = array(document.get("screens"), "/screens")
    if not screens:
        error("At least one screen is required", "/screens")
    integer(len(screens), 65535, "/screens")
    writer = _Writer(dialect, limits, profile)
    writer.reserve(4 + len(_wire.LEGACY_MARKER) + len(name_bytes) + 2 if legacy else 8 + len(name_bytes) + (10 if extended else 4) + 8 * len(screens), "/")
    blobs = [writer.node(s, f"/screens/{i}") for i, s in enumerate(screens)]
    prefix = struct.pack("<II", _wire.MAGIC, FILE_SIGNATURE) + name_bytes
    prefix += (struct.pack("<I", 4 + 8 * len(screens)) if extended else b"") + struct.pack("<H", len(screens))
    offset = len(prefix) + 8 * len(screens) + (4 if extended else 2)
    directory = bytearray()
    for screen, blob in zip(screens, blobs):
        directory += struct.pack("<II", jet_hash(screen["name"]), offset)
        offset += len(blob)
    result = struct.pack("<I", _wire.MAGIC) + _wire.LEGACY_MARKER + name_bytes + struct.pack("<H", len(screens)) + b"".join(blobs) if legacy else prefix + directory + (b"\x00\x00" if extended else b"") + struct.pack("<H", len(screens)) + b"".join(blobs)
    if len(result) > limits.max_bytes:
        raise BginError("Output size budget exceeded", 0, "/", "limit_exceeded")
    _wire.parse(bytes(result), dialect=dialect, limits=limits, format=profile)
    return bytes(result)


def convert_document(document: dict, target_format: str, *, limits: Limits | None = None) -> dict:
    """Return a separately owned document after lossless target checks.

    Conversion never rewrites the source object. Unknown identifiers cannot be
    certified for an earlier engine, and variant/channel semantics are not guessed.
    """
    import copy
    # Validate the source before converting; a target must not make an invalid
    # source document appear valid by replacing its format field.
    encode(document, limits=limits)
    target = normalize_format(target_format)
    source = normalize_format(document.get("format"))
    result = copy.deepcopy(document)
    if "name" not in result and result.get("screens") == []:
        error("Choose a name and first screen before converting formats", "/screens")
    def check(node, path):
        if FORMATS.index(target) < FORMATS.index(source):
            if hash_reference(node.get("type")) is not None:
                error("Unknown type is not verified for the target engine", path + "/type")
            props = node.get("properties", {})
            pairs = props.items() if isinstance(props, dict) else ((k,v) for item in props for k,v in item.items())
            for key, value in pairs:
                if hash_reference(key) is not None:
                    error("Unknown property is not verified for the target engine", path + "/properties/" + key)
        for name in ("children", "tracks"):
            for i, child in enumerate(node.get(name, [])):
                check(child, f"{path}/{name}/{i}")
    for i, node in enumerate(result.get("screens", [])):
        check(node, f"/screens/{i}")
    result["format"] = target
    encode(result, limits=limits)
    return result
