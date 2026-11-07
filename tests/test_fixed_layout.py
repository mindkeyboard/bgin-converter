"""FixedSizeContainer separates stored constraints from its centered child region."""

import unittest
from copy import deepcopy

from bgin_json.render import render


def node(kind, name, properties=None, children=None):
    result = {"type": kind, "name": name, "properties": properties or {}}
    if children is not None:
        result["children"] = children
    return result


def boxes(root, width=400, height=200):
    result = render(
        {"name": "authored", "screens": [root]}, {"width": width, "height": height}
    )
    return {box["name"]: box for box in result["geometry"]}


class FixedLayoutTests(unittest.TestCase):
    def test_fixed_child_region_does_not_fill_the_outer_container(self):
        child = node("Movie", "image")
        child["transform"] = [999, -999, 0, 1, 1]
        root = node(
            "FixedSizeContainer",
            "fixed",
            {
                "EnableFixedWidth": 1,
                "FixedWidthFactor": 25,
                "EnableFixedHeight": 1,
                "FixedHeightFactor": 25,
                "Margins": [900, 800, 700, 600],
            },
            [child],
        )
        before = deepcopy(root)
        measured = boxes(root)
        self.assertEqual(
            (measured["fixed"]["width"], measured["fixed"]["height"]), (400, 200)
        )
        self.assertEqual(
            tuple(measured["image"][key] for key in ("x", "y", "width", "height")),
            (150, 75, 100, 50),
        )
        self.assertEqual(root, before)

    def test_aspect_multiplies_the_unfixed_axis_and_is_disabled_for_two_axes(self):
        cases = (
            (
                {"EnableFixedWidth": 1, "FixedWidthFactor": 25, "AspectRatio": 0.5},
                (100, 50),
            ),
            (
                {"EnableFixedHeight": 1, "FixedHeightFactor": 25, "AspectRatio": 2},
                (100, 50),
            ),
            (
                {
                    "EnableFixedWidth": 1,
                    "EnableFixedHeight": 1,
                    "FixedWidthFactor": 50,
                    "FixedHeightFactor": 25,
                    "AspectRatio": 9,
                },
                (200, 50),
            ),
            ({"AspectRatio": 9}, (400, 200)),
            (
                {"EnableFixedWidth": 1, "FixedWidthFactor": 25, "AspectRatio": 0},
                (100, 0),
            ),
        )
        for properties, expected in cases:
            root = node(
                "FixedSizeContainer",
                "fixed",
                {"EnableAspectRatio": 1, **properties},
                [node("Movie", "image")],
            )
            image = boxes(root)["image"]
            self.assertEqual((image["width"], image["height"]), expected, properties)

    def test_stretch_weight_affects_outer_allocation_but_not_the_fixed_child_axis(self):
        for stretch, outer_width in ((0, 100), (1, 200), (3, 300)):
            fixed = node(
                "FixedSizeContainer",
                "fixed",
                {
                    "EnableFixedWidth": 1,
                    "FixedWidthFactor": 25,
                    "StretchFactor": stretch,
                },
                [node("Movie", "image")],
            )
            root = node(
                "HorizontalContainer",
                "row",
                {},
                [fixed, node("Movie", "rest", {"StretchFactor": 1})],
            )
            measured = boxes(root)
            self.assertEqual(measured["fixed"]["width"], outer_width)
            self.assertEqual(measured["image"]["width"], 100)
            self.assertEqual(measured["image"]["x"], (outer_width - 100) / 2)
            self.assertEqual(measured["rest"]["width"], 400 - outer_width)

    def test_aspect_constraint_uses_child_minimum_before_final_exact_region(self):
        fixed = node(
            "FixedSizeContainer",
            "fixed",
            {
                "EnableFixedWidth": 1,
                "FixedWidthFactor": 25,
                "EnableAspectRatio": 1,
                "AspectRatio": 0.5,
            },
            [node("Movie", "image", {"MinSize": [200, 0]})],
        )
        root = node(
            "VerticalContainer",
            "column",
            {},
            [fixed, node("Movie", "rest", {"StretchFactor": 1})],
        )
        measured = boxes(root)
        self.assertEqual(measured["fixed"]["height"], 100)
        self.assertEqual(
            tuple(measured["image"][key] for key in ("x", "y", "width", "height")),
            (150, 25, 200, 50),
        )
        self.assertEqual(measured["rest"]["height"], 100)

    def test_uncapped_local_requirement_survives_container_maximum(self):
        fixed = node(
            "FixedSizeContainer",
            "fixed",
            {"MaxSize": [120, 90]},
            [node("Movie", "image", {"MinSize": [200, 100]})],
        )
        measured = boxes(fixed)
        self.assertEqual(
            (measured["fixed"]["width"], measured["fixed"]["height"]), (120, 90)
        )
        self.assertEqual(
            tuple(measured["image"][key] for key in ("x", "y", "width", "height")),
            (-40, -5, 200, 100),
        )

    def test_screen_height_factor_example(self):
        fixed = node(
            "FixedSizeContainer",
            "fixed",
            {
                "EnableFixedHeight": 1,
                "FixedHeightFactor": 6.4,
                "EnableAspectRatio": 1,
                "AspectRatio": 0.6,
                "StretchFactor": 10.04,
            },
            [node("Movie", "image")],
        )
        image = boxes(fixed, 1280, 720)["image"]
        self.assertAlmostEqual(image["height"], 46.08)
        self.assertAlmostEqual(image["width"], 27.648)
