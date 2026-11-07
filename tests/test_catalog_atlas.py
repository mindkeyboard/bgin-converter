"""The editor parameter contract must agree with the engine and with real files."""
import unittest
from pathlib import Path

from bgin_json import encode, parse
from bgin_json.catalog import catalog
from bgin_json.engine_params import ENGINE_ENUMS
from bgin_json.parser import jet_hash
from bgin_json.vocabulary import ENUMS, PROPERTY_NAMES

CORPUS = Path(__file__).resolve().parents[2] / "inputs/bgin/corpus"


def values(spec):
    return {option["value"] for option in spec["options"]}


class ParameterContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = catalog()
        cls.parameters = cls.data["parameters"]

    def test_every_loader_parameter_has_a_type(self):
        for obj, names in self.data["schemas"].items():
            self.assertEqual(sorted(self.parameters[obj]), names, obj)

    def test_types_are_scoped_by_object(self):
        p = self.parameters
        self.assertEqual(p["FixedSizeContainer"]["EnableFixedWidth"]["type"], "bool")
        self.assertEqual(p["HorizontalSpring"]["MinSize"]["type"], "float")
        self.assertEqual(p["StackContainer"]["MinSize"]["type"], "vector")
        self.assertEqual(p["GridContainer"]["ColumnCount"], {**p["GridContainer"]["ColumnCount"], "type": "integer", "min": 1})
        self.assertEqual(p["Label"]["MarginFactors"]["unit"], "%")
        self.assertEqual(p["TextStyle"]["PrimaryColor"]["type"], "color")
        self.assertTrue(p["ScrollContainer"]["SnapAtEdges"]["noEffect"])
        self.assertEqual(self.data["properties"]["EnableFixedWidth"]["kind"], "number")

    def test_enum_domains_come_from_the_loader(self):
        p = self.parameters
        self.assertEqual(len(p["Label"]["Alignment"]["options"]), 9)
        self.assertEqual(values(p["Movie"]["Alignment"]), {"Center", "TopOrLeft", "BottomOrRight"})
        self.assertIn("Vertical", values(p["GridContainer"]["Direction"]))
        self.assertEqual(values(p["ScrollContainer"]["BarVisibility"]), {"Hidden", "AutoHide", "Always"})
        self.assertEqual(len(p["TransformContainer"]["InterpolationMode"]["options"]), 13)

    def test_engine_names_keep_their_hashes(self):
        names = {name: code for code, name in PROPERTY_NAMES.items()}
        for name, options in ENGINE_ENUMS.items():
            for option in options:
                if not option[0].startswith("Unnamed"):
                    self.assertEqual(jet_hash(option[0]), names[option[0]], (name, option[0]))

    def test_every_option_token_round_trips(self):
        for obj, parameters in self.parameters.items():
            for name, spec in parameters.items():
                for option in spec.get("options", []):
                    doc = {"name": "n", "screens": [{"name": "s", "type": "StackContainer", "properties": {}, "children": [
                        {"name": "o", "type": "Label", "properties": {name: option["token"]}},
                    ]}]}
                    self.assertEqual(parse(encode(doc))["screens"][0]["children"][0]["properties"][name], option["token"], (obj, name))

    def test_old_alias_still_writes_the_same_value(self):
        for label in ("UnnamedOption3", "Vertical"):
            doc = {"name": "n", "screens": [{"name": "s", "type": "GridContainer", "properties": {"Direction": {"enum": label}}, "children": []}]}
            self.assertEqual(parse(encode(doc))["screens"][0]["properties"]["Direction"], {"enum": "Vertical"})
        self.assertEqual(ENUMS["Direction"]["UnnamedOption3"], ENUMS["Direction"]["Vertical"])

    def test_numeric_boolean_round_trip(self):
        doc = {"name": "example", "screens": [{"name": "screen", "type": "FixedSizeContainer", "properties": {"EnableFixedWidth": 1, "Visible": 0}, "children": []}]}
        self.assertEqual(parse(encode(doc))["screens"][0]["properties"], doc["screens"][0]["properties"])

    @unittest.skipUnless(CORPUS.exists(), "game corpus is not available")
    def test_game_files_fit_the_contract(self):
        def fits(spec, value):
            if spec["type"] in ("enum", "font"):
                return isinstance(value, dict) and value.get("enum") in values(spec)
            if spec["type"] == "bool":
                return value in (0, 1)
            if spec["type"] == "integer":
                return value == int(value)
            if spec["type"] == "float":
                return isinstance(value, (int, float))
            if spec["type"] == "vector":
                return isinstance(value, list) and len(value) == len(spec["fields"])
            if spec["type"] == "color":
                return isinstance(value, list) and len(value) == 4 and all(0 <= part <= 1 for part in value)
            return isinstance(value, str)

        def visit(node):
            props = node.get("properties") or {}
            for row in props if isinstance(props, list) else [props]:
                for name, value in row.items():
                    spec = self.parameters[node["type"]].get(name)
                    if spec:
                        self.assertTrue(fits(spec, value), (node["type"], name, value))
            for child in node.get("children") or []:
                visit(child)

        for path in CORPUS.rglob("*.bgin"):
            for screen in parse(path.read_bytes())["screens"]:
                visit(screen)


if __name__ == "__main__":
    unittest.main()
