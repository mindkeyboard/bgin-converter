"""Independent transaction codec for the string-name Database BGIN variant.

Verified against all nine supplied June 2013 documents, including animation
tracks. Runtime layout policy is deliberately outside this wire codec.
"""
from .hashes import jet_hash, get_property_name, get_type_name
from .model import (BginDialect, BginDocument, BginError, BginNode, BginProperty,
                    BginScreen, EnumToken, SourceSpan, SpriteKeyframe,
                    SpriteMoviePayload, SpriteMovieTrack)
from .reader import ByteReader, ByteWriter

MARKER = b"\x08\x00Database"


class Reader:
    def __init__(self, data, dialect):
        if len(data) > 64 * 1024 * 1024:
            raise BginError("Legacy BGIN exceeds the size budget")
        self.data, self.dialect = data, BginDialect(dialect)
        self.nodes = self.values = 0

    def budget(self, count):
        self.values += count
        if self.values > 2_000_000:
            raise BginError("Legacy BGIN exceeds the value budget")

    def properties(self, r):
        count = r.u16()
        self.budget(count)
        result = []
        for _ in range(count):
            start = r.pos
            name, kind, count = r.text(), r.u32(), r.u16()
            self.budget(count)
            encodings = {0: "empty", 2: "f64", 4: "enum_token", 8: "path", 128: "f32_vector", 1024: "string"}
            if kind not in encodings:
                raise BginError(f"Unsupported legacy property kind {kind} at {start}")
            values = []
            for _ in range(count if kind else 0):
                if kind == 2:
                    value = r.f64()
                elif kind == 4:
                    code, label = r.u32(), r.text()
                    value = EnumToken(code, jet_hash(label), label)
                elif kind in (8, 1024):
                    value = r.text()
                else:
                    components = r.u8()
                    self.budget(components)
                    value = [r.f32() for _ in range(components)]
                values.append(value)
            value = None if kind == 0 else values[0] if count == 1 else values
            result.append(BginProperty(jet_hash(name), kind, count, value, encodings[kind],
                                      SourceSpan(start, r.pos - start), self.data[start:r.pos], literal_name=name))
        return result

    def frame(self, r):
        start, index = r.pos, r.u32()
        if index == 0xFFFFFFFF:
            return None
        flags = r.u16()
        if flags & ~0x3F:
            raise BginError(f"Unsupported legacy keyframe flags at {start}")
        self.budget(1)
        f = SpriteKeyframe(index, flags, SourceSpan(start, 0), b"")
        if flags & 1:
            f.position_interpolation, f.position = r.u8(), (r.f32(), r.f32())
        if flags & 2:
            f.rotation_interpolation, f.rotation = r.u8(), r.f32()
        if flags & 4:
            f.scale_interpolation, f.scale = r.u8(), (r.f32(), r.f32())
        if flags & 0x10:
            f.string_pair = r.text(), r.text()
        if flags & 8:
            f.event = r.text(), r.u32(), r.u32(), r.u8()
        if flags & 0x20:
            f.color_properties = self.properties(r)
        f.span, f.source_bytes = SourceSpan(start, r.pos - start), self.data[start:r.pos]
        return f

    def node(self, parent, depth=1):
        self.nodes += 1
        if depth > 128 or self.nodes > 200_000:
            raise BginError("Legacy BGIN exceeds the nesting or node budget")
        start = parent.pos
        type_name, size = parent.text(), parent.u32()
        parent.require(size)
        end = parent.pos + size
        r = ByteReader(self.data, parent.pos, end)
        node = BginNode(jet_hash(type_name), r.text(), SourceSpan(start, end - start),
                        self.data[start:end], literal_type=type_name)
        if self.dialect == BginDialect.SPRITES and type_name == "Movie":
            payload_start = r.pos
            count = r.u16()
            self.budget(count)
            sprites = [self.node(r, depth + 1) for _ in range(count)]
            if any(s.literal_type != "SpriteMovie" for s in sprites):
                raise BginError("Legacy Movie contains a non-SpriteMovie child")
            a, b, c, flags = r.u32(), r.u32(), r.u32(), r.u8()
            count = r.u32()
            self.budget(count)
            tracks = []
            for _ in range(count):
                track_start, marker = r.pos, r.u8()
                child = self.node(r, depth + 1)
                if child.literal_type != "MovieModule":
                    raise BginError("Legacy track contains a non-MovieModule node")
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
            node.metadata = r.bytes(20)
            node.properties = self.properties(r)
            count = r.u16()
            self.budget(count)
            node.children = [self.node(r, depth + 1) for _ in range(count)]
        if r.pos != end:
            raise BginError(f"Unconsumed legacy node bytes at {r.pos}")
        parent.pos = end
        return node

    def document(self):
        r = ByteReader(self.data)
        if r.u32() != 0xC1AAA or r.text() != "Database":
            raise BginError("Invalid legacy BGIN header")
        name = r.text()
        automatic = self.dialect == BginDialect.AUTO
        if automatic:
            self.dialect = {"widgets": BginDialect.TEMPLATES, "sprites": BginDialect.SPRITES}.get(name.lower(), BginDialect.UI)
        count = r.u16()
        if not count:
            raise BginError("Legacy BGIN has no screens")
        if automatic and ByteReader(self.data, r.pos).text() == "Sprite":
            self.dialect = BginDialect.SPRITES
        screens = []
        for _ in range(count):
            offset = r.pos
            node = self.node(r)
            screens.append(BginScreen(jet_hash(node.name), offset, node))
        if not r.eof():
            raise BginError("Unconsumed legacy document bytes")
        return BginDocument(0xC1AAA, jet_hash("Database"), name, self.dialect, screens,
                            count, b"", self.data, wire_format="legacy")


def decode_legacy(data, dialect):
    return Reader(data, dialect).document()


def property_bytes(prop):
    name = prop.literal_name if prop.literal_name is not None else get_property_name(prop.name_hash)
    if name is None or prop.literal_name is None and name.startswith("unknown_"):
        raise BginError("Legacy property spelling is missing")
    w = ByteWriter().text(name).u32(prop.kind)
    if prop.kind == 0:
        return w.u16(prop.count or 0).build()
    values = [prop.value] if prop.count == 1 else prop.value
    if not isinstance(values, list):
        raise BginError("Legacy property values must be a list")
    w.u16(len(values))
    for value in values:
        if prop.kind == 2:
            w.f64(value)
        elif prop.kind == 4:
            if not isinstance(value, EnumToken):
                value = EnumToken(*value)
            w.u32(value.code & 0xFFFFFFFF).text(value.name)
        elif prop.kind in (8, 1024):
            w.text(value)
        elif prop.kind == 128:
            w.u8(len(value))
            for component in value:
                w.f32(component)
        else:
            raise BginError(f"Unsupported legacy property kind {prop.kind}")
    return w.build()


def properties_bytes(properties):
    return ByteWriter().u16(len(properties)).bytes(b"".join(property_bytes(p) for p in properties)).build()


def frame_bytes(f):
    w = ByteWriter().u32(f.frame_index).u16(f.flags)
    if f.flags & 1:
        w.u8(f.position_interpolation).f32(f.position[0]).f32(f.position[1])
    if f.flags & 2:
        w.u8(f.rotation_interpolation).f32(f.rotation)
    if f.flags & 4:
        w.u8(f.scale_interpolation).f32(f.scale[0]).f32(f.scale[1])
    if f.flags & 0x10:
        w.text(f.string_pair[0]).text(f.string_pair[1])
    if f.flags & 8:
        w.text(f.event[0]).u32(f.event[1]).u32(f.event[2]).u8(f.event[3])
    if f.flags & 0x20:
        w.bytes(properties_bytes(f.color_properties))
    return w.build()


def node_bytes(node, force):
    if not force and not node.is_dirty():
        return node.source_bytes
    node.require_decoded()
    type_name = node.literal_type if node.literal_type is not None else get_type_name(node.type_hash)
    if type_name is None or node.literal_type is None and type_name.startswith("unknown_"):
        raise BginError("Legacy node type spelling is missing")
    w = ByteWriter().text(node.name)
    if node.sprite_movie is not None:
        m = node.sprite_movie
        w.u16(len(m.sprite_movies))
        for child in m.sprite_movies:
            w.bytes(node_bytes(child, force))
        w.u32(m.header_a).u32(m.header_b).u32(m.header_c).u8(m.header_flags).u32(len(m.tracks))
        for track in m.tracks:
            w.u8(track.marker).bytes(node_bytes(track.node, force))
            for f in track.keyframes:
                w.bytes(frame_bytes(f))
            w.u32(track.terminator)
    else:
        w.bytes(node.metadata).bytes(properties_bytes(node.properties)).u16(len(node.children))
        for child in node.children:
            w.bytes(node_bytes(child, force))
    payload = w.build()
    return ByteWriter().text(type_name).u32(len(payload)).bytes(payload).build()


def encode_legacy(document, force=False):
    if not force and not document.is_dirty():
        return document.source_bytes
    w = ByteWriter().u32(document.magic).text("Database").text(document.name).u16(len(document.screens))
    for screen in document.screens:
        w.bytes(node_bytes(screen.node, force))
    return w.build()
