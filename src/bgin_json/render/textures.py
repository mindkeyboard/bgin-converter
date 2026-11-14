"""Header-driven texture decoding. No game resources are bundled or synthesized."""

import struct
from io import BytesIO
from pathlib import Path

from ..resource_formats import ASTC_BLOCKS, pvr_layout


def _zstd06_frame_size(frame, expected):
    """Bound one legacy v0.6 frame before calling the native decoder.

    The frame/content and block-header layout follows zstd's zstd_v06.c.
    A known content size and a single complete frame keep the Python wrapper's
    allocation bounded; unknown-size or concatenated frames are not accepted.
    """
    if len(frame) < 6 or frame[:4] != b"\x26\xb5\x2f\xfd":
        raise ValueError("Unsupported Zstd frame generation")
    descriptor = frame[4]
    size_bytes = (0, 1, 2, 8)[descriptor >> 6]
    if descriptor & 0x20 or not size_bytes or len(frame) < 5 + size_bytes:
        raise ValueError("Invalid or unbounded Zstd v0.6 content size")
    declared = int.from_bytes(frame[5:5 + size_bytes], "little") + (256 if size_bytes == 2 else 0)
    if declared != expected:
        raise ValueError("Zstd frame output size disagrees with PVR mip")
    position = 5 + size_bytes
    while True:
        if position + 3 > len(frame):
            raise ValueError("Truncated Zstd v0.6 block header")
        first, second, third = frame[position:position + 3]
        position += 3
        kind = first >> 6
        size = third + (second << 8) + ((first & 7) << 16)
        if kind == 3:
            if position != len(frame):
                raise ValueError("Unexpected or concatenated Zstd frame data")
            return
        position += 1 if kind == 2 else size
        if position > len(frame):
            raise ValueError("Truncated Zstd v0.6 block")


def _modern_zstd_frame_size(frame, expected):
    """Validate a bounded standard frame, including checksum and exact end."""
    if len(frame) < 6 or frame[:4] != b"\x28\xb5\x2f\xfd":
        raise ValueError("Unsupported Zstd frame generation")
    descriptor = frame[4]
    if descriptor & 0x18:
        raise ValueError("Unsupported Zstd frame descriptor")
    single = bool(descriptor & 0x20)
    size_flag = descriptor >> 6
    size_bytes = (1 if single else 0) if size_flag == 0 else (2, 4, 8)[size_flag - 1]
    position = 5 + (0 if single else 1) + (0, 1, 2, 4)[descriptor & 3]
    if not size_bytes or position + size_bytes > len(frame):
        raise ValueError("Invalid or unbounded Zstd content size")
    declared = int.from_bytes(frame[position:position + size_bytes], "little") + (256 if size_flag == 1 else 0)
    if declared != expected:
        raise ValueError("Zstd frame output size disagrees with PVR mip")
    position += size_bytes
    while True:
        if position + 3 > len(frame):
            raise ValueError("Truncated Zstd block header")
        header = int.from_bytes(frame[position:position + 3], "little")
        position += 3
        kind, size = (header >> 1) & 3, header >> 3
        if kind == 3 or size > 128 * 1024:
            raise ValueError("Invalid Zstd block header")
        position += 1 if kind == 1 else size
        if position > len(frame):
            raise ValueError("Truncated Zstd block")
        if header & 1:
            position += 4 if descriptor & 4 else 0
            if position != len(frame):
                raise ValueError("Unexpected or concatenated Zstd frame data")
            return


def _pvr_payload(info):
    payload = info["payload"]
    if info["compression"] == "none":
        return payload
    result = []
    for offset, packed, expected in info["entries"]:
        frame = payload[offset:offset + packed]
        try:
            if info["compression"] == "jlz4":
                from lz4.block import decompress

                decoded = decompress(frame, uncompressed_size=expected)
            else:
                legacy = frame[:4] == b"\x26\xb5\x2f\xfd"
                (_zstd06_frame_size if legacy else _modern_zstd_frame_size)(frame, expected)
                import zstd

                if legacy and not zstd.ZSTD_legacy_support():
                    raise ValueError("Zstd v0.6 support is missing; install zstd from source with ZSTD_LEGACY=1 or use the bundled backend")
                decoded = zstd.decompress(frame)
        except ImportError as error:
            raise ValueError("Compressed texture preview requires the lz4 and legacy-enabled zstd render dependencies") from error
        except Exception as error:
            if isinstance(error, ValueError):
                raise
            raise ValueError(f"Invalid {info['compression']} PVR mip: {error}") from error
        if len(decoded) != expected:
            raise ValueError("Decompressed PVR mip has an unexpected size")
        result.append(decoded)
    return b"".join(result)


def _dimensions(w, h):
    if not 0 < w <= 16384 or not 0 < h <= 16384 or w * h > 32_000_000:
        raise ValueError("Texture dimensions exceed preview limits")


def _etc2_only(block):
    """Recognize ETC2 T/H/planar modes by ETC1 differential overflow."""
    if not block[3] & 2:
        return False
    for channel in block[:3]:
        delta = channel & 7
        if delta & 4:
            delta -= 8
        if not 0 <= (channel >> 3) + delta <= 31:
            return True
    return False


def _kty_blocks(payload, w, h):
    """Select the GLES3 block from each KTY ETC2/ETC1 pair.

    LoadKTX consumes 16 bytes for an ETC2-only block: the ETC2 block first,
    followed by an ETC1 substitute for GLES2. Shared ETC1/ETC2 blocks use 8.
    Small mip levels bypass this conversion in the engine.
    """
    expected = ((w + 3) // 4) * ((h + 3) // 4) * 8
    if w < 4 or h < 4:
        if len(payload) != expected:
            raise ValueError("Invalid KTY mip size")
        return payload
    if not expected <= len(payload) <= expected * 2 or len(payload) % 8:
        raise ValueError("Invalid KTY block stream size")
    pixels = bytearray(expected)
    pos = 0
    for output in range(0, expected, 8):
        block = payload[pos : pos + 8]
        if len(block) != 8:
            raise ValueError("Truncated KTY block stream")
        pixels[output : output + 8] = block
        pos += 16 if _etc2_only(block) else 8
        if pos > len(payload):
            raise ValueError("Missing KTY ETC1 substitute block")
    if pos != len(payload):
        raise ValueError("Unexpected KTY blocks after mip")
    return bytes(pixels)


def _compressed_size(kind, two_bit, w, h):
    if kind == "pvrtc":
        return max(16, w) * max(8, h) // 4 if two_bit else max(8, w) * max(8, h) // 2
    if kind == "astc":
        bw, bh = two_bit
        return ((w + bw - 1) // bw) * ((h + bh - 1) // bh) * 16
    return ((w + 3) // 4) * ((h + 3) // 4) * (16 if kind in ("etc2a8", "bc3") else 8)


def decode(raw):
    from PIL import Image

    if len(raw) > 256 * 1024 * 1024:
        raise ValueError("Texture exceeds size limit")
    compressed = None
    if raw[:4] == b"PVR\x03":
        if len(raw) < 52:
            raise ValueError("Truncated PVR header")
        info = pvr_layout(raw)
        fmt, w, h = info["pixel_format"], info["width"], info["height"]
        payload = _pvr_payload(info)
        compressed = {
            0: ("pvrtc", True),
            1: ("pvrtc", True),
            2: ("pvrtc", False),
            3: ("pvrtc", False),
            6: ("etc1", False),
            7: ("bc1", False),
            11: ("bc3", False),
            22: ("etc2", False),
            23: ("etc2a8", False),
            24: ("etc2a1", False),
        }.get(fmt)
        if 27 <= fmt < 27 + len(ASTC_BLOCKS):
            compressed = ("astc", ASTC_BLOCKS[fmt - 27])
        if compressed is None:
            channels = (
                (fmt & 0xFFFFFFFF)
                .to_bytes(4, "little")
                .rstrip(b"\x00")
                .decode("ascii", errors="replace")
            )
            bits = (fmt >> 32).to_bytes(4, "little")[: len(channels)]
            if channels not in ("rgba", "bgra", "rgb") or any(b != 8 for b in bits):
                raise ValueError("Unsupported uncompressed PVR layout")
            _dimensions(w, h)
            size = w * h * len(channels)
            if len(payload) < size:
                raise ValueError("Truncated texture pixels")
            return Image.frombytes(
                "RGBA" if len(channels) == 4 else "RGB",
                (w, h),
                payload[:size],
                "raw",
                channels.upper(),
            ).convert("RGBA")
    elif raw[:12] in (b"\xabKTY 11\xbb\r\n\x1a\n", b"\xabKTX 11\xbb\r\n\x1a\n"):
        if len(raw) < 68:
            raise ValueError("Truncated KTY header")
        (
            endian,
            gltype,
            typesize,
            glformat,
            fmt,
            _,
            w,
            h,
            depth,
            arrays,
            faces,
            mips,
            metadata,
        ) = struct.unpack_from("<13I", raw, 12)
        if (
            endian != 0x04030201
            or gltype != 0
            or glformat != 0
            or typesize != 1
            or arrays
            or depth
            or faces != 1
        ):
            raise ValueError("Unsupported KTY layout")
        _dimensions(w, h)
        compressed = {
            0x8D64: ("etc1", False),
            0x9274: ("etc2", False),
            0x8C00: ("pvrtc", False),
            0x8C02: ("pvrtc", False),
            0x8C01: ("pvrtc", True),
            0x8C03: ("pvrtc", True),
        }.get(fmt)
        if compressed is None:
            raise ValueError("Unsupported texture compression")
        if max(1, mips) > max(w, h).bit_length():
            raise ValueError("Invalid KTY mip count")
        pos = 64 + metadata
        kind, two_bit = compressed
        hybrid = raw[:4] == b"\xabKTY" and fmt == 0x8D64
        for level in range(max(1, mips)):
            if pos + 4 > len(raw):
                raise ValueError("Missing KTY mip size")
            size = struct.unpack_from("<I", raw, pos)[0]
            start = pos + 4
            end = start + size
            if end > len(raw):
                raise ValueError("Truncated KTY mip")
            level_w, level_h = max(1, w >> level), max(1, h >> level)
            level_data = raw[start:end]
            if hybrid:
                level_data = _kty_blocks(level_data, level_w, level_h)
            elif size != _compressed_size(kind, two_bit, level_w, level_h):
                raise ValueError("Invalid KTX mip size")
            if level == 0:
                payload = level_data
            pos = end + (-size % 4)
        if hybrid:
            compressed = ("etc2", False)
    elif len(raw) >= 16 and struct.unpack_from("<I", raw)[0] == 666:
        _, w, h, channels = struct.unpack_from("<4I", raw)
        _dimensions(w, h)
        if channels not in (1, 3, 4) or len(raw) - 16 != w * h * channels:
            raise ValueError("Invalid raw RGB texture payload")
        return Image.frombytes(
            {1: "L", 3: "RGB", 4: "RGBA"}[channels], (w, h), raw[16:]
        ).convert("RGBA")
    else:
        with Image.open(BytesIO(raw)) as im:
            _dimensions(*im.size)
            return im.convert("RGBA")
    _dimensions(w, h)
    if compressed is None:
        raise ValueError("Unsupported texture compression")
    import texture2ddecoder

    kind, two_bit = compressed
    if kind == "pvrtc" and (w & (w - 1) or h & (h - 1)):
        raise ValueError("PVRTC dimensions must be powers of two")
    expected = _compressed_size(kind, two_bit, w, h)
    if len(payload) < expected:
        raise ValueError("Truncated compressed texture")
    if kind == "pvrtc":
        pixels = texture2ddecoder.decode_pvrtc(payload[:expected], w, h, two_bit)
    elif kind == "astc":
        pixels = texture2ddecoder.decode_astc(payload[:expected], w, h, *two_bit)
    else:
        decoder = getattr(texture2ddecoder, "decode_" + kind)
        pixels = decoder(payload[:expected], w, h)
    if len(pixels) != w * h * 4:
        raise ValueError("Texture decoder returned an unexpected pixel count")
    return Image.frombytes("RGBA", (w, h), pixels, "raw", "BGRA")


def read(path: Path, alpha=True, *, mask_path=None):
    image = decode(path.read_bytes())
    alpha_path = mask_path if mask_path is not None else path.with_suffix(path.suffix + "__alpha")
    if alpha and alpha_path.is_file():
        mask = decode(alpha_path.read_bytes())
        if mask.size != image.size:
            raise ValueError("Alpha texture dimensions do not match")
        image.putalpha(mask.getchannel("R"))
    return image
