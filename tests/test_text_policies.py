"""The two three-value policy domains are independent."""

import unittest
from copy import deepcopy
from xml.etree import ElementTree as ET

from bgin_json.render import render
from bgin_json.render.scene import Scene
from bgin_json.render.text import initial_offsets


def label(horizontal="ScrollWrap", vertical="HeightFactor", **extra):
    return {
        "type": "Label",
        "name": "menu_label",
        "properties": {
            "FontHeight": [2, 20],
            "MarginFactors": [1, 1, 0, 0],
            "Alignment": {"enum": "Center", "value": 4},
            "TextPolicy": {"enum": horizontal},
            "VerticalTextPolicy": {"enum": vertical},
            "HeightFactor": 4.5,
            "TestString": "COLOR CAR SELECTION",
            **extra,
        },
    }


def text_elements(result):
    return [e for e in ET.fromstring(result["svg"]).iter() if e.tag.endswith("text")]


class TextPolicyTests(unittest.TestCase):
    def test_all_nine_combinations_keep_independent_layout_width_rules(self):
        for horizontal in ("Fit", "Scroll", "ScrollWrap"):
            for vertical in ("Default", "HeightFactor", "Fit"):
                with self.subTest(horizontal=horizontal, vertical=vertical):
                    n = label(horizontal, vertical, MaxSize=[320, 86.4])
                    doc = {"name": "authored", "screens": [n]}
                    original = deepcopy(doc)
                    s = Scene(doc, {"width": 1920, "height": 1080, "bounds": False})
                    result = s.build()
                    self.assertEqual(doc, original)
                    minimum = s.minimum_content(n, (320, 86.4))
                    self.assertEqual(minimum[0] > 0, horizontal == "Fit")
                    heights = [float(e.get("font-size")) for e in text_elements(result)]
                    self.assertTrue(heights)
                    self.assertTrue(all(7.56 <= h <= 75.6 for h in heights))
                    if vertical == "HeightFactor":
                        self.assertAlmostEqual(heights[0], 48.6)
                        self.assertAlmostEqual(minimum[1], 48.6)
                    self.assertFalse(
                        any("did not converge" in w for w in result["warnings"])
                    )

    def test_height_factor_uses_screen_not_short_label_height(self):
        n = label(MaxSize=[500, 86.4])
        doc = {"name": "authored", "screens": [n]}
        full = render(doc, {"width": 1920, "height": 1080, "bounds": False})
        narrow = render(doc, {"width": 1920, "height": 86.4, "bounds": False})
        self.assertAlmostEqual(float(text_elements(full)[0].get("font-size")), 48.6)
        self.assertAlmostEqual(float(text_elements(narrow)[0].get("font-size")), 7.56)
        self.assertEqual(full["geometry"][0]["height"], 86.4)

    def test_horizontal_fit_does_not_shrink_height_factor_when_maximum_is_narrow(self):
        n = label("Fit", MaxSize=[40, 80], TestString="A long caption" * 5)
        result = render(
            {"name": "authored", "screens": [n]},
            {"width": 1280, "height": 720, "bounds": False},
        )
        self.assertAlmostEqual(float(text_elements(result)[0].get("font-size")), 32.4)
        self.assertIn("textClip", result["svg"])

    def test_scrollwrap_repeats_only_overflowing_text_without_resizing_it(self):
        for policy, copies in (("Scroll", 1), ("ScrollWrap", 2)):
            result = render(
                {"name": "authored", "screens": [label(policy, MaxSize=[50, 80])]},
                {"width": 1280, "height": 720, "bounds": False},
            )
            self.assertEqual(len(text_elements(result)), copies)
            self.assertTrue(
                all(float(e.get("font-size")) == 32.4 for e in text_elements(result))
            )
        self.assertEqual(initial_offsets(1, 200, 100, 20, False), (0,))
        self.assertEqual(initial_offsets(1, 200, 100, 20, True), (-100,))
        self.assertEqual(initial_offsets(2, 200, 100, 20, False), (0, 240))
        self.assertEqual(initial_offsets(2, 200, 100, 20, True), (-340, -100))
        self.assertEqual(initial_offsets(2, 80, 100, 20, True), (0,))

    def test_default_draw_height_and_minimum_are_different(self):
        n = label("Scroll", "Default", MaxSize=[500, 60])
        s = Scene(
            {"name": "authored", "screens": [n]},
            {"width": 1280, "height": 720, "bounds": False},
        )
        result = s.build()
        self.assertAlmostEqual(float(text_elements(result)[0].get("font-size")), 60)
        self.assertLess(s.minimum_content(n, (500, 60))[1], 10)


if __name__ == "__main__":
    unittest.main()
