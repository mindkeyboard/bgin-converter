"""TextArea uses a screen percentage and width-dependent multiline height."""

import unittest
from copy import deepcopy
from xml.etree import ElementTree as ET

from bgin_json.render import render
from bgin_json.render.scene import Scene
from bgin_json.render.text import wrapped_lines


def area(text="A short message", **extra):
    return {
        "type": "TextArea",
        "name": "content_label",
        "properties": {
            "FontHeight": [2, 20],
            "FontHeightFactor": 4,
            "Alignment": {"enum": "Center", "value": 4},
            "TestString": text,
            **extra,
        },
    }


class TextAreaTests(unittest.TestCase):
    def test_factor_is_percentage_of_screen_and_style_limits_are_world_units(self):
        n = area()
        s = Scene({"name": "authored", "screens": [n]}, {"width": 1280, "height": 720})
        self.assertAlmostEqual(s.text_style(n)[1], 28.8)
        n["properties"]["FontHeight"] = [2, 3]
        self.assertAlmostEqual(s.text_style(n)[1], 11.34)
        del n["properties"]["FontHeightFactor"]
        n["properties"]["FontHeight"] = [2, 100]
        self.assertAlmostEqual(s.text_style(n)[1], 72)

    def test_margin_container_keeps_width_for_wrapping_instead_of_token_minimum(self):
        n = area("A message with several words that should wrap across multiple lines")
        doc = {
            "name": "authored",
            "screens": [
                {
                    "type": "MarginContainer",
                    "name": "margin",
                    "properties": {"MarginFactors": [10, 10, 0, 0]},
                    "children": [n],
                }
            ],
        }
        before = deepcopy(doc)
        s = Scene(doc, {"width": 200, "height": 720, "bounds": False})
        result = s.build()
        self.assertEqual(doc, before)
        self.assertEqual(s.minimum_content(n, (160, 720))[0], 0)
        tree = ET.fromstring(result["svg"])
        spans = [e for e in tree.iter() if e.tag.endswith("tspan")]
        self.assertGreater(len(spans), 1)
        self.assertTrue(all(float(e.get("x")) == 100 for e in spans))
        self.assertAlmostEqual(result["geometry"][1]["width"], 160)
        self.assertIn("textClip", result["svg"])
        self.assertFalse(any("did not converge" in w for w in result["warnings"]))

    def test_explicit_newlines_empty_text_and_unbreakable_words(self):
        n = area("first\n\nthird")
        s = Scene({"name": "authored", "screens": [n]})
        _, height, _, font, _ = s.text_style(n)
        lines, _ = wrapped_lines(font, "first\n\nthird", height, 10000)
        self.assertEqual(lines, ["first", "", "third"])
        self.assertEqual(
            wrapped_lines(font, "unbreakable_word", height, 1)[0], ["unbreakable_word"]
        )
        self.assertEqual(wrapped_lines(font, "abcd", height, 1, True)[0], list("abcd"))
        n["properties"]["TestString"] = ""
        self.assertEqual(
            Scene({"name": "authored", "screens": [n]}).minimum_content(n, (100, 100)),
            (0, 0),
        )

    def test_short_screen_still_applies_style_minimum_without_label_policies(self):
        n = area(TextPolicy={"enum": "Fit"}, VerticalTextPolicy={"enum": "Fit"})
        result = render(
            {"name": "authored", "screens": [n]}, {"width": 1920, "height": 86.4}
        )
        text = next(
            e for e in ET.fromstring(result["svg"]).iter() if e.tag.endswith("text")
        )
        self.assertAlmostEqual(float(text.get("font-size")), 7.56)


if __name__ == "__main__":
    unittest.main()
