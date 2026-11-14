"""Hand-built independent fixtures and optional retail corpus verification."""
import os
from pathlib import Path
import struct
import unittest

from bgin_core import (BginAddress, BginError, BginSession, decode_document,
                       encode_document, jet_hash)


def text(value):
    raw = value.encode("utf-8")
    return struct.pack("<H", len(raw)) + raw


def fixture(modern=False, second_table=False):
    # Neither fixture is produced by the codec under test.
    properties = struct.pack("<H", 1)
    properties += struct.pack("<IH", 0x12345678, 2)
    properties += (b"\x01" if modern else b"\x01\x00") + struct.pack("<d", 2.5)
    if modern:
        properties += b"\x01" + struct.pack("<I", 0xCF1A96C9) + b"\x01" + struct.pack("<d", 3.0)
    body = text("root")
    if not modern:
        body += struct.pack("<5f", 0, 0, 0, 1, 1)
    body += properties + b"\0\0"
    node = struct.pack("<II", 0x8706BEAF, len(body)) + body
    header = struct.pack("<II", 0xC1AAA, 0x9456A530) + text("Test")
    count = 2 if second_table else 1
    offset = len(header) + 4 + 4 + count * 8 + 2
    header += struct.pack("<IHIIH", 4 + count * 8, 1, jet_hash("root"), offset,
                          1 if second_table else 0)
    if second_table:
        header += struct.pack("<II", 0x99999999, offset + len(node))
    header += struct.pack("<H", count)
    return header + node + (b"special" if second_table else b"")


def animation_fixture():
    def node(type_hash, payload):
        return struct.pack("<II", type_hash, len(payload)) + payload
    def generic(type_hash, name, children=b"", child_count=0):
        return node(type_hash, text(name) + struct.pack("<HH", 0, child_count) + children)
    frame = struct.pack("<IHHIBB4f", 3, 0x20, 1, 0xB4A006C2, 2, 4, 1, 0.5, 0, 1)
    movie_data = text("pulse") + struct.pack("<H", 1)
    movie_data += generic(0xBE17FA7A, "metadata")
    movie_data += struct.pack("<IIIBI", 30, 0, 3333, 0, 1)
    movie_data += b"\x65" + generic(0xEB9A8C92, "track") + frame + struct.pack("<I", 0xFFFFFFFF)
    root = generic(0x3BA2E9E2, "atlas", node(0x6E739C13, movie_data), 1)
    header = struct.pack("<II", 0xC1AAA, 0x9456A530) + text("Sprites")
    offset = len(header) + 18
    header += struct.pack("<IHIIHH", 12, 1, jet_hash("atlas"), offset, 0, 1)
    return header + root


class IndependentProfileTests(unittest.TestCase):
    def test_profiles_detect_and_force_rebuild(self):
        for modern, profile in ((False, "a8-3.7.0"), (True, "a8-5.8.0")):
            with self.subTest(profile=profile):
                raw = fixture(modern)
                doc = decode_document(raw)
                self.assertEqual(doc.wire_format, profile)
                # Force reconstruction cannot use retained source bytes.
                doc.source_bytes = b"invalid"
                for _, _, node in doc.walk():
                    node.source_bytes = b"invalid"
                    for prop in node.properties:
                        prop.source_bytes = b"invalid"
                self.assertEqual(encode_document(doc, force=True), raw)

    def test_transaction_edit_preserves_variants_and_undo(self):
        raw = fixture(True)
        session = BginSession(raw)
        self.assertTrue(session.set_property(BginAddress(0), 0x12345678, 9.0))
        doc = decode_document(session.data)
        prop = doc.screens[0].node.properties[0]
        self.assertEqual(prop.value, 9.0)
        self.assertEqual([(v.name_hash, v.value) for v in prop.variants], [(0xCF1A96C9, 3.0)])
        self.assertEqual(encode_document(doc, force=True), session.data)
        self.assertTrue(session.undo())
        self.assertEqual(session.data, raw)
        self.assertTrue(session.redo())
        self.assertEqual(session.document.wire_format, "a8-5.8.0")

    def test_special_records_and_profile_mismatch_fail_clearly(self):
        with self.assertRaisesRegex(BginError, "second-table"):
            decode_document(fixture(True, True))
        with self.assertRaises(BginError):
            decode_document(fixture(True), wire_format="a8-3.7.0")
        with self.assertRaises(BginError):
            decode_document(fixture(False), wire_format="a8-5.8.0")

    def test_inconsistent_directory_fails(self):
        raw = bytearray(fixture(False))
        header_end = len(struct.pack("<II", 0, 0) + text("Test")) + 4 + 4 + 8 + 2
        struct.pack_into("<H", raw, header_end - 2, 3)
        with self.assertRaisesRegex(BginError, "directory count"):
            decode_document(bytes(raw))

    def test_down_conversion_cannot_discard_new_fields(self):
        doc = decode_document(fixture(True))
        doc.wire_format = "a8-3.7.0"
        with self.assertRaises(BginError):
            encode_document(doc, force=True)
        doc.wire_format = "a8-1.6.0"
        with self.assertRaises(BginError):
            encode_document(doc, force=True)

    def test_modern_animation_channels_rebuild_from_fields(self):
        raw = animation_fixture()
        doc = decode_document(raw)
        self.assertEqual(doc.wire_format, "a8-5.8.0")
        frame = doc.screens[0].node.children[0].sprite_movie.tracks[0].keyframes[0]
        self.assertEqual(frame.color_channels[0].interpolation, 2)
        self.assertEqual(frame.color_channels[0].values, [1, 0.5, 0, 1])
        frame.source_bytes = b""
        self.assertEqual(encode_document(doc, force=True), raw)
        frame.color_channels[0].values[1] = 0.75
        changed = decode_document(encode_document(doc, force=True))
        actual = changed.screens[0].node.children[0].sprite_movie.tracks[0].keyframes[0]
        self.assertEqual(actual.color_channels[0].values[1], 0.75)
        doc.wire_format = "a8-1.6.0"
        with self.assertRaises(BginError):
            encode_document(doc, force=True)


@unittest.skipUnless(os.environ.get("BGIN_NEW_CORPUS"), "External new-profile corpus not configured")
class IndependentRetailProfileTests(unittest.TestCase):
    def test_every_supported_file_rebuilds_byte_exactly(self):
        root = Path(os.environ["BGIN_NEW_CORPUS"])
        for corpus, profile, rejected in (
            (root / "370/gui", "a8-3.7.0", {"sequences.bgin", "prokits_menu.bgin", "options_menu.bgin", "car_poster_images.bgin"}),
            (root / "580/extracted/assets/releaseminigame", "a8-5.8.0", {"sequences.bgin", "download_minigame.bgin", "end_race_screens.bgin"}),
        ):
            files = sorted(corpus.glob("*.bgin"))
            self.assertTrue(files)
            for path in files:
                with self.subTest(profile=profile, file=path.name):
                    raw = path.read_bytes()
                    if path.name in rejected:
                        with self.assertRaises(BginError):
                            decode_document(raw)
                        continue
                    doc = decode_document(raw)
                    self.assertEqual(doc.wire_format, profile)
                    self.assertEqual(encode_document(doc, force=True), raw)


if __name__ == "__main__":
    unittest.main()
