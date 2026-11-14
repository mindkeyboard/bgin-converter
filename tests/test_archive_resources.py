"""Partial resource packs are read lazily; original archives remain immutable."""

import struct
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from bgin_json.render.resources import Resources
from bgin_json.render.scene import Scene
from bgin_json.render.model import value
from bgin_json.mcp_server.service import Service


class ArchiveResourceTests(unittest.TestCase):
    def test_partial_pad_loads_only_requested_texture_and_alpha(self):
        from PIL import Image
        def png(color):
            output = BytesIO()
            Image.new("RGBA", (2, 2), color).save(output, format="PNG")
            return output.getvalue()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack = root / "textures_pack1/58011/58011/assets/data#tcf_astc/textures1.jpk"
            pack.parent.mkdir(parents=True)
            with ZipFile(pack, "w") as zipped:
                zipped.writestr("../image.tga", png((10, 20, 30, 255)))
                zipped.writestr("image.tga__alpha", png((123, 123, 123, 255)))
                zipped.writestr("unused.tga", b"invalid unused texture")
            original = pack.read_bytes()
            resources = Resources({"textureRoot": str(root)}, "", set())
            self.assertIsNone(resources.archives.temporary)
            image = resources.texture({"properties": {"Source": "exporter/image.tga"}}, True)
            self.assertEqual(image.getpixel((0, 0)), (10, 20, 30, 123))
            self.assertEqual(len(resources.archives.extracted), 2)
            self.assertEqual(pack.read_bytes(), original)
            self.assertFalse((root / "image.tga").exists())
            resources.archives.temporary.cleanup()

    def test_duplicate_members_are_reported_and_updated_archive_is_reloaded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack = root / "textures1.jpk"
            with ZipFile(pack, "w") as zipped:
                zipped.writestr("a/image.tga", b"one")
                zipped.writestr("b/image.tga", b"two")
            resources = Resources({"textureRoot": str(root)}, "", set())
            with self.assertRaisesRegex(ValueError, "Ambiguous texture"):
                resources.resolve_file("image.tga")
            with ZipFile(pack, "w") as zipped:
                zipped.writestr("image.tga", b"updated")
            self.assertEqual(resources.resolve_file("image.tga").read_bytes(), b"updated")
            with self.assertRaises(FileNotFoundError):
                resources.resolve_file("absent.tga")
            resources.archives.temporary.cleanup()

    def test_primary_variant_preview_and_explicit_coverage(self):
        prop = {"value": {"number": 2}, "variants": [{"key": "#12345678", "value": 9}]}
        self.assertEqual(value({"StretchFactor": prop}, "StretchFactor"), 2)
        doc = {"name": "Modern", "format": "a8-5.8.0", "screens": [
            {"name": "root", "type": "StackContainer", "properties": {"StretchFactor": prop},
             "color_channels": [{"key": "#12345678", "value": [1]}]}]}
        scene = Scene(doc)
        self.assertTrue(any("primary values" in warning for warning in scene.warnings))
        self.assertTrue(any("not rendered" in warning for warning in scene.warnings))
        self.assertEqual(prop["variants"][0]["value"], 9)

    def test_report_checks_texture_target_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # One ETC2 block, no outer compression.
            raw = struct.pack("<IIQ9I", 0x03525650, 0, 22, 0, 0, 4, 4, 1, 1, 1, 1, 0) + bytes(8)
            (root / "image.tga").write_bytes(raw)
            doc = {"name": "Modern", "format": "a8-5.8.0", "screens": [
                {"name": "image", "type": "Sprite", "properties": {"Source": "image.tga"}}]}
            service = Service(root / "settings.json")
            report = service.resource_report({"document": doc}, {"textureRoot": str(root)}, "a8-1.6.0")
            self.assertFalse(report["textures"][0]["compatible"])
            self.assertFalse(report["textures"][0]["runtime_verified"])
            self.assertEqual((root / "image.tga").read_bytes(), raw)
