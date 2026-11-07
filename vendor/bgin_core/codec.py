from __future__ import annotations

from typing import Any

from .model import (
    BginDialect,
    BginDocument,
    BginError,
    BginNode,
    BginProperty,
    BginScreen,
    EnumToken,
    SourceSpan,
    SpriteKeyframe,
    SpriteMoviePayload,
    SpriteMovieTrack,
)
from .reader import ByteReader, ByteWriter, BginError as ReaderError

SPRITE_TYPE = 0x3BA2E9E2
SPRITE_MODULE_TYPE = 0x93EF34CD
SPRITE_MOVIE_TYPE = 0x6E739C13
SPRITE_MOVIE_NODE_TYPE = 0xBE17FA7A
MOVIE_MODULE_TYPE = 0xEB9A8C92
SPRITE_KEYFRAME_FLAGS = 0x003F


def infer_dialect(name: str) -> BginDialect:
    role = name.lower()
    if role == "sprites":
        return BginDialect.SPRITES
    if role == "widgets":
        return BginDialect.TEMPLATES
    return BginDialect.UI


def _single_or_list(values: list[Any]) -> Any:
    return values[0] if len(values) == 1 else values


def _decode_property(reader: ByteReader) -> BginProperty:
    start = reader.pos
    name_hash = reader.u32()
    kind = reader.u16()
    count = reader.u16()
    value: Any = None
    encoding = "empty"

    # GUILoader::LoadParam always reads count, including for kind zero.
    if kind == 0:
        pass
    else:
        if kind == 0x0002:
            values = [reader.f64() for _ in range(count)]
            value = _single_or_list(values)
            encoding = "f64"
        elif kind == 0x0004:
            values = [
                EnumToken(reader.u32(), reader.u32(), reader.text())
                for _ in range(count)
            ]
            value = _single_or_list(values)
            encoding = "enum_token"
        elif kind == 0x0008:
            values = [reader.text() for _ in range(count)]
            value = _single_or_list(values)
            encoding = "path"
        elif kind == 0x0080:
            vectors: list[list[float]] = []
            for _ in range(count):
                component_count = reader.u8()
                if component_count > 32:
                    raise BginError(
                        f"Unreasonable vector length {component_count} at 0x{reader.pos - 1:x}"
                    )
                vectors.append([reader.f32() for _ in range(component_count)])
            value = vectors[0] if len(vectors) == 1 else vectors
            encoding = "f32_vector"
        elif kind == 0x0400:
            values = [reader.text() for _ in range(count)]
            value = _single_or_list(values)
            encoding = "string"
        else:
            raise BginError(f"Unknown property kind 0x{kind:04x} at 0x{start:x}")

    end = reader.pos
    return BginProperty(
        name_hash=name_hash,
        kind=kind,
        count=count,
        value=value,
        encoding=encoding,
        span=SourceSpan(start, end - start),
        source_bytes=reader.data[start:end],
    )


def _peek_opaque_node(data: bytes, offset: int, limit: int, reason: str) -> BginNode:
    reader = ByteReader(data, offset, limit)
    type_hash = reader.u32()
    payload_size = reader.u32()
    end = offset + 8 + payload_size
    if end > limit:
        raise BginError(f"Node at 0x{offset:x} exceeds its containing range")
    try:
        name = reader.text()
    except BginError:
        name = ""
    return BginNode(
        type_hash=type_hash,
        name=name,
        span=SourceSpan(offset, end - offset),
        source_bytes=data[offset:end],
        decoded=False,
        opaque_reason=reason,
    )


def _decode_ui_node(data: bytes, offset: int, limit: int) -> BginNode:
    header = ByteReader(data, offset, limit)
    type_hash = header.u32()
    payload_size = header.u32()
    end = offset + 8 + payload_size
    if payload_size < 24 or end > limit:
        raise BginError(f"Invalid node size {payload_size} at 0x{offset:x}")

    reader = ByteReader(data, header.pos, end)
    try:
        name = reader.text()
        metadata = reader.bytes(20)
        property_count = reader.u16()
        properties = [_decode_property(reader) for _ in range(property_count)]
        child_count = reader.u16()
        children: list[BginNode] = []
        for _ in range(child_count):
            child = _decode_ui_node(data, reader.pos, end)
            children.append(child)
            reader.pos = child.span.end
        if reader.pos != end:
            raise BginError(
                f"Node payload has {end - reader.pos} trailing bytes at 0x{reader.pos:x}"
            )
    except BginError as error:
        return _peek_opaque_node(data, offset, limit, str(error))

    return BginNode(
        type_hash=type_hash,
        name=name,
        span=SourceSpan(offset, end - offset),
        source_bytes=data[offset:end],
        metadata=metadata,
        properties=properties,
        children=children,
    )


def _decode_sprite_generic_node(data: bytes, offset: int, limit: int) -> BginNode:
    header = ByteReader(data, offset, limit)
    type_hash = header.u32()
    payload_size = header.u32()
    end = offset + 8 + payload_size
    if payload_size < 24 or end > limit:
        raise BginError(f"Invalid sprite node size {payload_size} at 0x{offset:x}")

    reader = ByteReader(data, header.pos, end)
    try:
        name = reader.text()
        metadata = reader.bytes(20)
        property_count = reader.u16()
        properties = [_decode_property(reader) for _ in range(property_count)]
        child_count = reader.u16()
        children: list[BginNode] = []
        for _ in range(child_count):
            child = _decode_sprite_node(data, reader.pos, end)
            children.append(child)
            reader.pos = child.span.end
        if reader.pos != end:
            raise BginError(
                f"Sprite node has {end - reader.pos} trailing bytes at 0x{reader.pos:x}"
            )
    except BginError as error:
        return _peek_opaque_node(data, offset, limit, str(error))

    return BginNode(
        type_hash=type_hash,
        name=name,
        span=SourceSpan(offset, end - offset),
        source_bytes=data[offset:end],
        metadata=metadata,
        properties=properties,
        children=children,
    )


def _decode_sprite_keyframe(reader: ByteReader) -> SpriteKeyframe | None:
    start = reader.pos
    frame_index = reader.u32()
    if frame_index == 0xFFFFFFFF:
        return None
    flags = reader.u16()
    if flags & ~SPRITE_KEYFRAME_FLAGS:
        raise BginError(
            f"Unknown sprite keyframe flags 0x{flags:04x} at 0x{start:x}"
        )

    values: dict[str, Any] = {}
    if flags & 0x01:
        values["position_interpolation"] = reader.u8()
        values["position"] = (reader.f32(), reader.f32())
    if flags & 0x02:
        values["rotation_interpolation"] = reader.u8()
        values["rotation"] = reader.f32()
    if flags & 0x04:
        values["scale_interpolation"] = reader.u8()
        values["scale"] = (reader.f32(), reader.f32())
    if flags & 0x10:
        values["string_pair"] = (reader.text(), reader.text())
    if flags & 0x08:
        values["event"] = (reader.text(), reader.u32(), reader.u32(), reader.u8())
    color_properties: list[BginProperty] = []
    if flags & 0x20:
        color_properties = [_decode_property(reader) for _ in range(reader.u16())]

    end = reader.pos
    return SpriteKeyframe(
        frame_index=frame_index,
        flags=flags,
        span=SourceSpan(start, end - start),
        source_bytes=reader.data[start:end],
        color_properties=color_properties,
        **values,
    )


def _decode_sprite_movie_node(data: bytes, offset: int, limit: int) -> BginNode:
    header = ByteReader(data, offset, limit)
    type_hash = header.u32()
    payload_size = header.u32()
    end = offset + 8 + payload_size
    if type_hash != SPRITE_MOVIE_TYPE or end > limit:
        raise BginError(f"Invalid sprite Movie record at 0x{offset:x}")

    reader = ByteReader(data, header.pos, end)
    try:
        name = reader.text()
        payload_start = reader.pos
        sprite_movies: list[BginNode] = []
        for _ in range(reader.u16()):
            node = _decode_sprite_generic_node(data, reader.pos, end)
            if not node.decoded or node.type_hash != SPRITE_MOVIE_NODE_TYPE:
                raise BginError(f"Invalid SpriteMovie child at 0x{reader.pos:x}")
            sprite_movies.append(node)
            reader.pos = node.span.end

        header_a = reader.u32()
        header_b = reader.u32()
        header_c = reader.u32()
        header_flags = reader.u8()
        tracks: list[SpriteMovieTrack] = []
        for _ in range(reader.u32()):
            track_start = reader.pos
            marker = reader.u8()
            track_node = _decode_sprite_generic_node(data, reader.pos, end)
            if not track_node.decoded or track_node.type_hash != MOVIE_MODULE_TYPE:
                raise BginError(f"Invalid MovieModule track at 0x{reader.pos:x}")
            reader.pos = track_node.span.end
            keyframes: list[SpriteKeyframe] = []
            while True:
                keyframe = _decode_sprite_keyframe(reader)
                if keyframe is None:
                    break
                keyframes.append(keyframe)
            track_end = reader.pos
            tracks.append(
                SpriteMovieTrack(
                    marker=marker,
                    node=track_node,
                    keyframes=keyframes,
                    terminator=0xFFFFFFFF,
                    span=SourceSpan(track_start, track_end - track_start),
                    source_bytes=data[track_start:track_end],
                )
            )
        if reader.pos != end:
            raise BginError(
                f"Sprite Movie has {end - reader.pos} trailing bytes at 0x{reader.pos:x}"
            )
    except BginError as error:
        return _peek_opaque_node(data, offset, limit, str(error))

    return BginNode(
        type_hash=type_hash,
        name=name,
        span=SourceSpan(offset, end - offset),
        source_bytes=data[offset:end],
        sprite_movie=SpriteMoviePayload(
            sprite_movies=sprite_movies,
            header_a=header_a,
            header_b=header_b,
            header_c=header_c,
            header_flags=header_flags,
            tracks=tracks,
            span=SourceSpan(payload_start, end - payload_start),
            source_bytes=data[payload_start:end],
        ),
    )


def _decode_sprite_node(data: bytes, offset: int, limit: int) -> BginNode:
    reader = ByteReader(data, offset, limit)
    type_hash = reader.u32()
    if type_hash == SPRITE_MOVIE_TYPE:
        return _decode_sprite_movie_node(data, offset, limit)
    return _decode_sprite_generic_node(data, offset, limit)


def decode_document(
    data: bytes, dialect: BginDialect | str = BginDialect.AUTO
) -> BginDocument:
    if data[4:14] == b"\x08\x00Database":
        from .legacy import decode_legacy
        return decode_legacy(data, dialect)
    reader = ByteReader(data)
    magic = reader.u32()
    file_hash = reader.u32()
    name = reader.text()
    screen_count = reader.u16()
    entries = [(reader.u32(), reader.u32()) for _ in range(screen_count)]
    if not entries:
        raise BginError("BGIN document has no screens")

    first_offset = entries[0][1]
    if first_offset < reader.pos or first_offset > len(data):
        raise BginError(f"Invalid first screen offset 0x{first_offset:x}")
    if first_offset - reader.pos < 2:
        raise BginError("BGIN screen directory is missing its repeated count")
    directory_count = reader.u16()
    directory_trailing_bytes = data[reader.pos:first_offset]
    if directory_count != screen_count:
        raise BginError(
            f"Screen directory count {directory_count} does not match {screen_count}"
        )

    selected = BginDialect(dialect)
    if selected is BginDialect.AUTO:
        selected = infer_dialect(name)

    screens: list[BginScreen] = []
    for index, (name_hash, offset) in enumerate(entries):
        limit = entries[index + 1][1] if index + 1 < len(entries) else len(data)
        if not first_offset <= offset < limit <= len(data):
            raise BginError(f"Invalid screen range at index {index}")
        if selected is BginDialect.SPRITES:
            node = _decode_sprite_node(data, offset, limit)
        else:
            node = _decode_ui_node(data, offset, limit)
        if node.span.end != limit:
            raise BginError(
                f"Screen {index} consumes 0x{node.span.end:x}, expected 0x{limit:x}"
            )
        screens.append(BginScreen(name_hash, offset, node))

    return BginDocument(
        magic=magic,
        file_hash=file_hash,
        name=name,
        dialect=selected,
        screens=screens,
        directory_count=directory_count,
        directory_trailing_bytes=directory_trailing_bytes,
        source_bytes=data,
    )


def _as_values(value: Any, count: int | None) -> list[Any]:
    if count == 1:
        return [value]
    if isinstance(value, list):
        return value
    return [value]


def _encode_property(prop: BginProperty, force: bool = False) -> bytes:
    if not prop.dirty and not force:
        return prop.source_bytes
    if prop.encoding == "empty":
        return ByteWriter().u32(prop.name_hash).u16(prop.kind).u16(prop.count or 0).build()

    values = _as_values(prop.value, prop.count)
    header = ByteWriter().u32(prop.name_hash).u16(prop.kind).u16(len(values)).build()
    if prop.encoding == "f64":
        w = ByteWriter()
        for v in values:
            w.f64(float(v))
        payload = w.build()
    elif prop.encoding == "enum_token":
        w = ByteWriter()
        for token in values:
            if not isinstance(token, EnumToken):
                token = EnumToken(int(token[0]), int(token[1]), str(token[2]))
            w.u32(token.code).u32(token.name_hash).text(token.name)
        payload = w.build()
    elif prop.encoding in {"path", "string"}:
        w = ByteWriter()
        for v in values:
            w.text(str(v))
        payload = w.build()
    elif prop.encoding == "f32_vector":
        vectors = values
        if prop.count == 1 and values and not isinstance(values[0], list):
            vectors = [values]
        w = ByteWriter()
        for vector in vectors:
            components = [float(component) for component in vector]
            if len(components) > 0xFF:
                raise BginError("Float vector has more than 255 components")
            w.u8(len(components))
            for c in components:
                w.f32(c)
        payload = w.build()
    else:
        raise BginError(f"Property encoding {prop.encoding!r} is not writable")
    return header + payload


def _encode_node(node: BginNode, force: bool = False) -> bytes:
    if not node.is_dirty() and not force:
        return node.source_bytes
    if not node.decoded:
        if node.is_dirty():
            node.require_decoded()
        return node.source_bytes
    node.require_decoded()
    if node.sprite_movie is not None:
        payload = ByteWriter().text(node.name).bytes(
            _encode_sprite_movie_payload(node.sprite_movie, force)
        ).build()
        w = ByteWriter()
        w.u32(node.type_hash).u32(len(payload)).bytes(payload)
        return w.build()
    inner = ByteWriter()
    inner.text(node.name).bytes(node.metadata)
    inner.u16(len(node.properties))
    for prop in node.properties:
        inner.bytes(_encode_property(prop, force))
    inner.u16(len(node.children))
    for child in node.children:
        inner.bytes(_encode_node(child, force))
    payload = inner.build()
    w = ByteWriter()
    w.u32(node.type_hash).u32(len(payload)).bytes(payload)
    return w.build()


def _encode_sprite_keyframe(
    keyframe: SpriteKeyframe, force: bool = False
) -> bytes:
    if not keyframe.is_dirty() and not force:
        return keyframe.source_bytes
    w = ByteWriter()
    w.u32(keyframe.frame_index).u16(keyframe.flags)
    if keyframe.flags & 0x01:
        if keyframe.position_interpolation is None or keyframe.position is None:
            raise BginError("Position keyframe payload is missing")
        w.u8(keyframe.position_interpolation).f32(keyframe.position[0]).f32(keyframe.position[1])
    if keyframe.flags & 0x02:
        if keyframe.rotation_interpolation is None or keyframe.rotation is None:
            raise BginError("Rotation keyframe payload is missing")
        w.u8(keyframe.rotation_interpolation).f32(keyframe.rotation)
    if keyframe.flags & 0x04:
        if keyframe.scale_interpolation is None or keyframe.scale is None:
            raise BginError("Scale keyframe payload is missing")
        w.u8(keyframe.scale_interpolation).f32(keyframe.scale[0]).f32(keyframe.scale[1])
    if keyframe.flags & 0x10:
        if keyframe.string_pair is None:
            raise BginError("String-pair keyframe payload is missing")
        w.text(keyframe.string_pair[0]).text(keyframe.string_pair[1])
    if keyframe.flags & 0x08:
        if keyframe.event is None:
            raise BginError("Event keyframe payload is missing")
        event_name, event_a, event_b, event_flags = keyframe.event
        w.text(event_name).u32(event_a).u32(event_b).u8(event_flags)
    if keyframe.flags & 0x20:
        w.u16(len(keyframe.color_properties))
        for prop in keyframe.color_properties:
            w.bytes(_encode_property(prop, force))
    return w.build()


def _encode_sprite_movie_track(
    track: SpriteMovieTrack, force: bool = False
) -> bytes:
    if not track.is_dirty() and not force:
        return track.source_bytes
    w = ByteWriter()
    w.u8(track.marker)
    w.bytes(_encode_node(track.node, force))
    for frame in track.keyframes:
        w.bytes(_encode_sprite_keyframe(frame, force))
    w.u32(track.terminator)
    return w.build()


def _encode_sprite_movie_payload(
    payload: SpriteMoviePayload, force: bool = False
) -> bytes:
    if not payload.is_dirty() and not force:
        return payload.source_bytes
    w = ByteWriter()
    w.u16(len(payload.sprite_movies))
    for node in payload.sprite_movies:
        w.bytes(_encode_node(node, force))
    w.u32(payload.header_a).u32(payload.header_b).u32(payload.header_c)
    w.u8(payload.header_flags)
    w.u32(len(payload.tracks))
    for track in payload.tracks:
        w.bytes(_encode_sprite_movie_track(track, force))
    return w.build()


def encode_document(document: BginDocument, force: bool = False) -> bytes:
    if document.wire_format == "legacy":
        from .legacy import encode_legacy
        return encode_legacy(document, force)
    if not document.is_dirty() and not force:
        return document.source_bytes

    screen_blobs = [
        _encode_node(screen.node, force) for screen in document.screens
    ]
    name_encoded = ByteWriter().text(document.name).build()
    header_size = 4 + 4 + len(name_encoded) + 2
    offset = (
        header_size
        + len(document.screens) * 8
        + 2
        + len(document.directory_trailing_bytes)
    )
    entries: list[tuple[int, int]] = []
    for screen, blob in zip(document.screens, screen_blobs):
        entries.append((screen.name_hash, offset))
        offset += len(blob)

    w = ByteWriter()
    w.u32(document.magic).u32(document.file_hash)
    w.bytes(name_encoded)
    w.u16(len(document.screens))
    for name_hash, screen_offset in entries:
        w.u32(name_hash).u32(screen_offset)
    w.u16(len(document.screens))
    w.bytes(document.directory_trailing_bytes)
    for blob in screen_blobs:
        w.bytes(blob)
    return w.build()


def clone_document(document: BginDocument) -> BginDocument:
    # Re-decode the exact wire representation so mutable lists are independent
    # while all unknown bytes and source spans remain lossless.
    return decode_document(encode_document(document), document.dialect)


def set_property_value(
    document: BginDocument,
    screen_index: int,
    node_path: list[int] | tuple[int, ...],
    property_hash: int,
    value: Any,
) -> None:
    node = document.screens[screen_index].node.find(node_path)
    node.require_decoded()
    prop = node.property_by_hash(property_hash)
    if prop is None:
        raise BginError(f"Property 0x{property_hash:08x} is absent on node {node.name!r}")
    prop.set_value(value)
