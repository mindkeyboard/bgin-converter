"""Inspect resource encoding separately from BGIN serialization and preview.

The compatibility result is deliberately conservative: successfully decoding an
image on the host does not establish that an older game can load its encoding.
"""

import struct


MAX_TEXTURE_BYTES = 256 * 1024 * 1024
ASTC_BLOCKS = ((4, 4), (5, 4), (5, 5), (6, 5), (6, 6), (8, 5), (8, 6),
               (8, 8), (10, 5), (10, 6), (10, 8), (10, 10), (12, 10), (12, 12))


def pvr_layout(raw):
    """Return validated PVR metadata, including observed Gameloft mip envelopes."""
    if len(raw) > MAX_TEXTURE_BYTES:
        raise ValueError("Texture exceeds size limit")
    if len(raw) < 52 or raw[:4] != b"PVR\x03":
        raise ValueError("Truncated or invalid PVR header")
    _, _, fmt, _, _, height, width, depth, surfaces, faces, mips, metadata = struct.unpack_from("<IIQ9I", raw)
    if not 0 < width <= 16384 or not 0 < height <= 16384 or width * height > 32_000_000:
        raise ValueError("Texture dimensions exceed preview limits")
    if depth not in (0, 1) or surfaces != 1 or faces != 1:
        raise ValueError("Only 2D single-surface PVR is supported")
    levels = max(1, mips)
    if levels > max(width, height).bit_length():
        raise ValueError("Invalid PVR mip count")
    if metadata > len(raw) - 52:
        raise ValueError("Truncated PVR metadata")
    meta, payload = raw[52:52 + metadata], raw[52 + metadata:]
    codec, entries = "none", []
    if meta[:4] in (b"jlz4", b"zstd") or meta[4:8] == b"jetc":
        if len(meta) < 12 or meta[:4] not in (b"jlz4", b"zstd") or meta[4:8] != b"jetc":
            raise ValueError("Unsupported PVR compression metadata")
        table_bytes = struct.unpack_from("<I", meta, 8)[0]
        if table_bytes != 12 * levels or len(meta) != 12 + table_bytes:
            raise ValueError("Invalid PVR compressed mip table")
        codec = meta[:4].decode("ascii")
        end, total = 0, 0
        for level in range(levels):
            offset, packed, unpacked = struct.unpack_from("<III", meta, 12 + 12 * level)
            if offset != end or not packed or not unpacked or packed > len(payload) - offset:
                raise ValueError("Invalid PVR compressed mip range")
            expected = pvr_level_size(fmt, max(1, width >> level), max(1, height >> level))
            if unpacked != expected:
                raise ValueError("PVR compressed mip output size disagrees with pixel format")
            total += unpacked
            if total > MAX_TEXTURE_BYTES:
                raise ValueError("PVR mip output exceeds size limit")
            end = offset + packed
            entries.append((offset, packed, unpacked))
        if end != len(payload):
            raise ValueError("Unexpected bytes after PVR compressed mips")
    return dict(width=width, height=height, pixel_format=fmt, mip_count=levels,
                compression=codec, entries=entries, payload=payload)


def pvr_level_size(fmt, width, height):
    if fmt in (0, 1):
        return max(16, width) * max(8, height) // 4
    if fmt in (2, 3):
        return max(8, width) * max(8, height) // 2
    if fmt in (6, 7, 22, 24):
        return ((width + 3) // 4) * ((height + 3) // 4) * 8
    if fmt in (11, 23):
        return ((width + 3) // 4) * ((height + 3) // 4) * 16
    if 27 <= fmt < 27 + len(ASTC_BLOCKS):
        bw, bh = ASTC_BLOCKS[fmt - 27]
        return ((width + bw - 1) // bw) * ((height + bh - 1) // bh) * 16
    channels = (fmt & 0xFFFFFFFF).to_bytes(4, "little").rstrip(b"\0")
    bits = (fmt >> 32).to_bytes(4, "little")[:len(channels)]
    if channels in (b"rgba", b"bgra", b"rgb") and all(bit == 8 for bit in bits):
        return width * height * len(channels)
    raise ValueError(f"Unsupported PVR pixel format {fmt}")


def inspect_texture(raw):
    """Identify container/GPU/envelope encodings without claiming runtime support."""
    if raw[:4] == b"PVR\x03":
        info = pvr_layout(raw)
        fmt = info["pixel_format"]
        gpu = {0: "PVRTC1-2", 1: "PVRTC1-2", 2: "PVRTC1-4", 3: "PVRTC1-4",
               6: "ETC1", 7: "BC1", 11: "BC3", 22: "ETC2-RGB", 23: "ETC2-RGBA",
               24: "ETC2-RGB-A1"}.get(fmt)
        if 27 <= fmt < 27 + len(ASTC_BLOCKS):
            gpu = "ASTC-%dx%d" % ASTC_BLOCKS[fmt - 27]
        if gpu is None:
            pvr_level_size(fmt, info["width"], info["height"])
            gpu = "RGB8" if len((fmt & 0xFFFFFFFF).to_bytes(4, "little").rstrip(b"\0")) == 3 else "RGBA8"
        return {k: v for k, v in info.items() if k not in ("entries", "payload")} | {"container": "pvr3", "gpu": gpu}
    if raw[:12] in (b"\xabKTX 11\xbb\r\n\x1a\n", b"\xabKTY 11\xbb\r\n\x1a\n"):
        if len(raw) < 64:
            raise ValueError("Truncated KTX header")
        fields = struct.unpack_from("<13I", raw, 12)
        endian, gltype, typesize, glformat, fmt, _, width, height, depth, arrays, faces, mips, metadata = fields
        if endian != 0x04030201 or gltype or glformat or typesize != 1 or depth or arrays or faces != 1:
            raise ValueError("Unsupported KTX layout")
        if not 0 < width <= 16384 or not 0 < height <= 16384 or width * height > 32_000_000:
            raise ValueError("Texture dimensions exceed preview limits")
        if metadata > len(raw) - 64 or max(1, mips) > max(width, height).bit_length():
            raise ValueError("Invalid KTX metadata or mip count")
        hybrid = raw[3:4] == b"Y"
        gpu = {0x8D64: "ETC1", 0x9274: "ETC2-RGB", 0x9278: "ETC2-RGBA",
               0x9276: "ETC2-RGB-A1", 0x8C00: "PVRTC1-4", 0x8C02: "PVRTC1-4",
               0x8C01: "PVRTC1-2", 0x8C03: "PVRTC1-2"}.get(fmt, "unknown")
        if hybrid and fmt == 0x8D64:
            gpu = "KTY-ETC2-ETC1-pairs"
        astc = fmt - 0x93B0 if 0x93B0 <= fmt <= 0x93BD else fmt - 0x93D0 if 0x93D0 <= fmt <= 0x93DD else None
        if astc is not None:
            gpu = "ASTC-%dx%d" % ASTC_BLOCKS[astc]
        return dict(container="kty" if hybrid else "ktx1", compression="none", gpu=gpu,
                    width=width, height=height, pixel_format=fmt, mip_count=max(1, mips))
    if len(raw) >= 16 and struct.unpack_from("<I", raw)[0] == 666:
        return {"container": "raw666", "compression": "none", "gpu": "raw"}
    return {"container": "other", "compression": "unknown", "gpu": "unknown"}


def check_texture_target(raw, target_format):
    """Return known incompatibilities; never use this as a runtime support proof."""
    profile = {"legacy": "a8-0.0.2", "hashed": "a8-1.6.0"}.get(target_format, target_format)
    if profile not in ("a8-0.0.2", "a8-1.6.0", "a8-3.7.0", "a8-5.8.0"):
        raise ValueError("Unknown resource target format")
    info = inspect_texture(raw)
    issues = []
    if profile in ("a8-0.0.2", "a8-1.6.0"):
        if info["compression"] in ("jlz4", "zstd"):
            issues.append(f"{profile} cannot use the newer {info['compression']}/jetc texture envelope; resource transcoding is required")
        if info["gpu"].startswith(("ASTC", "ETC2")):
            issues.append(f"{profile} has no confirmed support for {info['gpu']}; resource transcoding is required")
    elif profile == "a8-3.7.0" and info["gpu"].startswith("ASTC"):
        issues.append("ASTC support in the 3.7.0 target is unverified; choose a verified resource encoding")
    if profile in ("a8-0.0.2", "a8-1.6.0") and (info["container"] == "other" or info["gpu"] == "unknown"):
        issues.append(f"{profile} resource encoding is unknown; target compatibility must be verified before copying it")
    return dict(target_format=profile, texture=info, issues=issues,
                compatible=False if issues else None, runtime_verified=False)


def require_texture_target(raw, target_format):
    result = check_texture_target(raw, target_format)
    if result["issues"]:
        raise ValueError("; ".join(result["issues"]))
    return result
