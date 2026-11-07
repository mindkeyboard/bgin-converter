import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bgin_json import parse
from fixtures import document, node, prop, sprite_document, text

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None


@unittest.skipIf(Draft202012Validator is None, "Optional JSON Schema check requires jsonschema")
class SchemaTests(unittest.TestCase):
    def test_export_variants_and_rejected_bookkeeping(self):
        schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/bgin-json.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        for flags in range(64):
            validator.validate(parse(sprite_document(flags)))
        validator.validate(parse(document([node(properties=[prop(1024, 2, text("a") + text("b"))])])))
        doc = parse(document())
        doc["screens"][0]["type_hash"] = "forbidden"
        self.assertFalse(validator.is_valid(doc))
