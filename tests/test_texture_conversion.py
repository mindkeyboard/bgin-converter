"""Separate texture writes preserve mip data and fail before touching outputs."""

import struct
import tempfile
import unittest
from pathlib import Path

from bgin_json.texture_conversion import RGBA8, convert_texture, convert_texture_file
from bgin_json.render.textures import decode
from test_textures import pvr


class TextureConversionTests(unittest.TestCase):
    def test_rgba_preserves_all_mips_and_texture_pixels(self):
        # Different ETC2 block bytes in each mip make accidental mip reuse visible.
        payload = bytes.fromhex("1234567800000000") + bytes.fromhex("8765432100000000")
        original = pvr(payload, fmt=22, mips=2)
        converted = convert_texture(original, method="rgba8", target_format="a8-1.6.0")
        self.assertEqual(struct.unpack_from("<Q", converted, 8)[0], RGBA8)
        self.assertEqual(struct.unpack_from("<I", converted, 44)[0], 2)
        self.assertEqual(converted[52:52 + 64], decode(pvr(payload[:8], fmt=22)).tobytes())
        self.assertEqual(converted[52 + 64:], decode(pvr(payload[8:], fmt=22, width=2, height=2)).tobytes())

    def test_unwrap_preserves_gpu_blocks_and_rejects_incompatible_target(self):
        import lz4.block
        block = bytes.fromhex("1234567800000000")
        compressed = lz4.block.compress(block, store_size=False)
        metadata = b"jlz4jetc" + struct.pack("<4I", 12, 0, len(compressed), len(block))
        original = pvr(compressed, fmt=6, metadata=metadata)
        self.assertEqual(convert_texture(original, method="unwrap", target_format="a8-1.6.0"), pvr(block, fmt=6))
        with self.assertRaisesRegex(ValueError, "ETC2"):
            convert_texture(pvr(block, fmt=22), method="unwrap", target_format="a8-1.6.0")

    def test_failed_conversion_leaves_source_and_destination_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "source.tga", root / "target.tga"
            original = pvr(bytes(8), fmt=22)
            source.write_bytes(original)
            target.write_bytes(b"preserved")
            with self.assertRaises(ValueError):
                convert_texture_file(source, target, method="unwrap", target_format="a8-1.6.0", overwrite=True)
            self.assertEqual(target.read_bytes(), b"preserved")
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(list(root.glob("*.bak")), [])
            result = convert_texture_file(source, target, method="rgba8", target_format="a8-1.6.0", overwrite=True)
            self.assertEqual(Path(result["backup"]).read_bytes(), b"preserved")
            self.assertFalse(result["runtime_verified"])
