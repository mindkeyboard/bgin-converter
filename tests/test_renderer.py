"""Layout and external-resource tests authored independently of the game corpus."""

import base64
import json
import struct
import tempfile
import unittest
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

from bgin_json import encode, parse
from bgin_json.catalog import catalog
from bgin_json.render import render
from bgin_json.render.resources import Resources
from bgin_json.render.scene import Scene, options
from bgin_json.render.sprites import Sprites, channel, easing, frame_color
from bgin_json.render.textures import decode
from bgin_json.rpc import Server

try:
    from PIL import Image
except ImportError:
    Image = None


def node(kind, name, props=None, children=None):
    n = {"type": kind, "name": name, "properties": props or {}}
    if children is not None:
        n["children"] = children
    return n


def document(root):
    return {"name": "authored", "screens": [root]}


@unittest.skipUnless(Image, "Renderer tests require the render extra")
class LayoutTests(unittest.TestCase):
    def test_margin_container_uses_full_size_ignores_absolute_margins_and_position(self):
        child = node("Movie", "child")
        child["transform"] = [999, -999, 0, 1, 1]
        doc = document(node("MarginContainer", "margin", {
            "MarginFactors": [10, 20, 30, 40], "Margins": [900, 800, 700, 600],
        }, [child]))
        before = deepcopy(doc)
        result = render(doc, {"width": 100, "height": 80})
        box = result["geometry"][1]
        self.assertEqual(tuple(box[key] for key in ("x", "y", "width", "height")), (10, 24, 70, 24))
        self.assertFalse(any("did not converge" in warning for warning in result["warnings"]))
        self.assertEqual(doc, before)

    def test_margin_factor_pairs_clamp_negatives_and_normalize_independently(self):
        cases = (
            ([200, 100, -30, 20], (200 / 3, 0, 0, 64)),
            ([-10, 20, 200, 100], (0, 160 / 3, 80, 0)),
        )
        for factors, expected in cases:
            doc = document(node("MarginContainer", "margin", {"MarginFactors": factors}, [node("Movie", "child")]))
            box = render(doc, {"width": 100, "height": 80})["geometry"][1]
            for key, target in zip(("x", "y", "width", "height"), expected):
                self.assertAlmostEqual(box[key], target)

    def test_margin_minimum_feeds_back_into_parent_allocation(self):
        margin = node("MarginContainer", "margin", {"MarginFactors": [10, 10, 0, 0]}, [node("Movie", "minimum", {"MinSize": [80, 0]})])
        doc = document(node("HorizontalContainer", "row", {}, [margin, node("Movie", "rest", {"StretchFactor": 1})]))
        result = render(doc, {"width": 200, "height": 80})
        boxes = {box["name"]: box for box in result["geometry"]}
        self.assertAlmostEqual(boxes["margin"]["width"], 100, delta=0.1)
        self.assertAlmostEqual(boxes["minimum"]["x"], 10, delta=0.1)
        self.assertAlmostEqual(boxes["rest"]["width"], 100, delta=0.1)
        self.assertFalse(any("did not converge" in warning for warning in result["warnings"]))

    def test_margin_feedback_is_bounded_and_maximum_caps_layout_minimum(self):
        doc = document(node("MarginContainer", "margin", {"MarginFactors": [100, 0, 0, 0]}, [node("Movie", "minimum", {"MinSize": [10, 0]})]))
        scene = Scene(doc, {"width": 100, "height": 80})
        from unittest.mock import patch

        with patch.object(scene, "_minimum_content", wraps=scene._minimum_content) as measure:
            result = scene.build()
        self.assertEqual(measure.call_count, 2, "Feedback must reuse content metrics")
        self.assertTrue(any("11 preview passes" in warning for warning in result["warnings"]))
        self.assertLessEqual(result["geometry"][0]["width"], 210)
        doc["screens"][0]["properties"]["MaxSize"] = [100, 80]
        capped = render(doc, {"width": 100, "height": 80})
        self.assertEqual(capped["geometry"][0]["width"], 100)
        self.assertFalse(any("did not converge" in warning for warning in capped["warnings"]))

    def test_label_margin_factors_use_widget_size_and_clip_text_locally(self):
        label = node("Label", "caption", {
            "TestString": "A very long caption for a narrow label" * 20,
            "TextPolicy": {"enum": "ScrollWrap"},
            "VerticalTextPolicy": {"enum": "HeightFactor"},
            "HeightFactor": 10,
            "MarginFactors": [-10, 20, 30, 40],
        })
        result = render(document(label), {"width": 100, "height": 80, "bounds": False})
        tree = ET.fromstring(result["svg"])
        text_clip = next(element for element in tree.iter() if element.tag.endswith("clipPath") and element.get("id", "").startswith("textClip"))
        rect = next(iter(text_clip))
        self.assertEqual(tuple(float(rect.get(key)) for key in ("x", "y", "width", "height")), (0, 24, 80, 24))
        text = next(element for element in tree.iter() if element.tag.endswith("text"))
        self.assertEqual(text.get("text-anchor"), "start")
        self.assertEqual(float(text.get("x")), 0)

    def test_height_factor_font_bounds_are_world_units_and_text_margins_are_separate(self):
        label = node("Button", "caption", {
            "TestString": "Text", "TextPolicy": {"enum": "ScrollWrap"},
            "VerticalTextPolicy": {"enum": "HeightFactor"}, "HeightFactor": 50,
            "FontHeight": [2, 3], "MarginFactors": [0, 0, 10, 20],
        })
        scene = Scene(document(label), {"width": 200, "height": 100, "pixelsPerMm": 2})
        self.assertEqual(scene.text_style(label)[1], 6)
        self.assertEqual(scene.minimum_content(label), (0, 50))
        label["properties"]["FontHeight"] = [2, 20]
        scene = Scene(document(label), {"width": 200, "height": 100, "pixelsPerMm": 2})
        # The text block is 50 high, so style fitting uses 35, while draw margins use 100.
        self.assertEqual(scene.text_style(label)[1], 35)
        tree = ET.fromstring(scene.build()["svg"])
        text = next(element for element in tree.iter() if element.tag.endswith("text"))
        self.assertAlmostEqual(float(text.get("y")), 10 + (70 - 35) * 0.5 + 35 * 0.86)

    def test_scrollwrap_buttons_do_not_expand_aspect_row_to_token_width(self):
        buttons = [
            node(
                "Button",
                str(i),
                {
                    "TestString": "$STR_" + "LONG_UNRESOLVED_NAME_" * 8,
                    "TextPolicy": {"enum": "ScrollWrap"},
                    "VerticalTextPolicy": {"enum": "HeightFactor"},
                    "HeightFactor": 7,
                    "StretchFactor": 1,
                },
            )
            for i in range(5)
        ]
        aspect = node(
            "AspectRatioContainer",
            "aspect",
            {"ItemAspectRatio": 0.15, "ItemAspectRatioMode": {"enum": "UnnamedOption3"}},
            [node("HorizontalContainer", "row", {}, buttons)],
        )
        stats = node(
            "VerticalContainer",
            "stats",
            {"StretchFactor": 41.18},
            [
                node("VerticalSpring", "top", {"StretchFactor": 70}),
                node("StackContainer", "classes", {"StretchFactor": 12.5}, [aspect]),
                node("VerticalSpring", "bottom", {"StretchFactor": 2}),
            ],
        )
        doc = document(
            node("HorizontalContainer", "root", {}, [stats, node("Movie", "rest", {"StretchFactor": 58.82})])
        )
        original = deepcopy(doc)
        result = render(doc, {"width": 1280, "height": 720})
        boxes = {box["name"]: box for box in result["geometry"]}
        self.assertAlmostEqual(boxes["stats"]["width"], 527.104)
        self.assertAlmostEqual(boxes["row"]["height"], 527.104 * 0.15)
        self.assertAlmostEqual(boxes["row"]["width"], 527.104)
        for i in range(5):
            self.assertAlmostEqual(boxes[str(i)]["width"], 527.104 / 5)
            self.assertAlmostEqual(boxes[str(i)]["height"], 527.104 * 0.15)
        self.assertEqual(doc, original)

    def test_aspect_modes_and_full_rectangle_centering(self):
        for mode, size in ((0, (400, 200)), (1, (100, 200))):
            doc = document(node("AspectRatioContainer", "aspect", {"ItemAspectRatioMode": mode, "ItemAspectRatio": 2}, [node("Movie", "child")]))
            child = render(doc, {"width": 400, "height": 200})["geometry"][1]
            self.assertEqual((child["width"], child["height"]), size)
        child = node("Movie", "child")
        child["transform"] = [11, 13, 0, 1, 1]
        doc = document(node("AspectRatioContainer", "aspect", {"ItemAspectRatioMode": 0, "ItemAspectRatio": 2, "Margins": [10, 30, 20, 40]}, [child]))
        child_box = render(doc, {"width": 400, "height": 240})["geometry"][1]
        self.assertEqual(tuple(child_box[k] for k in ("x", "y", "width", "height")), (30, 50, 360, 180))

    def test_widget_size_applies_maximum_after_minimum(self):
        doc = document(node("StackContainer", "limited", {"MinSize": [80, 90], "MaxSize": [40, 50]}))
        box = render(doc, {"width": 100, "height": 100})["geometry"][0]
        self.assertEqual((box["width"], box["height"]), (40, 50))

    def test_fixed_parameter_schemas(self):
        schemas = catalog()["schemas"]
        self.assertIn("AspectRatio", schemas["FixedSizeContainer"])
        self.assertIn("FontHeight", schemas["TextStyle"])
        self.assertNotIn("Alignment", schemas["AspectRatioContainer"])

    def test_preview_does_not_encode_entire_document(self):
        from unittest.mock import patch

        server = Server()
        doc = document(node("StackContainer", "root"))
        with patch(
            "bgin_json.rpc.encode", side_effect=AssertionError("unexpected encode")
        ):
            result = server.call("render", {"text": json.dumps(doc)})
        self.assertIn("timings", result)

    def test_selection_respects_full_parent_and_sibling_layout(self):
        doc = document(
            node(
                "HorizontalContainer",
                "root",
                {"Margins": [10, 20, 30, 40], "Spacing": 0},
                [
                    node("StackContainer", "left", {"StretchFactor": 1}),
                    node(
                        "StackContainer",
                        "right",
                        {"StretchFactor": 3},
                        [node("Movie", "leaf")],
                    ),
                ],
            )
        )
        before = deepcopy(doc)
        all_scene = render(doc, {"width": 430, "height": 200})
        part = render(
            doc, {"width": 430, "height": 200, "selected": "/screens/0/children/1"}
        )
        self.assertEqual(all_scene["geometry"], part["geometry"])
        right = part["geometry"][2]
        self.assertEqual(
            (right["x"], right["y"], right["width"], right["height"]),
            (110, 30, 300, 130),
        )
        self.assertNotIn('data-path="/screens/0/children/0"', part["svg"])
        self.assertIn('data-path="/screens/0/children/1/children/0"', part["svg"])
        self.assertEqual(doc, before)

    def test_hidden_objects_keep_space_and_parent_clips(self):
        doc = document(
            node(
                "HorizontalContainer",
                "r",
                {"ClipRender": 1},
                [
                    node("Movie", "hidden", {"Visible": 0, "StretchFactor": 1}),
                    node("Movie", "visible", {"StretchFactor": 1}),
                ],
            )
        )
        result = render(doc, {"width": 400, "height": 200})
        self.assertEqual(result["geometry"][2]["x"], 200)
        self.assertFalse(result["geometry"][1]["visible"])
        self.assertNotIn('data-path="/screens/0/children/0"', result["svg"])
        self.assertIn("clip-path=", result["svg"])

    def test_rtl_uses_full_width_including_gaps(self):
        doc = document(
            node(
                "HorizontalContainer",
                "r",
                {"EnableRightToLeftLayout": 1, "Spacing": 10},
                [
                    node("Movie", "a", {"StretchFactor": 1}),
                    node("Movie", "b", {"StretchFactor": 1}),
                ],
            )
        )
        result = render(
            doc, {"width": 200, "height": 100, "rtl": True, "pixelsPerMm": 1}
        )
        self.assertEqual(result["geometry"][1]["x"], 105)
        self.assertEqual(result["geometry"][2]["x"], 0)

    def test_size_is_not_a_minimum_hint(self):
        result = render(
            document(
                node(
                    "HorizontalContainer",
                    "r",
                    {},
                    [
                        node("Movie", "a", {"Size": [200, 200], "StretchFactor": 1}),
                        node("Movie", "b", {"Size": [200, 200], "StretchFactor": 1}),
                    ],
                )
            ),
            {"width": 100, "height": 50},
        )
        self.assertEqual(result["geometry"][1]["width"], 50)

    def test_percentage_factors_are_converted_by_loader(self):
        fixed = node(
            "FixedSizeContainer",
            "fixed",
            {"EnableFixedWidth": 1, "FixedWidthFactor": 25},
        )
        doc = document(
            node(
                "HorizontalContainer",
                "r",
                {},
                [fixed, node("Movie", "rest", {"StretchFactor": 1})],
            )
        )
        result = render(doc, {"width": 400, "height": 200})
        self.assertEqual(result["geometry"][1]["width"], 100)
        margin = document(
            node(
                "MarginContainer",
                "r",
                {"MarginFactors": [10, 20, 30, 5]},
                [node("Movie", "inside")],
            )
        )
        box = render(margin, {"width": 400, "height": 200})["geometry"][1]
        self.assertEqual(
            (box["x"], box["y"], box["width"], box["height"]), (40, 60, 280, 130)
        )

    def test_svg_escapes_editable_text(self):
        result = render(
            document(
                node("Label", "<script>", {"TestString": '<script>alert("x")</script>'})
            )
        )
        tree = ET.fromstring(result["svg"])
        self.assertFalse(tree.findall(".//{http://www.w3.org/2000/svg}script"))
        self.assertIn("&lt;script&gt;", result["svg"])

    def test_invalid_preview_options_are_errors(self):
        for bad in ({"width": float("nan")}, {"height": 100000}, {"clipping": 1}):
            with self.assertRaises(ValueError):
                render(document(node("Movie", "r")), bad)


@unittest.skipUnless(Image, "Renderer tests require the render extra")
class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def resource(self, name="assets", texture="atlas.png"):
        module = node(
            "Module",
            "piece",
            {"Position": [3, 1], "BakePosition": [1, 0], "Size": [2, 2]},
        )
        movie = {
            "type": "Movie",
            "name": "clip",
            "tracks": [
                {
                    "type": "MovieModule",
                    "name": "track",
                    "properties": {"Module": "/Pictures/atlas/piece"},
                    "keyframes": [],
                }
            ],
        }
        return {
            "name": name,
            "dialect": "sprites",
            "screens": [node("Sprite", "atlas", {"Source": texture}, [module, movie])],
        }

    def write(self, name, doc):
        p = self.root / name
        p.write_bytes(encode(doc))
        return str(p)

    def test_movie_atlas_pixels_are_not_a_layout_minimum(self):
        resource = self.resource()
        module = resource["screens"][0]["children"][0]
        module["properties"].update(Size=[128, 64], BakePosition=[0, 0])
        Image.new("RGBA", (128, 64), "white").save(self.root / "atlas.png")
        config = {"assetRoot": str(self.root), "bindings": {"Pictures": self.write("pictures.bgin", resource)}}
        doc = document(node("HorizontalContainer", "root", {}, [node("Movie", "a", {"Movie": "/Pictures/atlas/piece", "StretchFactor": 1}), node("Movie", "b", {"Movie": "/Pictures/atlas/piece", "StretchFactor": 1})]))
        result = render(doc, {"width": 64, "height": 32}, config)
        self.assertEqual([(box["width"], box["height"]) for box in result["geometry"][1:]], [(32, 32), (32, 32)])
        self.assertEqual(result["errors"], [])

    def test_separate_resource_folders_survive_renderer_rollback(self):
        texture_root = self.root / "external-textures"
        font_root = self.root / "external-fonts"
        texture_root.mkdir()
        font_root.mkdir()
        texture = texture_root / "atlas.png"
        Image.new("RGBA", (4, 2), (21, 43, 65, 255)).save(texture)
        font = font_root / "font.ttf"
        font.write_bytes(b"path-resolution fixture")
        resources = Resources(
            {"textureRoot": str(texture_root), "fontRoot": str(font_root)},
            "",
            set(),
        )
        self.assertEqual(resources.resolve_file("exported/atlas.png"), texture)
        self.assertEqual(resources.resolve_file("font.ttf", "texter_fonts"), font)
        sprite = self.resource()["screens"][0]
        self.assertEqual(resources.texture(sprite, False).getpixel((0, 0)), (21, 43, 65, 255))

    def test_named_bindings_are_explicit_and_can_reference_many_files(self):
        one = self.write("one.bgin", self.resource())
        two = self.write(
            "two.bgin", document(node("TextStyle", "caption", {"FontHeight": [2, 18]}))
        )
        r = Resources({"bindings": {"Pictures": one, "MyStyles": two}}, "", set())
        self.assertEqual(r.lookup("/Pictures/atlas/piece")[1]["type"], "Module")
        self.assertEqual(r.style("/MyStyles/caption")["FontHeight"], [2, 18])
        with self.assertRaises(KeyError):
            r.lookup("/Sprites/atlas/piece")
        auto = Resources({}, str(self.root / "menu.bgin"), set())
        self.assertFalse(auto.bindings, "No adjacent/built-in resource auto-binding")

    def test_missing_files_and_missing_objects_have_diagnostic_paths(self):
        r = render(
            document(node("Movie", "r", {"Movie": "/Pictures/atlas/absent"})),
            resources={"bindings": {"Pictures": str(self.root / "absent.bgin")}},
        )
        self.assertTrue(any("Pictures" in e["message"] for e in r["errors"]))
        self.assertTrue(
            any(e["path"] == "/screens/0/properties/Movie" for e in r["errors"])
        )

    def test_resource_reload_observes_changed_file(self):
        doc = self.resource()
        p = self.write("source.bgin", doc)
        cfg = {"bindings": {"Pictures": p}}
        r = Resources(cfg, "", set())
        self.assertEqual(
            r.lookup("/Pictures/atlas/piece")[1]["properties"]["Size"], [2, 2]
        )
        doc["screens"][0]["children"][0]["properties"]["Size"] = [3, 2]
        Path(p).write_bytes(encode(doc))
        r.configure(cfg, "", set())
        self.assertEqual(
            r.lookup("/Pictures/atlas/piece")[1]["properties"]["Size"], [3, 2]
        )

    def test_crop_alpha_and_shared_svg_image(self):
        atlas = Image.new("RGBA", (4, 2), (255, 0, 0, 255))
        atlas.putpixel((1, 0), (0, 255, 0, 255))
        atlas.save(self.root / "atlas.png")
        mask = Image.new("RGB", (4, 2), (64, 0, 0))
        mask.save(self.root / "atlas.png__alpha", format="PNG")
        cfg = {
            "assetRoot": str(self.root),
            "bindings": {"Pictures": self.write("source.bgin", self.resource())},
        }
        doc = document(
            node(
                "StackContainer",
                "r",
                children=[
                    node("Movie", "a", {"Movie": "/Pictures/atlas/clip"}),
                    node("Movie", "b", {"Movie": "/Pictures/atlas/clip"}),
                ],
            )
        )
        result = render(doc, resources=cfg)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["svg"].count("data:image/png;base64,"), 1)
        tree = ET.fromstring(result["svg"])
        image = tree.find(".//{http://www.w3.org/2000/svg}image")
        decoded = Image.open(
            BytesIO(base64.b64decode(image.attrib["href"].split(",")[1]))
        )
        self.assertEqual(decoded.size, (2, 2))
        self.assertEqual(decoded.getpixel((0, 0)), (0, 255, 0, 64))

    def test_nine_patch_preserves_border_pixels_under_scale(self):
        sprites = Sprites(Resources({}, "", set()), options({}), set())
        markup = sprites.image(
            "#crop",
            {"NinePatchMode": {"enum": "Classic"}, "NinePatchDef": [2, 3, 1, 2]},
            (10, 10),
            (2, 2),
        )
        tree = ET.fromstring("<g>" + markup + "</g>")
        patches = list(tree)
        self.assertEqual(len(patches), 9)
        self.assertEqual(
            (patches[0].get("width"), patches[0].get("height")), ("1", "0.5")
        )
        self.assertEqual(patches[0].get("viewBox"), "0 0 2 1")

    def test_png_cache_is_reused_and_invalidates_on_texture_change(self):
        import os
        from unittest.mock import patch

        from bgin_json.render.resources import png_uri

        path = self.root / "atlas.png"
        Image.new("RGBA", (4, 2), (255, 0, 0, 255)).save(path)
        resource = Resources({"assetRoot": str(self.root)}, "", set())
        root = self.resource()["screens"][0]
        with patch("bgin_json.render.resources.png_uri", wraps=png_uri) as convert:
            first = resource.png(root, True, (1, 0, 2, 2))
            self.assertEqual(resource.png(root, True, (1, 0, 2, 2)), first)
            self.assertEqual(convert.call_count, 1)
            stamp = path.stat().st_mtime_ns
            Image.new("RGBA", (4, 2), (0, 255, 0, 255)).save(path)
            os.utime(path, ns=(stamp + 1000000000, stamp + 1000000000))
            self.assertNotEqual(resource.png(root, True, (1, 0, 2, 2)), first)
            self.assertEqual(convert.call_count, 2)

    def test_raw_pvr_etc_and_bad_texture_headers(self):
        raw = struct.pack("<4I", 666, 2, 1, 3) + bytes([255, 0, 0, 0, 255, 0])
        self.assertEqual(
            [decode(raw).getpixel((i, 0)) for i in range(2)],
            [(255, 0, 0, 255), (0, 255, 0, 255)],
        )
        fmt = int.from_bytes(b"rgba" + bytes([8, 8, 8, 8]), "little")
        pvr = struct.pack(
            "<IIQ9I", 0x03525650, 0, fmt, 0, 0, 1, 2, 1, 1, 1, 1, 0
        ) + bytes([1, 2, 3, 255, 4, 5, 6, 127])
        self.assertEqual(decode(pvr).getpixel((1, 0)), (4, 5, 6, 127))

        etc = struct.pack(
            "<IIQ9I", 0x03525650, 0, 6, 0, 0, 4, 4, 1, 1, 1, 1, 0
        ) + bytes(8)
        self.assertEqual(decode(etc).size, (4, 4))
        for invalid in (b"PVR\x03", etc[:-1], struct.pack("<4I", 666, 100000, 1, 3)):
            with self.assertRaises(ValueError):
                decode(invalid)


class ProtocolTests(unittest.TestCase):
    def test_edited_json_encode_decode_and_failure_response(self):
        server = Server()
        doc = document(node("Movie", "r"))
        result = server.call("encode", {"text": json.dumps(doc)})
        self.assertEqual(
            json.loads(server.call("decode", result)["text"]), parse(encode(doc))
        )
        self.assertIn(
            "error",
            server.response(
                {"id": 1, "method": "encode", "params": {"text": '{"screens": [}'}}
            ),
        )
        self.assertIn(
            "error",
            server.response(
                {
                    "id": 2,
                    "method": "encode",
                    "params": {"text": '{"name":"x","name":"y"}'},
                }
            ),
        )

    def test_loader_catalog_contains_unobserved_parameters(self):
        c = catalog()
        self.assertIn("Toggleable", c["properties"])
        self.assertIn("Button", c["properties"]["Toggleable"]["appliesTo"])
        self.assertIn(
            "HorizontalContainer", c["properties"]["StretchFactor"]["appliesTo"]
        )

    def test_interpolation_indices_match_gin_loader(self):
        self.assertEqual(easing(0.5, 0), 0)
        self.assertEqual(easing(0.5, 1), 0.5)
        self.assertEqual(easing(0.5, 4), 0.25)
        track = {
            "keyframes": [
                {"frame": 0, "position": {"value": [0, 0], "interpolation": 1}},
                {"frame": 10, "position": {"value": [10, 20]}},
            ]
        }
        self.assertEqual(channel(track, "position", 5, [0, 0]), [5, 10])

    def test_movie_color_comes_from_keyframes(self):
        track = {
            "properties": {"Color": [0, 0, 0, 0]},
            "keyframes": [
                {"frame": 0, "colors": {"Color": [1, 0, 0, 0]}},
                {"frame": 10, "colors": {"Color": [0, 1, 0, 1]}},
            ],
        }
        self.assertEqual(frame_color(track, 5), (0.5, 0.5, 0, 0.5))
        self.assertEqual(frame_color(track, 5, False), (1, 0, 0, 0))

    def test_new_loader_properties_have_correct_wire_types(self):
        from bgin_json import _wire

        raw = encode(
            document(
                node(
                    "Switch",
                    "r",
                    {
                        "EnabledTextStyle": "/Styles/white",
                        "Toggleable": 1,
                        "DisabledMargin": 3,
                    },
                )
            )
        )
        props = _wire.parse(raw)["screens"][0]["root"]["properties"]
        self.assertEqual(int(props[0]["kind"], 16), 8)
        self.assertEqual(
            parse(raw)["screens"][0]["properties"]["EnabledTextStyle"], "/Styles/white"
        )


if __name__ == "__main__":
    unittest.main()
