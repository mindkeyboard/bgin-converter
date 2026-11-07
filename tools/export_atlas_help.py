"""Snapshot Engine Atlas parameter descriptions into src/bgin_json/parameter_help.json."""
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bgin_json.engine_params import OBJECT_CLASSES  # noqa: E402

DATABASE = ROOT.parent / "engine-atlas/data/engine-atlas.sqlite"
OUTPUT = ROOT / "src/bgin_json/parameter_help.json"
LANGUAGE_FAMILIES = {
    "FontNameJA и др.": ["FontNameAR", "FontNameID", "FontNameJA", "FontNameKO", "FontNameRU",
                         "FontNameTH", "FontNameTR", "FontNameZH", "FontNameZH_HANT"],
    "FontScalingJA и др.": ["FontScalingAR", "FontScalingID", "FontScalingJA", "FontScalingKO",
                            "FontScalingRU", "FontScalingTH", "FontScalingTR", "FontScalingZH",
                            "FontScalingZH_HANT"],
    "FillBackground0–2": ["FillBackground0", "FillBackground1", "FillBackground2"],
}


def named(title):
    inner = re.search(r"\(([^()]*)\)\s*$", title)
    if not inner:
        return []
    text = inner.group(1)
    return LANGUAGE_FAMILIES.get(text) or re.findall(r"\b[A-Z][A-Za-z0-9_]+\b", text)


def records(connection):
    rows = connection.execute(
        """select c.qualified_name, r.kind, r.name, r.content_json, r.localizations_json
           from reference_records r join classes c on c.id = r.class_id
           where r.confirmation = 'confirmed' and r.kind = 'property' and c.qualified_name like 'gin::%'"""
    )
    for owner, _, title, content, localizations in rows:
        summary = json.loads(content).get("summary")
        english = (json.loads(localizations or "{}").get("en") or {}).get("content") or {}
        names = named(title) or re.findall(r"Параметр BGIN `(\w+)`", summary or "")
        for name in names:
            yield owner, name, {"ru": summary, "en": english.get("summary") or ""}


def main():
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    by_class = {}
    for owner, name, text in records(connection):
        by_class.setdefault(owner, {})[name] = text
    result = {}
    for obj, classes in OBJECT_CLASSES.items():
        result[obj] = {}
        for owner in reversed(classes):
            result[obj].update(by_class.get(owner, {}))
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=0, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
