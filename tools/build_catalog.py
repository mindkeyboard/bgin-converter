"""Record observed property shapes and owners, without copying resource values."""

import sys
from pathlib import Path
from pprint import pformat

from bgin_json import load

observed = {}


def walk(node):
    for name, value in node.get("properties", {}).items():
        values = (
            value
            if isinstance(value, list) and value and isinstance(value[0], dict)
            else [value]
        )
        shapes = set()
        for v in values:
            shapes.add(
                "vector" + str(len(v))
                if isinstance(v, list)
                else next(iter(v), "empty")
                if isinstance(v, dict)
                else type(v).__name__
            )
        observed.setdefault(name, {}).setdefault(node["type"], set()).update(shapes)
    for group in ("children", "tracks"):
        for child in node.get(group, []):
            walk(child)


for path in Path(sys.argv[1]).glob("*.bgin"):
    for root in load(path)["screens"]:
        walk(root)
clean = {
    k: {t: sorted(s) for t, s in sorted(v.items())} for k, v in sorted(observed.items())
}
Path("src/bgin_json/observed.py").write_text(
    '"""Observed shapes only; absence does not mean a property is forbidden."""\nOBSERVED = '
    + pformat(clean, width=110, sort_dicts=True)
    + "\n",
    encoding="utf-8",
)
