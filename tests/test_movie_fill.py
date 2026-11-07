"""Movie Fill crops its drawing rectangle without enabling container clipping."""

import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image

from bgin_json import encode
from bgin_json.render import render

NS = {"s": "http://www.w3.org/2000/svg"}


class MovieFillTests(unittest.TestCase):
    def test_fill_clips_at_target_while_fit_and_stretch_do_not(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            Image.new("RGBA", (44, 63), (0, 0, 0, 255)).save(folder / "atlas.png")
            library = {
                "name": "Pictures",
                "dialect": "sprites",
                "screens": [
                    {
                        "type": "Sprite",
                        "name": "atlas",
                        "properties": {"Source": "atlas.png"},
                        "children": [
                            {
                                "type": "Module",
                                "name": "fill",
                                "properties": {
                                    "Size": [44, 63],
                                    "BakePosition": [0, 0],
                                },
                            }
                        ],
                    }
                ],
            }
            resource = folder / "pictures.bgin"
            resource.write_bytes(encode(library))
            config = {"bginRoot": str(folder), "textureRoot": str(folder)}
            for keep, mode, clipped in (
                (1, "Fill", True),
                (1, "Fit", False),
                (0, "Fill", False),
            ):
                doc = {
                    "name": "authored",
                    "screens": [
                        {
                            "type": "Movie",
                            "name": "background",
                            "properties": {
                                "Movie": "/Pictures/atlas/fill",
                                "KeepAspectRatio": keep,
                                "Fitting": {"enum": mode},
                                "Alignment": {"enum": "Center"},
                            },
                        }
                    ],
                }
                result = render(
                    doc, {"width": 200, "height": 80, "clipping": False}, config
                )
                svg = ET.fromstring(result["svg"])
                clips = [
                    clip
                    for clip in svg.findall(".//s:clipPath", NS)
                    if clip.get("id", "").startswith("movieFill")
                ]
                self.assertEqual(len(clips), int(clipped), (keep, mode))
                if clipped:
                    self.assertEqual(clips[0].get("clipPathUnits"), "userSpaceOnUse")
                    self.assertEqual(
                        clips[0].find("s:rect", NS).attrib,
                        {"x": "0", "y": "0", "width": "200", "height": "80"},
                    )
                    self.assertTrue(
                        any(
                            g.get("clip-path") == "url(#" + clips[0].get("id") + ")"
                            for g in svg.findall(".//s:g", NS)
                        )
                    )
                self.assertEqual(result["errors"], [])

    def test_fill_clips_have_unique_ids_for_siblings(self):
        from unittest.mock import Mock

        from bgin_json.render.model import Rect
        from bgin_json.render.scene import options
        from bgin_json.render.sprites import Sprites

        resource = Mock()
        resource.lookup.return_value = ({}, {"type": "Movie"})
        sprites = Sprites(resource, options({}), set())
        sprites.bounds = Mock(return_value=(0, 0, 44, 63))
        sprites.node = Mock(return_value="<rect/>")
        for index in range(5):
            sprites.draw(
                "/Pictures/atlas/fill", Rect(10 + index * 100, 50, 90, 30), True, 1
            )
        root = ET.fromstring("<defs>" + "".join(sprites.definitions) + "</defs>")
        ids = [child.get("id") for child in root]
        self.assertEqual(len(set(ids)), 5)
        self.assertEqual(
            [child[0].get("x") for child in root], ["10", "110", "210", "310", "410"]
        )
