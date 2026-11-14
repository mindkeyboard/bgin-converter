"""Explicit offline texture conversion, separate from every BGIN write path."""

import argparse
import json
import os
from pathlib import Path
import struct

from .publication import atomic_write
from .profiles import normalize_format
from .resource_formats import pvr_layout, pvr_level_size, require_texture_target
from .render.textures import _pvr_payload, decode

RGBA8 = 0x0808080861626772


def convert_texture(raw, *, method, target_format):
    target_format = normalize_format(target_format)
    info = pvr_layout(raw)
    payload = _pvr_payload(info)
    expected_bytes = sum(pvr_level_size(info["pixel_format"], max(1, info["width"] >> level), max(1, info["height"] >> level)) for level in range(info["mip_count"]))
    if len(payload) != expected_bytes:
        raise ValueError("Invalid PVR mip chain length")
    header = bytearray(raw[:52])
    if method == "unwrap":
        # The recognized jetc envelope occupies the entire metadata block.
        # Other metadata is retained verbatim when no envelope is present.
        if info["compression"] == "none":
            result = raw
        else:
            struct.pack_into("<I", header, 48, 0)
            result = bytes(header) + payload
    elif method == "rgba8":
        if info["compression"] == "none" and struct.unpack_from("<I", raw, 48)[0]:
            raise ValueError("Unknown PVR metadata cannot be discarded during RGBA8 conversion")
        chunks, offset = [], 0
        for level in range(info["mip_count"]):
            width, height = max(1, info["width"] >> level), max(1, info["height"] >> level)
            size = pvr_level_size(info["pixel_format"], width, height)
            single = bytearray(header)
            struct.pack_into("<II", single, 24, height, width)
            struct.pack_into("<II", single, 44, 1, 0)
            image = decode(bytes(single) + payload[offset:offset + size])
            chunks.append(image.tobytes())
            offset += size
        if offset != len(payload):
            raise ValueError("Unexpected bytes after PVR mip chain")
        struct.pack_into("<Q", header, 8, RGBA8)
        struct.pack_into("<I", header, 20, 0)  # Unsigned byte normalized.
        struct.pack_into("<I", header, 48, 0)
        result = bytes(header) + b"".join(chunks)
        # Independently inspect the output's complete mip chain boundaries.
        output = pvr_layout(result)
        expected = sum(max(1, output["width"] >> level) * max(1, output["height"] >> level) * 4 for level in range(output["mip_count"]))
        if len(output["payload"]) != expected:
            raise ValueError("Converted RGBA8 mip chain length is invalid")
    else:
        raise ValueError("Texture method must be unwrap or rgba8")
    require_texture_target(result, target_format)
    return result


def convert_texture_file(source, destination, *, method, target_format, overwrite=False):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or (destination.exists() and os.path.samefile(source, destination)):
        raise ValueError("Texture conversion requires a separate destination")
    raw = source.read_bytes()
    result = convert_texture(raw, method=method, target_format=target_format)
    return {**atomic_write(destination, result, overwrite=overwrite), "source_bytes": len(raw),
            "method": method, "target_format": normalize_format(target_format), "runtime_verified": False,
            "notice": "Separate texture conversion; game loading is unverified. Convert any separate alpha texture explicitly as well."}


def main():
    parser = argparse.ArgumentParser(description="Convert one PVR texture into a separate file; never runs during BGIN saving")
    parser.add_argument("input")
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--method", choices=("unwrap", "rgba8"), required=True)
    parser.add_argument("--target-format", default="a8-1.6.0")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(convert_texture_file(args.input, args.output, method=args.method, target_format=args.target_format, overwrite=args.force)))
        return 0
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
