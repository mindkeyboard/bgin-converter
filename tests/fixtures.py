"""Small independent wire fixtures, built directly from the documented byte layout."""
import struct


def u16(value):
    return struct.pack("<H", value)


def u32(value):
    return struct.pack("<I", value)


def text(value):
    raw = value.encode("utf-8")
    return u16(len(raw)) + raw


def prop(kind, count, payload=b"", name_hash=0x28C8DE16):
    return u32(name_hash) + u16(kind) + u16(count) + payload


def framed(payload, type_hash=0x8706BEAF):
    return u32(type_hash) + u32(len(payload)) + payload


def node(name="root", properties=(), children=(), type_hash=0x8706BEAF):
    return framed(text(name) + struct.pack("<5f", 0, 0, 0, 1, 1) + u16(len(properties)) +
                  b"".join(properties) + u16(len(children)) + b"".join(children), type_hash)


def document(roots=None, name="fixture", extra=b""):
    roots = [node()] if roots is None else roots
    prefix = u32(0xC1AAA) + u32(0x9456A530) + text(name) + u16(len(roots))
    offset = len(prefix) + len(roots) * 8 + 2 + len(extra)
    entries = b""
    for index, root in enumerate(roots):
        size=struct.unpack_from('<H',root,8)[0]
        root_name=root[10:10+size].decode('utf-8')
        from bgin_json.parser import jet_hash
        entries += u32(jet_hash(root_name)) + u32(offset)
        offset += len(root)
    return prefix + entries + u16(len(roots)) + extra + b"".join(roots)


def sprite_document(flags=0x3F):
    sprite_movie = node("nested", type_hash=0xBE17FA7A)
    track = node("track", type_hash=0xEB9A8C92)
    frame = u32(12) + u16(flags)
    for flag, floats in ((1, (10., 20.)), (2, (45.,)), (4, (1., 2.))):
        if flags & flag:
            frame += bytes([flag]) + struct.pack("<" + "f" * len(floats), *floats)
    if flags & 0x10:
        frame += text("left") + text("right")
    if flags & 8:
        frame += text("event") + u32(7) + u32(9) + bytes([1])
    if flags & 0x20:
        frame += u16(1) + prop(0x80, 1, bytes([4]) + struct.pack("<ffff", 1., .5, .25, 1.))
    payload = (text("animation") + u16(1) + sprite_movie + u32(30) + u32(0) + u32(3333) +
               bytes([0]) + u32(1) + bytes([0x65]) + track + frame + u32(0xFFFFFFFF))
    root = node("sprite", children=[framed(payload, 0x6E739C13)], type_hash=0x3BA2E9E2)
    return document([root], name="sprites")
