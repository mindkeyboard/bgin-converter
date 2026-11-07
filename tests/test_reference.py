"""Optional independent checks against the workspace-owned, verified codec."""
import copy
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bgin_json import encode, load
from bgin_json.parser import jet_hash

reference_root = Path(os.environ.get("BGIN_REFERENCE_WORKSPACE", Path(__file__).resolve().parents[2]))
available = (reference_root / "tools/bgin_core/codec.py").is_file()
if available:
    sys.path.insert(0, str(reference_root))
    from tools.bgin_core import decode_document, encode_document


def nodes(node):
    yield node
    for child in node.get("children", []):
        yield from nodes(child)


@unittest.skipUnless(available, "Independent workspace codec is not installed")
class IndependentTests(unittest.TestCase):
    def checked(self, doc):
        binary = encode(doc)
        ref = decode_document(binary)
        self.assertEqual(encode_document(ref, force=True), binary)
        for screen in ref.screens:
            self.assertTrue(all(n.decoded for n in screen.node.structural_nodes()))
        return ref

    def test_from_authored_json(self):
        ref = self.checked({"name": "test", "screens": [{"type": "Label", "name": "label",
                            "properties": {"TestString": "Тест", "Size": [120, 30]}}]})
        root = ref.screens[0].node
        self.assertEqual(root.property_by_hash(jet_hash("TestString")).value, "Тест")
        self.assertEqual(root.property_by_hash(jet_hash("Size")).value, [120., 30.])

    def test_edit_actual_profile(self):
        path = reference_root / "inputs/bgin/corpus/gui/profile.bgin"
        if not path.is_file():
            self.skipTest("Profile corpus file is unavailable")
        doc = load(path)
        root = doc["screens"][0]
        prototype = next(n for n in nodes(root) if n["type"] == "Label")
        clone = copy.deepcopy(prototype)
        clone["name"] = "converter_label"
        clone.setdefault("properties", {})["TestString"] = "Изменено"
        root["children"].insert(0, clone)
        root["name"] = "renamed_screen"
        root["properties"]["Size"] = [700, 400]
        ref = self.checked(doc)
        label = ref.screens[0].node.children[0]
        self.assertEqual(label.name, "converter_label")
        self.assertEqual(label.property_by_hash(jet_hash("TestString")).value, "Изменено")
        self.assertEqual(ref.screens[0].name_hash, jet_hash("renamed_screen"))

    def test_edit_actual_sprite_track(self):
        path = reference_root / "inputs/bgin/corpus/gui/sprites.bgin"
        if not path.is_file():
            self.skipTest("Sprites corpus file is unavailable")
        doc = load(path)
        movie = next(n for screen in doc["screens"] for n in nodes(screen)
                     if n.get("tracks") and any(t.get("keyframes") for t in n["tracks"]))
        track = next(t for t in movie["tracks"] if t.get("keyframes"))
        clone = copy.deepcopy(track)
        clone["name"] += "_clone"
        clone["keyframes"][0]["position"] = {"value": [42, 84], "interpolation": 1}
        movie["tracks"].append(clone)
        ref = self.checked(doc)
        rebuilt = next(n for s in ref.screens for n in s.node.structural_nodes()
                       if n.sprite_movie is not None and n.name == movie["name"])
        self.assertEqual(rebuilt.sprite_movie.tracks[-1].node.name, clone["name"])
        self.assertEqual(rebuilt.sprite_movie.tracks[-1].keyframes[0].position, (42., 84.))
