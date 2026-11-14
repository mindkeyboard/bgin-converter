"""Independent codecs for the two-table BGIN profiles.

These routines reconstruct records from fields. They deliberately do not import
the editable codec, so verification can detect mistakes in either implementation.
"""
from __future__ import annotations

from .model import (BginDialect, BginDocument, BginError, BginNode,
                    BginProperty, BginScreen, EnumToken, PropertyVariant,
                    SourceSpan, SpriteColorChannel, SpriteKeyframe,
                    SpriteMoviePayload, SpriteMovieTrack)
from .reader import ByteReader, ByteWriter, BginError as ReaderError

PROFILES = ("a8-0.0.2", "a8-1.6.0", "a8-3.7.0", "a8-5.8.0")
ALIASES = {"legacy": PROFILES[0], "hashed": PROFILES[1]}
ENCODINGS = {0: "empty", 2: "f64", 4: "enum_token", 8: "path",
             128: "f32_vector", 1024: "string"}
MOVIE = 0x6E739C13
SPRITE_MOVIE = 0xBE17FA7A
MOVIE_MODULE = 0xEB9A8C92


def canonical_profile(value):
    value = ALIASES.get(value, value)
    if value not in PROFILES:
        raise BginError(f"Unknown BGIN profile: {value}")
    return value


def has_extended_directory(data):
    """Recognize the bounded directory prefix, without guessing the body."""
    try:
        r = ByteReader(data)
        r.bytes(8)
        r.text()
        size = r.u32()
        if size < 4 or size % 8 != 4 or size > r.remaining() - 2:
            return False
        start = r.pos
        first = r.u16()
        r.bytes(first * 8)
        second = r.u16()
        r.bytes(second * 8)
        return r.pos - start == size
    except ReaderError:
        return False


class Reader:
    def __init__(self, data, dialect, profile):
        if len(data) > 64 * 1024 * 1024:
            raise BginError("BGIN exceeds the size budget")
        self.data, self.dialect, self.profile = data, BginDialect(dialect), profile
        self.modern = profile == "a8-5.8.0"
        self.nodes = self.values = 0

    def budget(self, count):
        self.values += count
        if self.values > 2_000_000:
            raise BginError("BGIN exceeds the value budget")

    def values_for(self, r, kind):
        count = r.u8() if self.modern else r.u16()
        self.budget(count)
        values = []
        for _ in range(count if kind else 0):
            if kind == 2:
                value = r.f64()
            elif kind == 4:
                value = EnumToken(r.u32(), r.u32(), r.text())
            elif kind in (8, 1024):
                value = r.text()
            elif kind == 128:
                components = r.u8()
                self.budget(components)
                value = [r.f32() for _ in range(components)]
            else:
                raise BginError(f"Unsupported property kind 0x{kind:04X}")
            values.append(value)
        return count, None if kind == 0 else values[0] if count == 1 else values

    def property(self, r):
        start = r.pos
        name_hash, kind = r.u32(), r.u16()
        if kind not in ENCODINGS:
            raise BginError(f"Unsupported property kind 0x{kind:04X} at 0x{start:X}")
        count, value = self.values_for(r, kind)
        variants = []
        if self.modern:
            for _ in range(r.u8()):
                name = r.u32()
                variant_count, variant_value = self.values_for(r, kind)
                variants.append(PropertyVariant(name, variant_count, variant_value))
        return BginProperty(name_hash, kind, count, value, ENCODINGS[kind],
                            SourceSpan(start, r.pos - start), self.data[start:r.pos],
                            variants=variants)

    def properties(self, r):
        count = r.u16()
        self.budget(count)
        return [self.property(r) for _ in range(count)]

    def frame(self, r):
        start, index = r.pos, r.u32()
        if index == 0xFFFFFFFF:
            return None
        flags = r.u16()
        if flags & ~0x3F:
            raise BginError(f"Unsupported keyframe flags at 0x{start:X}")
        self.budget(1)
        frame = SpriteKeyframe(index, flags, SourceSpan(start, 0), b"")
        if flags & 1:
            frame.position_interpolation, frame.position = r.u8(), (r.f32(), r.f32())
        if flags & 2:
            frame.rotation_interpolation, frame.rotation = r.u8(), r.f32()
        if flags & 4:
            frame.scale_interpolation, frame.scale = r.u8(), (r.f32(), r.f32())
        if flags & 0x10:
            frame.string_pair = r.text(), r.text()
        if flags & 8:
            frame.event = r.text(), r.u32(), r.u32(), r.u8()
        if flags & 0x20:
            if self.modern:
                count = r.u16()
                self.budget(count)
                for _ in range(count):
                    name_hash, interpolation, size = r.u32(), r.u8(), r.u8()
                    self.budget(size)
                    frame.color_channels.append(SpriteColorChannel(
                        name_hash, interpolation, [r.f32() for _ in range(size)]))
            else:
                frame.color_properties = self.properties(r)
        frame.span = SourceSpan(start, r.pos - start)
        frame.source_bytes = self.data[start:r.pos]
        return frame

    def node(self, parent, depth=1):
        self.nodes += 1
        if depth > 128 or self.nodes > 200_000:
            raise BginError("BGIN exceeds the nesting or node budget")
        start = parent.pos
        type_hash, size = parent.u32(), parent.u32()
        parent.require(size)
        end = parent.pos + size
        r = ByteReader(self.data, parent.pos, end)
        node = BginNode(type_hash, r.text(), SourceSpan(start, end - start),
                        self.data[start:end])
        if self.dialect == BginDialect.SPRITES and type_hash == MOVIE:
            payload_start = r.pos
            count = r.u16()
            self.budget(count)
            sprites = [self.node(r, depth + 1) for _ in range(count)]
            if any(s.type_hash != SPRITE_MOVIE for s in sprites):
                raise BginError("Movie contains a non-SpriteMovie child")
            a, b, c, flags = r.u32(), r.u32(), r.u32(), r.u8()
            count = r.u32()
            self.budget(count)
            tracks = []
            for _ in range(count):
                track_start, marker = r.pos, r.u8()
                child = self.node(r, depth + 1)
                if child.type_hash != MOVIE_MODULE:
                    raise BginError("Track contains a non-MovieModule node")
                frames = []
                while True:
                    frame = self.frame(r)
                    if frame is None:
                        break
                    frames.append(frame)
                tracks.append(SpriteMovieTrack(marker, child, frames, 0xFFFFFFFF,
                    SourceSpan(track_start, r.pos - track_start), self.data[track_start:r.pos]))
            node.sprite_movie = SpriteMoviePayload(sprites, a, b, c, flags, tracks,
                SourceSpan(payload_start, r.pos - payload_start), self.data[payload_start:r.pos])
        else:
            node.metadata = b"" if self.modern else r.bytes(20)
            node.properties = self.properties(r)
            count = r.u16()
            self.budget(count)
            node.children = [self.node(r, depth + 1) for _ in range(count)]
        if r.pos != end:
            raise BginError(f"Unconsumed node bytes at 0x{r.pos:X}")
        parent.pos = end
        return node

    def document(self):
        r = ByteReader(self.data)
        magic, file_hash, name = r.u32(), r.u32(), r.text()
        if magic != 0xC1AAA or file_hash != 0x9456A530:
            raise BginError("Invalid BGIN signature")
        size = r.u32()
        block_start = r.pos
        count = r.u16()
        r.require(8 * count + 2)
        entries = [(r.u32(), r.u32()) for _ in range(count)]
        secondary_count = r.u16()
        r.require(8 * secondary_count + 2)
        secondary = [(r.u32(), r.u32()) for _ in range(secondary_count)]
        if r.pos - block_start != size:
            raise BginError("BGIN directory size does not match its tables")
        repeated = r.u16()
        if repeated != count + secondary_count:
            raise BginError("BGIN directory count does not match its tables")
        if secondary:
            raise BginError(f"Unsupported BGIN second-table records ({len(secondary)}); saving is unavailable")
        if not entries:
            raise BginError("BGIN document has no ordinary screens")
        if entries[0][1] != r.pos:
            raise BginError("First screen offset does not follow the BGIN directory")
        if self.dialect == BginDialect.AUTO:
            from .codec import infer_dialect
            self.dialect = infer_dialect(name)
            if ByteReader(self.data, r.pos).u32() == 0x3BA2E9E2:
                self.dialect = BginDialect.SPRITES
        screens = []
        for index, (name_hash, offset) in enumerate(entries):
            limit = entries[index + 1][1] if index + 1 < len(entries) else len(self.data)
            if not r.pos == offset < limit <= len(self.data):
                raise BginError(f"Invalid screen offset at index {index}")
            node = self.node(r)
            if r.pos != limit:
                raise BginError(f"Screen {index} does not fill its directory range")
            from .hashes import jet_hash
            if jet_hash(node.name) != name_hash:
                raise BginError(f"Directory hash does not match screen {index}")
            screens.append(BginScreen(name_hash, offset, node))
        return BginDocument(magic, file_hash, name, self.dialect, screens,
                            repeated, b"", self.data, wire_format=self.profile)


def decode_extended(data, dialect, profile="auto"):
    candidates = ("a8-3.7.0", "a8-5.8.0") if profile == "auto" else (canonical_profile(profile),)
    successes, errors = [], []
    for selected in candidates:
        try:
            successes.append(Reader(data, dialect, selected).document())
        except (ReaderError, BginError, RecursionError) as error:
            errors.append(f"{selected}: {error}")
    if len(successes) == 1:
        return successes[0]
    if successes:
        raise BginError("Ambiguous BGIN profile; select a profile explicitly")
    raise BginError("; ".join(errors))


class Writer:
    def __init__(self, modern):
        self.modern = modern

    def values_for(self, w, prop, count, value):
        if prop.kind not in ENCODINGS:
            raise BginError(f"Unsupported property kind 0x{prop.kind:X}")
        values = [] if prop.kind == 0 else [value] if count == 1 else value
        if not isinstance(values, list):
            raise BginError("Property values must be a list")
        actual_count = count if prop.kind == 0 else len(values)
        (w.u8 if self.modern else w.u16)(actual_count)
        for value in values:
            if prop.kind == 2:
                w.f64(value)
            elif prop.kind == 4:
                if not isinstance(value, EnumToken):
                    value = EnumToken(*value)
                w.u32(value.code & 0xFFFFFFFF).u32(value.name_hash).text(value.name)
            elif prop.kind in (8, 1024):
                w.text(value)
            elif prop.kind == 128:
                w.u8(len(value))
                for component in value:
                    w.f32(component)

    def property(self, prop):
        w = ByteWriter().u32(prop.name_hash).u16(prop.kind)
        self.values_for(w, prop, prop.count or 0, prop.value)
        if self.modern:
            w.u8(len(prop.variants))
            for variant in prop.variants:
                w.u32(variant.name_hash)
                self.values_for(w, prop, variant.count, variant.value)
        elif prop.variants:
            raise BginError("This BGIN profile cannot store property variants")
        return w.build()

    def properties(self, props):
        return ByteWriter().u16(len(props)).bytes(b"".join(self.property(p) for p in props)).build()

    def frame(self, frame):
        w = ByteWriter().u32(frame.frame_index).u16(frame.flags)
        if frame.flags & ~0x3F:
            raise BginError("Unsupported keyframe flags")
        if frame.flags & 1:
            w.u8(frame.position_interpolation).f32(frame.position[0]).f32(frame.position[1])
        if frame.flags & 2:
            w.u8(frame.rotation_interpolation).f32(frame.rotation)
        if frame.flags & 4:
            w.u8(frame.scale_interpolation).f32(frame.scale[0]).f32(frame.scale[1])
        if frame.flags & 0x10:
            w.text(frame.string_pair[0]).text(frame.string_pair[1])
        if frame.flags & 8:
            w.text(frame.event[0]).u32(frame.event[1]).u32(frame.event[2]).u8(frame.event[3])
        if frame.flags & 0x20:
            if self.modern:
                if frame.color_properties:
                    raise BginError("5.8.0 color channels require their explicit channel representation")
                w.u16(len(frame.color_channels))
                for channel in frame.color_channels:
                    w.u32(channel.name_hash).u8(channel.interpolation).u8(len(channel.values))
                    for component in channel.values:
                        w.f32(component)
            else:
                if frame.color_channels:
                    raise BginError("This BGIN profile cannot store 5.8.0 color channels")
                w.bytes(self.properties(frame.color_properties))
        elif frame.color_channels or frame.color_properties:
            raise BginError("Color data without a color keyframe flag")
        return w.build()

    def node(self, node):
        node.require_decoded()
        w = ByteWriter().text(node.name)
        if node.sprite_movie is not None:
            movie = node.sprite_movie
            w.u16(len(movie.sprite_movies))
            for child in movie.sprite_movies:
                w.bytes(self.node(child))
            w.u32(movie.header_a).u32(movie.header_b).u32(movie.header_c).u8(movie.header_flags)
            w.u32(len(movie.tracks))
            for track in movie.tracks:
                w.u8(track.marker).bytes(self.node(track.node))
                for frame in track.keyframes:
                    w.bytes(self.frame(frame))
                w.u32(track.terminator)
        else:
            if self.modern:
                if node.metadata:
                    raise BginError("5.8.0 cannot store the earlier transform block")
            else:
                if len(node.metadata) != 20:
                    raise BginError("This BGIN profile requires a 20-byte transform block")
                w.bytes(node.metadata)
            w.bytes(self.properties(node.properties)).u16(len(node.children))
            for child in node.children:
                w.bytes(self.node(child))
        payload = w.build()
        return ByteWriter().u32(node.type_hash).u32(len(payload)).bytes(payload).build()

    def document(self, document):
        if document.directory_trailing_bytes:
            raise BginError("Extended BGIN directories cannot store unknown trailing bytes")
        blobs = [self.node(screen.node) for screen in document.screens]
        if not blobs:
            raise BginError("BGIN document has no screens")
        name = ByteWriter().text(document.name).build()
        offset = 8 + len(name) + 4 + 4 + 8 * len(blobs) + 2
        w = ByteWriter().u32(document.magic).u32(document.file_hash).bytes(name)
        w.u32(4 + 8 * len(blobs)).u16(len(blobs))
        for screen, blob in zip(document.screens, blobs):
            from .hashes import jet_hash
            w.u32(jet_hash(screen.node.name)).u32(offset)
            offset += len(blob)
        w.u16(0).u16(len(blobs))
        for blob in blobs:
            w.bytes(blob)
        return w.build()


def encode_extended(document):
    return Writer(canonical_profile(document.wire_format) == "a8-5.8.0").document(document)
