"""File conversion through the same RPC used by the sidebar."""
import base64
import json
from pathlib import Path
import tempfile
import unittest

from bgin_json import encode
from bgin_json.rpc import Server


class FileConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.server = Server()
        self.doc = {"name": "example", "screens": [{"type": "StackContainer", "name": "main"}]}
        self.source = self.root / "source.bgin"
        self.source.write_bytes(encode(self.doc))

    def call(self, source, destination, to, **kwargs):
        result = self.server.response({"id": 1, "method": "convert", "params": {"source": str(source), "destination": str(destination), "to": to, **kwargs}})
        if "error" in result:
            raise ValueError(result["error"]["message"])
        return result["result"]

    def test_binary_json_binary_is_byte_exact(self):
        from bgin_core import BginSession, encode_document
        text, binary = self.root / "editable.json", self.root / "edited.bgin"
        self.call(self.source, text, "json")
        doc = json.loads(text.read_text(encoding="utf-8"))
        self.assertEqual(doc, self.doc)
        self.call(text, binary, "bgin")
        self.assertEqual(binary.read_bytes(), self.source.read_bytes())
        session = BginSession(binary.read_bytes(), "ui")
        self.assertEqual(encode_document(session.snapshot(), force=True), binary.read_bytes())

    def test_edit_json_is_reflected_in_binary(self):
        from bgin_json import parse
        text, binary = self.root / "editable.json", self.root / "edited.bgin"
        self.call(self.source, text, "json")
        doc = json.loads(text.read_text(encoding="utf-8"))
        doc["screens"][0]["name"] = "edited"
        text.write_text(json.dumps(doc), encoding="utf-8-sig")
        self.call(text, binary, "bgin")
        self.assertEqual(parse(binary.read_bytes())["screens"][0]["name"], "edited")

    def test_invalid_input_never_changes_destination(self):
        text, binary = self.root / "invalid.json", self.root / "existing.bgin"
        binary.write_bytes(b"original")
        for value in ('{"screens":[}', '{"name":"a","name":"b"}', '{"screens":[],"unknown":123}'):
            text.write_text(value, encoding="utf-8")
            with self.assertRaises(ValueError):
                self.call(text, binary, "bgin", overwrite=True)
            self.assertEqual(binary.read_bytes(), b"original")
        self.assertFalse(list(self.root.glob("*.bak")))

    def test_overwrite_is_explicit_and_recoverable(self):
        text = self.root / "existing.json"
        text.write_bytes(b"keep me")
        with self.assertRaises(ValueError):
            self.call(self.source, text, "json")
        result = self.call(self.source, text, "json", overwrite=True, expected=base64.b64encode(b"keep me").decode())
        self.assertEqual(Path(result["backup"]).read_bytes(), b"keep me")
        self.assertEqual(json.loads(text.read_text()), self.doc)

    def test_destination_changes_after_confirmation_are_rejected(self):
        text = self.root / "existing.json"
        text.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "changed since"):
            self.call(self.source, text, "json", overwrite=True, expected=base64.b64encode(b"old").decode())
        self.assertEqual(text.read_bytes(), b"changed")

    def test_same_file_and_hardlink_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "different"):
            self.call(self.source, self.source, "json", overwrite=True)
        alias = self.root / "alias.json"
        alias.hardlink_to(self.source)
        with self.assertRaisesRegex(ValueError, "different"):
            self.call(self.source, alias, "json", overwrite=True)

    def test_empty_explorer_draft_round_trip(self):
        blank, text, target = self.root / "blank.bgin", self.root / "draft.json", self.root / "new.bgin"
        blank.write_bytes(b"")
        decoded = self.call(blank, text, "json")
        self.assertEqual(json.loads(text.read_text()), {"screens": []})
        self.assertTrue(decoded["warnings"])
        encoded = self.call(text, target, "bgin")
        self.assertTrue(encoded["warnings"])
        self.assertEqual(target.read_bytes(), b"")

    def test_public_codec_empty_draft_without_name(self):
        from bgin_json import parse
        self.assertEqual(parse(b""), {"screens": []})
        self.assertEqual(encode({"screens": []}), b"")
        self.assertEqual(self.server.call("validate", {"text": '{"screens": []}'})["valid"], True)
        self.assertTrue(self.server.call("validate", {"text": '{"screens": []}'})["warnings"])
        with self.assertRaises(ValueError):
            encode({"screens": [{"type": "StackContainer", "name": "main"}]})


if __name__ == "__main__":
    unittest.main()
