"""Namespace discovery uses only explicit folders and defers full BGIN parsing."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bgin_json import encode
from bgin_json.render.resources import Resources


def document(namespace, name="caption"):
    return {
        "name": namespace,
        "screens": [
            {"type": "TextStyle", "name": name, "properties": {"FontHeight": [2, 18]}}
        ],
    }


class ResourceFolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, filename, namespace):
        target = self.root / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encode(document(namespace)))
        return target

    def test_folder_index_uses_internal_namespace_and_loads_only_references(self):
        one = self.write("unrelated-filename.bgin", "Widgets")
        self.write("gui/second.bgin", "Other")
        with patch(
            "bgin_json.render.resources.load",
            wraps=__import__("bgin_json.parser", fromlist=["load"]).load,
        ) as load:
            resources = Resources({"bginRoot": str(self.root)}, "", set())
            self.assertEqual(load.call_count, 0)
            self.assertEqual(set(resources.sources), {"widgets", "other"})
            self.assertEqual(resources.style("/Widgets/caption")["FontHeight"], [2, 18])
            self.assertEqual(load.call_count, 1)
            self.assertEqual(load.call_args.args[0], one)
            resources.lookup("/Widgets/caption")
            self.assertEqual(load.call_count, 1)
            self.assertNotIn("other", resources.bindings)

    def test_unused_body_is_not_parsed_and_a_bad_referenced_body_is_diagnostic(self):
        file = self.write("header-only.bgin", "Lazy")
        data = file.read_bytes()
        length = int.from_bytes(data[8:10], "little")
        file.write_bytes(data[: 10 + length])
        resources = Resources({"bginRoot": str(self.root)}, "", set())
        self.assertFalse(
            resources.errors, "Header indexing must not parse an unused body"
        )
        with self.assertRaises(KeyError):
            resources.lookup("/Lazy/caption")
        self.assertTrue(any("Lazy" in error["message"] for error in resources.errors))

    def test_duplicate_namespace_is_reported_and_neither_file_is_used(self):
        self.write("one.bgin", "Widgets")
        self.write("gui/two.bgin", "widgets")
        resources = Resources({"bginRoot": str(self.root)}, "", set())
        self.assertNotIn("widgets", resources.sources)
        self.assertTrue(
            any(
                "Duplicate BGIN namespace" in error["message"]
                for error in resources.errors
            )
        )
        with self.assertRaises(KeyError):
            resources.lookup("/Widgets/caption")

    def test_missing_or_invalid_folder_files_are_reported(self):
        missing = Resources({"bginRoot": str(self.root / "absent")}, "", set())
        self.assertTrue(
            any("directory not found" in error["message"] for error in missing.errors)
        )
        (self.root / "bad.bgin").write_bytes(b"not BGIN")
        invalid = Resources({"bginRoot": str(self.root)}, "", set())
        self.assertTrue(
            any("Invalid BGIN header" in error["message"] for error in invalid.errors)
        )

    def test_configure_reloads_changed_namespaces_and_keeps_legacy_explicit_alias(self):
        file = self.write("library.bgin", "First")
        resources = Resources({"bginRoot": str(self.root)}, "", set())
        resources.lookup("/First/caption")
        file.write_bytes(encode(document("Changed")))
        resources.configure({"bginRoot": str(self.root)}, "", set())
        with self.assertRaises(KeyError):
            resources.lookup("/First/caption")
        self.assertEqual(resources.lookup("/Changed/caption")[1]["name"], "caption")
        resources.configure({"bindings": {"Manual": str(file)}}, "", set())
        self.assertEqual(resources.lookup("/Manual/caption")[1]["type"], "TextStyle")
        resources.configure({}, str(self.root / "menu.bgin"), set())
        self.assertFalse(
            resources.sources, "Adjacent BGIN files require an explicit folder"
        )
        self.assertEqual(resources.root, self.root)


if __name__ == "__main__":
    unittest.main()
