import copy
import json
import os
from pathlib import Path
import random
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bgin_json import BginError, Limits, convert_file, dumps, encode, load, load_json, parse
from bgin_json.parser import jet_hash
from fixtures import document, node, prop, sprite_document, text, u32


def sample():
    return {"name": "example", "screens": [{"type": "StackContainer", "name": "screen",
            "properties": {"Size": [200, 100]}, "children": [
                {"type": "Label", "name": "caption", "properties": {"Text": "Пример"}}]}]}


class ConverterTests(unittest.TestCase):
    def test_json_authored_without_original(self):
        original = sample()
        raw = encode(original)
        self.assertEqual(parse(raw), original)
        self.assertEqual(encode(json.loads(dumps(parse(raw)))), raw)

    def test_edit_rename_insert_delete_and_reorder(self):
        original = sample()
        raw = encode(original)
        doc = parse(raw)
        doc["name"] = "renamed"
        root = doc["screens"][0]
        root["name"] = "new_screen"
        root["properties"]["Size"] = [320, 240]
        label = root["children"][0]
        label["properties"]["Text"] = "Изменённая длинная подпись 🌍"
        label["name"] = "renamed_caption"
        root["children"].insert(0, {"type": "VerticalContainer", "name": "panel"})
        root["children"].reverse()
        doc["screens"].append({"type": "StackContainer", "name": "second_screen"})
        self.assertEqual(parse(encode(doc)), doc)
        del root["children"][1]
        del root["properties"]["Size"]
        del root["properties"]
        self.assertEqual(parse(encode(doc)), doc)

    def test_no_binary_bookkeeping_in_json(self):
        result = dumps(parse(encode(sample())))
        for forbidden in ("type_hash", "metadata_hex", "sha256", "raw_hex", "offset", "payload_size", "decoded", "directory", "0x"):
            self.assertNotIn(forbidden, result)
        self.assertEqual(set(json.loads(result)), {"name", "screens"})

    def test_every_property_type_cardinality_and_exact_bytes(self):
        records = [prop(0, 0), prop(0, 7), prop(2, 1, struct.pack("<d", 1.25)),
                   prop(2, 2, struct.pack("<dd", 2., 3.)),
                   prop(4, 1, struct.pack("<i", -1) + u32(jet_hash("Center")) + text("Center")),
                   prop(8, 2, text("a/b") + text("c")),
                   prop(128, 2, bytes([0, 2]) + struct.pack("<ff", 1., 2.)),
                   prop(1024, 1, text("Юникод"))]
        records += [prop(k, 0) for k in (2, 4, 8, 128, 1024)]
        records += [prop(128, 1, b"\x00")]
        raw = document([node(properties=records)])
        doc = parse(raw)
        self.assertIsInstance(doc["screens"][0]["properties"], list)
        self.assertEqual(encode(json.loads(dumps(doc))), raw)

    def test_scalar_and_vector_minimum_sizes(self):
        for value in (0, [10, 20], {"number": [10, 20]}, {"vectors": []}):
            doc = sample()
            doc["screens"][0]["properties"]["MinSize"] = value
            raw = encode(doc)
            self.assertEqual(encode(parse(raw)), raw)

    def test_transform_numbers_and_negative_zero(self):
        doc = sample()
        doc["screens"][0]["transform"] = [-0., 17., .5, 2., 3.]
        raw = encode(doc)
        parsed = parse(raw)
        self.assertEqual(struct.pack("<f", parsed["screens"][0]["transform"][0]), b"\x00\x00\x00\x80")
        self.assertEqual(encode(parsed), raw)

    def test_all_keyframe_flags_roundtrip(self):
        for flags in range(64):
            with self.subTest(flags=flags):
                raw = sprite_document(flags)
                doc = parse(raw)
                self.assertEqual(encode(json.loads(dumps(doc))), raw)

    def test_real_animation_edit_changes_values_and_lengths(self):
        doc = parse(sprite_document())
        movie = doc["screens"][0]["children"][0]
        frame = movie["tracks"][0]["keyframes"][0]
        frame["position"]["value"] = [100, 200]
        frame["event"]["name"] = "new_long_event_name"
        frame["strings"] = ["новая", "строка"]
        movie["settings"] = [30, 0, 6666, 0]
        movie["tracks"].append(copy.deepcopy(movie["tracks"][0]))
        self.assertEqual(parse(encode(doc)), doc)

    def test_unsupported_data_is_rejected_without_dumping_it(self):
        cases = [document([node(properties=[prop(0x7777, 0)])]),
                 document([node(type_hash=0x12345678)]),
                 document(extra=b"x"), sprite_document(0x40),
                 document([node(properties=[prop(2, 1, struct.pack("<d", float("nan")))])])]
        for raw in cases:
            with self.subTest(size=len(raw)):
                with self.assertRaises(BginError):
                    parse(raw)

    def test_truncation_and_mutations(self):
        raw = sprite_document()
        for end in range(1, len(raw)):
            with self.assertRaises(BginError):
                parse(raw[:end])
        rng = random.Random(7301)
        for _ in range(200):
            modified = bytearray(raw)
            modified[rng.randrange(len(raw))] = rng.randrange(256)
            try:
                doc = parse(bytes(modified))
                self.assertEqual(encode(doc), bytes(modified))
            except BginError:
                pass

    def test_limits_in_both_directions(self):
        raw = encode(sample())
        for limits in (Limits(max_bytes=10), Limits(max_nodes=1), Limits(max_values=1), Limits(max_depth=1)):
            with self.assertRaises(BginError):
                encode(sample(), limits=limits)
            with self.assertRaises(BginError):
                parse(raw, limits=limits)
        doc = sample()
        doc["screens"][0]["properties"] = {"Text": ["a" * 100] * 1000}
        with self.assertRaises(BginError):
            encode(doc, limits=Limits(max_bytes=1000))

    def test_invalid_edit_is_rejected(self):
        bad_values = [True, "a", float("inf"), {"vector": [1, "a"]}]
        for value in bad_values:
            doc = sample()
            doc["screens"][0]["properties"]["Size"] = value
            with self.assertRaises(BginError):
                encode(doc)
        for key in ("metadata_hex", "type_hash", "raw_hex", "sha256", "surprise"):
            doc = sample()
            doc["screens"][0][key] = "forbidden"
            with self.assertRaises(BginError):
                encode(doc)

    def test_maximum_depth(self):
        root = {"type": "StackContainer", "name": "leaf"}
        for _ in range(127):
            root = {"type": "StackContainer", "name": "parent", "children": [root]}
        doc = {"name": "depth", "screens": [root]}
        self.assertEqual(json.loads(dumps(parse(encode(doc)))), doc)


class FileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.binary = self.folder / "тест.bgin"
        self.binary.write_bytes(encode(sample()))
        self.json = self.folder / "edit.json"
        self.output = self.folder / "rebuilt.bgin"

    def cli(self, path, *args):
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        return subprocess.run([sys.executable, "-m", "bgin_json", str(path), *map(str, args)],
                              cwd=self.folder, env=env, capture_output=True, encoding="utf-8")

    def test_cli_roundtrip_in_separate_processes(self):
        a = self.cli(self.binary, "-o", self.json)
        b = self.cli(self.json, "-o", self.output)
        self.assertEqual((a.returncode, b.returncode), (0, 0), a.stderr + b.stderr)
        self.assertEqual(self.binary.read_bytes(), self.output.read_bytes())
        self.assertEqual(a.stdout + b.stdout, "")
        self.assertEqual(a.stderr + b.stderr, "")

    def test_json_edit_survives_source_removal(self):
        convert_file(self.binary, self.json)
        self.binary.unlink()
        doc = load_json(self.json)
        doc["screens"][0]["children"][0]["properties"]["Text"] = "Готово"
        self.json.write_text(dumps(doc), encoding="utf-8")
        convert_file(self.json, self.output)
        self.assertEqual(load(self.output), doc)
        self.assertEqual({p.name for p in self.folder.iterdir()}, {"edit.json", "rebuilt.bgin"})

    def test_no_accidental_overwrite_or_partial_file(self):
        original = self.binary.read_bytes()
        with self.assertRaises(ValueError):
            convert_file(self.binary, self.binary, overwrite=True)
        alias = self.folder / "alias.bgin"
        os.link(self.binary, alias)
        with self.assertRaises(ValueError):
            convert_file(self.binary, alias, overwrite=True)
        convert_file(self.binary, self.json)
        with self.assertRaises(FileExistsError):
            convert_file(self.binary, self.json)
        self.json.write_text('{"screens": "bad"}', encoding="utf-8")
        self.output.write_bytes(b"previous")
        with self.assertRaises(BginError):
            convert_file(self.json, self.output, overwrite=True)
        self.assertEqual(self.output.read_bytes(), b"previous")
        self.assertEqual(self.binary.read_bytes(), original)
        self.assertFalse(list(self.folder.glob(".bgin-*.tmp")))

    def test_duplicate_json_keys_and_non_finite_are_errors(self):
        for value in ('{"name":"a","name":"b"}', '{"name":NaN}', '{broken', '\ud800'):
            self.json.write_bytes(value.encode("utf-8", errors="surrogatepass"))
            with self.assertRaises(BginError):
                load_json(self.json)

    def test_stdout_and_error_codes(self):
        result = self.cli(self.binary)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), sample())
        self.json.write_text("not json", encoding="utf-8")
        result = self.cli(self.json, "-o", self.output)
        self.assertEqual(result.returncode, 1)
        self.assertIn("error", json.loads(result.stderr))
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
