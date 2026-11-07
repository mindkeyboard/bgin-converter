"""Vertical Fit measures at the style minimum and draws at the final fitted size."""

import math
import unittest
from copy import deepcopy
from xml.etree import ElementTree as ET

from bgin_json.render.scene import Scene


class TextFitTests(unittest.TestCase):
    def test_margin_container_text_grows_without_changing_layout_minimum(self):
        label = {
            "type": "Label",
            "name": "caption",
            "properties": {
                "FontHeight": [2, 20],
                "TextPolicy": {"enum": "Fit"},
                "VerticalTextPolicy": {"enum": "Fit"},
                "TestString": "$STR_MENU_SINGLE_PLAYER",
            },
        }
        doc = {
            "name": "authored",
            "screens": [
                {
                    "type": "MarginContainer",
                    "name": "margin",
                    "properties": {"MarginFactors": [4, 0, 20, 20]},
                    "children": [label],
                }
            ],
        }
        original = deepcopy(doc)
        scene = Scene(doc, {"width": 360, "height": 100, "bounds": False})
        minimum = scene.minimum_content(label)
        result = scene.build()
        text = next(
            e for e in ET.fromstring(result["svg"]).iter() if e.tag.endswith("text")
        )
        height = float(text.get("font-size"))
        self.assertGreater(height, minimum[1] * 2)
        self.assertLessEqual(height, 60)
        self.assertEqual(scene.minimum_content(label), minimum)
        self.assertEqual(doc, original)

    def test_fit_uses_inner_width_and_style_limits_for_labels_and_buttons(self):
        for kind in ("Label", "Button"):
            for size in ((240, 100), (400, 12), (2000, 200), (0, 0)):
                with self.subTest(kind=kind, size=size):
                    label = {
                        "type": kind,
                        "name": "caption",
                        "properties": {
                            "FontHeight": [2, 20],
                            "TextPolicy": {"enum": "Fit"},
                            "VerticalTextPolicy": {"enum": "Fit"},
                            "MarginFactors": [10, 20, 10, 20],
                            "TestString": "A fitted caption",
                        },
                    }
                    scene = Scene(
                        {"name": "authored", "screens": [label]},
                        {
                            "width": max(64, size[0]),
                            "height": max(64, size[1]),
                            "pixelsPerMm": 2,
                        },
                    )
                    from bgin_json.render.model import Rect

                    _, reference_height, text, font, _ = scene.text_style(label)
                    inner = Rect(0, 0, *size).inset(
                        (size[1] * 0.1, size[1] * 0.2, size[0] * 0.1, size[0] * 0.2)
                    )
                    expected = min(
                        40,
                        max(
                            4,
                            min(
                                inner.h,
                                math.floor(inner.w / 2)
                                * 2
                                / (font.getlength(text) * reference_height / font.size)
                                * 4,
                            ),
                        ),
                    )
                    self.assertAlmostEqual(scene.text_style(label, inner)[1], expected)


if __name__ == "__main__":
    unittest.main()
