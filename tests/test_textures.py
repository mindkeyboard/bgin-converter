"""Authored texture containers and asymmetric block/row fixtures; no game assets."""

import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bgin_json.render import textures

try:
    import texture2ddecoder
    from PIL import Image
except ImportError:
    Image = None


def pvr(payload, width=4, height=4, fmt=6, metadata=b"", mips=1):
    return (
        struct.pack(
            "<IIQ9I",
            0x03525650,
            0,
            fmt,
            0,
            0,
            height,
            width,
            1,
            1,
            1,
            mips,
            len(metadata),
        )
        + metadata
        + payload
    )


def ktx(levels, width=4, height=4, fmt=0x8D64, hybrid=True, metadata=b""):
    magic = b"\xabKTY 11\xbb\r\n\x1a\n" if hybrid else b"\xabKTX 11\xbb\r\n\x1a\n"
    header = struct.pack(
        "<13I",
        0x04030201,
        0,
        1,
        0,
        fmt,
        0x1907,
        width,
        height,
        0,
        0,
        1,
        len(levels),
        len(metadata),
    )
    return (
        magic
        + header
        + metadata
        + b"".join(
            struct.pack("<I", len(level)) + level + b"\0" * (-len(level) % 4)
            for level in levels
        )
    )


# ETC1 individual mode with different left/right colours and asymmetric selectors.
SHARED = bytes.fromhex("e12468003c3ca5a5")
OTHER = bytes.fromhex("2b96350069966996")
# Differential overflow in R, G and B identifies ETC2 T, H and planar modes.
T_BLOCK = bytes.fromhex("0488a50269c3f00f")
H_BLOCK = bytes.fromhex("8804a5025ac30ff0")
PLANAR_BLOCK = bytes.fromhex("88990402f00f5aa5")


@unittest.skipUnless(Image, "Texture tests require the render extra")
class TextureTests(unittest.TestCase):
    def test_etc1_colour_selectors_and_orientation_from_spec(self):
        image = textures.decode(pvr(SHARED))
        # Selector bits are x*4+y, with the high selector bit in bits 16..31.
        self.assertEqual(image.getpixel((0, 0)), (246, 42, 110, 255))
        self.assertEqual(image.getpixel((0, 3)), (236, 32, 100, 255))
        self.assertEqual(image.getpixel((3, 0)), (15, 66, 134, 255))
        self.assertEqual(image.getpixel((3, 3)), (25, 76, 144, 255))

    def test_kty_mixed_etc2_and_shared_blocks_select_one_block_per_cell(self):
        stream = T_BLOCK + OTHER + SHARED + H_BLOCK + OTHER + PLANAR_BLOCK + SHARED
        selected = T_BLOCK + SHARED + H_BLOCK + PLANAR_BLOCK
        with patch.object(
            texture2ddecoder, "decode_etc2", wraps=texture2ddecoder.decode_etc2
        ) as decoder:
            actual = textures.decode(ktx([stream], 8, 8))
        decoder.assert_called_once_with(selected, 8, 8)
        # Compare with a standard ETC2 KTX containing the selected 8-byte blocks.
        reference = textures.decode(ktx([selected], 8, 8, fmt=0x9274, hybrid=False))
        self.assertEqual(actual.tobytes(), reference.tobytes())
        self.assertNotEqual(actual.getpixel((0, 0)), actual.getpixel((7, 7)))

    def test_kty_shared_blocks_preserve_etc1_pixels_and_block_rows(self):
        stream = SHARED + OTHER + OTHER + SHARED
        actual = textures.decode(ktx([stream], 8, 8))
        reference = textures.decode(pvr(stream, 8, 8))
        self.assertEqual(actual.tobytes(), reference.tobytes())
        self.assertEqual(actual.getpixel((0, 0)), reference.getpixel((4, 4)))
        self.assertNotEqual(actual.getpixel((0, 0)), actual.getpixel((4, 0)))

    def test_standard_ktx_etc1_does_not_unpack_kty_pairs(self):
        stream = T_BLOCK + OTHER
        with patch.object(
            texture2ddecoder, "decode_etc1", wraps=texture2ddecoder.decode_etc1
        ) as decoder:
            textures.decode(ktx([stream], 8, 4, hybrid=False))
        decoder.assert_called_once_with(stream, 8, 4)

    def test_standard_etc2_accepts_single_special_block_without_substitute(self):
        for block in (T_BLOCK, H_BLOCK, PLANAR_BLOCK):
            with self.subTest(block=block.hex()):
                image = textures.decode(ktx([block], fmt=0x9274, hybrid=False))
                self.assertEqual(image.size, (4, 4))

    def test_kty_all_declared_mips_are_validated_and_base_is_returned(self):
        levels = [SHARED * 4, H_BLOCK + OTHER, SHARED, OTHER]
        image = textures.decode(ktx(levels, 8, 8, metadata=b"\0" * 4))
        self.assertEqual(
            image.tobytes(), textures.decode(pvr(SHARED * 4, 8, 8)).tobytes()
        )
        with self.assertRaisesRegex(ValueError, "Truncated KTY mip"):
            textures.decode(ktx(levels, 8, 8)[:-1])
        # The engine does not unpack special pairs for dimensions below 4.
        with self.assertRaisesRegex(ValueError, "Invalid KTY mip size"):
            textures.decode(ktx([H_BLOCK + OTHER], 2, 2))

    def test_truncated_or_overlong_kty_block_streams_are_rejected(self):
        for stream in (T_BLOCK, SHARED + OTHER, T_BLOCK + OTHER + SHARED, b"\0" * 7):
            with self.subTest(length=len(stream)), self.assertRaises(ValueError):
                textures.decode(ktx([stream]))
        with self.assertRaisesRegex(ValueError, "Truncated KTY mip"):
            textures.decode(ktx([T_BLOCK + OTHER])[:-1])

    def test_kty_etc2_mode_detection_requires_differential_flag(self):
        for block in (T_BLOCK, H_BLOCK, PLANAR_BLOCK):
            self.assertTrue(textures._etc2_only(block))
            individual = block[:3] + bytes([block[3] & ~2]) + block[4:]
            self.assertFalse(textures._etc2_only(individual))
        self.assertFalse(textures._etc2_only(bytes.fromhex("8181810200000000")))

    def test_pvr_metadata_mips_and_truncation(self):
        encoded = pvr(SHARED + OTHER, metadata=b"test", mips=2)
        self.assertEqual(
            textures.decode(encoded).tobytes(), textures.decode(pvr(SHARED)).tobytes()
        )
        with self.assertRaisesRegex(ValueError, "Truncated PVR metadata"):
            textures.decode(pvr(b"", metadata=b"1234")[:-1])
        with self.assertRaisesRegex(ValueError, "Truncated compressed texture"):
            textures.decode(pvr(SHARED[:-1]))

    def test_uncompressed_pvr_channel_layouts(self):
        for channels, pixels in (
            ("rgba", b"\x11\x22\x33\x44"),
            ("bgra", b"\x33\x22\x11\x44"),
            ("rgb", b"\x11\x22\x33"),
        ):
            with self.subTest(channels=channels):
                fmt = int.from_bytes(channels.encode().ljust(4, b"\0"), "little")
                fmt |= int.from_bytes(bytes([8]) * len(channels), "little") << 32
                image = textures.decode(pvr(pixels, 1, 1, fmt))
                self.assertEqual(
                    image.getpixel((0, 0)),
                    (17, 34, 51, 68 if len(channels) == 4 else 255),
                )

    def test_pvrtc_header_variant_and_minimum_block_footprint(self):
        for fmt, two_bit in ((0, True), (1, True), (2, False), (3, False)):
            with self.subTest(fmt=fmt):
                payload = b"\0" * 32
                with patch.object(
                    texture2ddecoder,
                    "decode_pvrtc",
                    wraps=texture2ddecoder.decode_pvrtc,
                ) as decoder:
                    image = textures.decode(pvr(payload, 8, 4, fmt))
                decoder.assert_called_once_with(payload, 8, 4, two_bit)
                self.assertEqual(image.size, (8, 4))
                with self.assertRaisesRegex(ValueError, "Truncated compressed texture"):
                    textures.decode(pvr(payload[:-1], 8, 4, fmt))
        with self.assertRaisesRegex(ValueError, "powers of two"):
            textures.decode(pvr(b"\0" * 32, 7, 4, 2))

    def test_standard_ktx_pvrtc_format_mapping_preserves_blocks(self):
        for fmt, two_bit in (
            (0x8C00, False),
            (0x8C02, False),
            (0x8C01, True),
            (0x8C03, True),
        ):
            with self.subTest(fmt=fmt):
                payload = b"\0" * 32
                with patch.object(
                    texture2ddecoder,
                    "decode_pvrtc",
                    wraps=texture2ddecoder.decode_pvrtc,
                ) as decoder:
                    image = textures.decode(ktx([payload], 8, 4, fmt, hybrid=False))
                decoder.assert_called_once_with(payload, 8, 4, two_bit)
                self.assertEqual(image.size, (8, 4))

    def test_raw_rgb_and_true_tga_rows_are_normalized(self):
        rgb = bytes.fromhex("ff0000 00ff00 0000ff ffffff")
        raw = struct.pack("<4I", 666, 2, 2, 3) + rgb
        expected = textures.decode(raw)
        # TGA bottom-left rows: blue, white, red, green in BGR channel order.
        tga = struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, 2, 2, 24, 0)
        image = textures.decode(tga + bytes.fromhex("ff0000 ffffff 0000ff 00ff00"))
        self.assertEqual(image.tobytes(), expected.tobytes())
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 255))
        self.assertEqual(image.getpixel((0, 1)), (0, 0, 255, 255))
        with self.assertRaisesRegex(ValueError, "Invalid raw RGB texture payload"):
            textures.decode(raw[:-1])

    def test_raw_gray_rgba_and_png_keep_alpha_and_order(self):
        gray = textures.decode(struct.pack("<4I", 666, 2, 1, 1) + b"\x11\xcc")
        self.assertEqual(gray.tobytes(), bytes.fromhex("111111ff ccccccff"))
        rgba = bytes.fromhex("11223344 aabbccdd")
        image = textures.decode(struct.pack("<4I", 666, 2, 1, 4) + rgba)
        self.assertEqual(image.tobytes(), rgba)
        from io import BytesIO

        stream = BytesIO()
        image.save(stream, format="PNG")
        self.assertEqual(textures.decode(stream.getvalue()).tobytes(), rgba)

    def test_separate_alpha_uses_red_channel_without_flipping(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "authored.tga"
            path.write_bytes(
                struct.pack("<4I", 666, 2, 1, 3) + bytes.fromhex("ff0000 0000ff")
            )
            path.with_suffix(".tga__alpha").write_bytes(
                struct.pack("<4I", 666, 2, 1, 3) + bytes.fromhex("110000 cc0000")
            )
            image = textures.read(path)
            self.assertEqual(image.tobytes(), bytes.fromhex("ff000011 0000ffcc"))
            self.assertEqual(
                textures.read(path, False).getchannel("A").tobytes(), b"\xff\xff"
            )

    def test_invalid_headers_dimensions_and_declared_sizes_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "dimensions"):
            textures.decode(pvr(SHARED, 0, 4))
        with self.assertRaisesRegex(ValueError, "Truncated PVR header"):
            textures.decode(b"PVR\x03")
        with self.assertRaisesRegex(ValueError, "Invalid KTX mip size"):
            textures.decode(ktx([SHARED * 2], hybrid=False))
        with self.assertRaisesRegex(ValueError, "Invalid KTY mip count"):
            textures.decode(ktx([SHARED] * 4))


if __name__ == "__main__":
    unittest.main()
