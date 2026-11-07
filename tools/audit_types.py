"""Compare all external BGIN node types with the fixed editor catalog.

Run with PYTHONPATH=src: python tools/audit_types.py EXTERNAL_FOLDER
Only names and occurrence counts are emitted; game values are not copied.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from bgin_json import load
from bgin_json.catalog import catalog


def audit(root: Path) -> dict:
    counts: Counter[str] = Counter()
    roots: Counter[str] = Counter()
    errors = []
    files = 0
    for path in sorted(root.rglob("*.bgin")):
        try:
            document = load(path)
            files += 1
            stack = list(document["screens"])
            roots.update(node["type"] for node in stack)
            while stack:
                node = stack.pop()
                counts[node["type"]] += 1
                for group in ("children", "tracks"):
                    stack.extend(node.get(group, []))
        except Exception as error:
            errors.append({"file": str(path.relative_to(root)), "error": str(error)})
    known = set(catalog()["types"])
    return {
        "files": files,
        "types": dict(sorted(counts.items())),
        "rootTypes": dict(sorted(roots.items())),
        "unknownTypes": sorted(set(counts) - known),
        "notObserved": sorted(known - set(counts)),
        "errors": errors,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    if not args.folder.is_dir():
        parser.error("The external BGIN folder does not exist")
    result = audit(args.folder)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(1 if result["errors"] or result["unknownTypes"] or not result["files"] else 0)
