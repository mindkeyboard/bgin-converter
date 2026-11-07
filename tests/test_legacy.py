"""String-name BGIN fixtures and optional independent checks of external files."""
import copy
from io import BytesIO
import os
from pathlib import Path
import struct
import tempfile
import unittest

from bgin_json import BginError, Limits, encode, parse
from bgin_json.file_conversion import independent_core, verified_binary, convert_saved_file
from bgin_json.header import read_namespace
from bgin_json.render.resources import Resources


def text(value):
    raw = value.encode("utf-8")
    return struct.pack("<H", len(raw)) + raw


def fixture():
    props = [("LegacyCaption", 1024, 1, text("Пример")),
             ("LegacyMode", 4, 1, struct.pack("<i", -7) + text("AnOldChoice")),
             ("LegacyVector", 128, 1, b"\x02" + struct.pack("<2f", 3, 4)),
             ("LegacyCaption", 0, 2, b"")]
    payload = text("screen") + struct.pack("<5f", 0, 0, 0, 1, 1) + struct.pack("<H", len(props))
    for name, kind, count, data in props:
        payload += text(name) + struct.pack("<IH", kind, count) + data
    payload += b"\x00\x00"
    return struct.pack("<I", 0xC1AAA) + text("Database") + text("LegacyUI") + b"\x01\x00" + text("OldCustomContainer") + struct.pack("<I", len(payload)) + payload


class LegacyTests(unittest.TestCase):
    def test_hand_built_fixture_and_unknown_names_are_preserved(self):
        raw = fixture()
        doc = parse(raw)
        self.assertEqual(doc["format"], "legacy")
        self.assertEqual(doc["screens"][0]["type"], "OldCustomContainer")
        self.assertIsInstance(doc["screens"][0]["properties"], list)
        self.assertEqual(doc["screens"][0]["properties"][1]["LegacyMode"], {"enum": "AnOldChoice", "value": -7})
        self.assertEqual(verified_binary(doc), raw)
        self.assertEqual(read_namespace(BytesIO(raw)), "LegacyUI")

    def test_transaction_edits_and_undo_keep_the_variant(self):
        core = independent_core()
        session = core.BginSession(fixture())
        self.assertEqual(session.document.wire_format, "legacy")
        session.rename_node(core.BginAddress(0), "renamed")
        self.assertEqual(parse(session.data)["screens"][0]["name"], "renamed")
        self.assertTrue(session.undo())
        self.assertEqual(session.data, fixture())
        self.assertTrue(session.redo())
        self.assertEqual(core.encode_document(session.snapshot(), force=True), session.data)

    def test_corruption_and_budgets_fail_without_encoding_fallback(self):
        raw = fixture()
        for end in range(1, len(raw)):
            with self.assertRaises(BginError):
                parse(raw[:end])
        with self.assertRaises(BginError):
            parse(raw + b"junk")
        with self.assertRaises(BginError):
            parse(raw, limits=Limits(max_bytes=10))
        with self.assertRaises(BginError):
            encode({**parse(raw), "format": "invented"})

    def test_resource_index_accepts_mixed_variants_and_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "old.bgin").write_bytes(fixture())
            (root / "new.bgin").write_bytes(encode({"name": "ModernUI", "screens": [{"type": "Label", "name": "modern"}]}))
            resources = Resources({"bginRoot": str(root)}, "", set())
            self.assertFalse(resources.errors)
            self.assertEqual(set(resources.sources), {"legacyui", "modernui"})
            (root / "duplicate.bgin").write_bytes(fixture())
            resources.configure({"bginRoot": str(root)}, "", set())
            self.assertNotIn("legacyui", resources.sources)
            self.assertTrue(any("Duplicate" in e["message"] for e in resources.errors))

    def test_file_conversion_reopens_without_the_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, editable, result = root / "old.bgin", root / "editable.json", root / "edited.bgin"
            source.write_bytes(fixture())
            convert_saved_file(source, editable, "json")
            source.unlink()
            convert_saved_file(editable, result, "bgin")
            self.assertEqual(result.read_bytes(), fixture())

    def test_animation_channels_and_renamed_sprite_namespace(self):
        doc = {"name": "CustomSprites", "dialect": "sprites", "format": "legacy", "screens": [
            {"type": "Sprite", "name": "atlas", "children": [
                {"type": "Movie", "name": "pulse", "children": [{"type": "SpriteMovie", "name": "metadata"}],
                 "tracks": [{"type": "MovieModule", "name": "track", "keyframes": [
                    {"frame": 1, "position": {"value": [2, 3], "interpolation": 1},
                     "rotation": {"value": 0.5, "interpolation": 2}, "scale": {"value": [1, 2]},
                     "strings": ["a", "b"], "event": {"name": "tick", "arguments": [4, 5, 6]},
                     "colors": {"LegacyColour": {"vector": [1, 0, 0, 1]}}}]}]}]}]}
        raw = verified_binary(doc)
        reloaded = parse(raw)
        self.assertEqual(reloaded["dialect"], "sprites")
        self.assertEqual(encode(reloaded), raw)
        frame = reloaded["screens"][0]["children"][0]["tracks"][0]["keyframes"][0]
        self.assertEqual(frame["event"]["arguments"], [4, 5, 6])
        self.assertEqual(frame["colors"]["LegacyColour"], [1, 0, 0, 1])


@unittest.skipUnless(os.environ.get("BGIN_LEGACY_CORPUS"), "External legacy corpus not configured")
class LegacyCorpusTests(unittest.TestCase):
    def test_every_document_is_independently_byte_exact(self):
        core = independent_core()
        paths = sorted(Path(os.environ["BGIN_LEGACY_CORPUS"]).glob("*.bgin"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(file=path.name):
                original = path.read_bytes()
                doc = parse(original)
                self.assertEqual(encode(doc), original)
                session = core.BginSession(original)
                self.assertEqual(core.encode_document(session.snapshot(), force=True), original)
                edited = copy.deepcopy(doc)
                edited["screens"][0]["name"] += "_edited"
                compiled = verified_binary(edited)
                self.assertEqual(parse(compiled)["format"], "legacy")
                self.assertEqual(parse(compiled)["screens"][0]["name"], edited["screens"][0]["name"])
                self.assertEqual(path.read_bytes(), original)
