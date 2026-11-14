"""Independent modern wire fixtures and loss-aware profile conversion."""
import copy
import os
from pathlib import Path
import struct
import unittest

from bgin_json import BginError, encode, parse
from bgin_json.file_conversion import verified_binary
from bgin_json.writer import convert_document
from bgin_json.parser import jet_hash
from fixtures import text, u16, u32


def wire(profile, unknown=False):
    name = "#12345678" if unknown else "StackContainer"
    key = 0x89ABCDEF if unknown else jet_hash("Size")
    property_data = u32(key) + u16(2)
    property_data += (b"\x01" if profile == "a8-5.8.0" else u16(1))
    property_data += struct.pack("<d", 3.5)
    if profile == "a8-5.8.0":
        property_data += b"\x01" + u32(0xCF1A96C9) + b"\x01" + struct.pack("<d", 7.)
    body = text("root")
    if profile != "a8-5.8.0":
        body += struct.pack("<5f", 0, 0, 0, 1, 1)
    body += u16(1) + property_data + u16(0)
    root = u32(0x12345678 if unknown else jet_hash(name)) + u32(len(body)) + body
    prefix = u32(0xC1AAA) + u32(0x9456A530) + text("Fixture") + u32(12) + u16(1)
    return prefix + u32(jet_hash("root")) + u32(len(prefix) + 12) + u16(0) + u16(1) + root


class ProfileTests(unittest.TestCase):
    def test_wire_unknown_identifiers_and_variants_are_lossless(self):
        for profile in ("a8-3.7.0", "a8-5.8.0"):
            for unknown in (False, True):
                with self.subTest(profile=profile, unknown=unknown):
                    raw = wire(profile, unknown)
                    doc = parse(raw)
                    self.assertEqual(doc["format"], profile)
                    self.assertEqual(verified_binary(doc), raw)
                    if unknown:
                        self.assertEqual(doc["screens"][0]["type"], "#12345678")
                    doc["screens"][0]["name"] += "_edited"
                    edited = verified_binary(doc)
                    self.assertEqual(parse(edited)["screens"][0]["name"], "root_edited")

    def test_profiles_are_explicit_and_earlier_aliases_still_compile(self):
        for alias, canonical in (("legacy", "a8-0.0.2"), ("hashed", "a8-1.6.0"),
                                 ("a8-3.7.0", "a8-3.7.0"), ("a8-5.8.0", "a8-5.8.0")):
            doc = {"name": "Example", "format": alias,
                   "screens": [{"type": "StackContainer", "name": "root"}]}
            self.assertEqual(parse(verified_binary(doc))["format"], canonical)

    def test_unknown_ids_and_variants_cannot_be_silently_downgraded(self):
        doc = parse(wire("a8-5.8.0", True))
        before = copy.deepcopy(doc)
        for target in ("a8-0.0.2", "a8-1.6.0", "a8-3.7.0"):
            with self.assertRaises(BginError):
                convert_document(doc, target)
        self.assertEqual(doc, before)

    def test_nonidentity_transform_is_not_dropped(self):
        doc = {"name": "Example", "screens": [{"type": "StackContainer", "name": "root",
               "transform": [1, 2, 0, 1, 1]}]}
        with self.assertRaisesRegex(BginError, "Nonidentity transform"):
            convert_document(doc, "a8-5.8.0")

    def test_known_ordinary_values_can_be_converted(self):
        doc = {"name": "Example", "screens": [{"type": "StackContainer", "name": "root",
               "properties": {"Size": [640, 360]}}]}
        for target in ("a8-0.0.2", "a8-1.6.0", "a8-3.7.0", "a8-5.8.0"):
            converted = convert_document(doc, target)
            self.assertEqual(parse(verified_binary(converted))["screens"], doc["screens"])

    def test_new_headers_with_special_table_refuse_clearly(self):
        raw = bytearray(wire("a8-3.7.0"))
        end_namespace = 10 + len("Fixture")
        struct.pack_into("<I", raw, end_namespace, 20)
        struct.pack_into("<H", raw, end_namespace + 14, 1)
        with self.assertRaisesRegex(BginError, "second directory table"):
            parse(bytes(raw))

    def test_modern_color_animation_edits_are_independently_verified(self):
        from test_independent_profiles import animation_fixture
        raw = animation_fixture()
        doc = parse(raw)
        self.assertEqual(verified_binary(doc), raw)
        frame = doc["screens"][0]["children"][0]["tracks"][0]["keyframes"][0]
        frame["color_channels"][0]["value"][1] = 0.75
        output = verified_binary(doc)
        actual = parse(output)["screens"][0]["children"][0]["tracks"][0]["keyframes"][0]
        self.assertEqual(actual["color_channels"][0]["value"][1], 0.75)
        with self.assertRaisesRegex(BginError, "Color channels"):
            convert_document(doc, "a8-3.7.0")

    def test_ambiguous_profile_requires_explicit_selection(self):
        doc = {"name": "Sprites", "format": "a8-5.8.0", "screens": [
            {"type": "Movie", "name": "animation"}]}
        raw = encode(doc)
        with self.assertRaisesRegex(BginError, "Ambiguous"):
            parse(raw)
        self.assertEqual(parse(raw, format="a8-5.8.0")["format"], "a8-5.8.0")


@unittest.skipUnless(os.environ.get("BGIN_NEW_CORPUS"), "External modern corpora not configured")
class ModernCorpusTests(unittest.TestCase):
    def test_supported_files_are_independent_and_byte_exact(self):
        root = Path(os.environ["BGIN_NEW_CORPUS"])
        for folder, expected in (("370/gui", 70), ("580/extracted/assets/releaseminigame", 10)):
            success = 0
            for path in sorted((root / folder).glob("*.bgin")):
                try:
                    document = parse(path.read_bytes())
                except BginError:
                    continue
                with self.subTest(file=str(path.relative_to(root))):
                    self.assertEqual(verified_binary(document), path.read_bytes())
                    document["screens"][0]["name"] += "_edited"
                    output = verified_binary(document)
                    self.assertEqual(parse(output)["screens"][0]["name"], document["screens"][0]["name"])
                    success += 1
                    print(f"Verified profile and edit: {path.name}", flush=True)
            self.assertEqual(success, expected)
