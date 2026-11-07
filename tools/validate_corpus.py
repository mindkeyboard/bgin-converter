"""Independent byte and edit validation. Input game files are never modified."""
import argparse
import copy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bgin_json import dumps, encode, parse
from bgin_json.parser import jet_hash


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("corpus", type=Path)
    cli.add_argument("--reference-workspace", type=Path, required=True)
    args = cli.parse_args()
    sys.path.insert(0, str(args.reference_workspace.resolve()))
    from tools.bgin_core import decode_document, encode_document
    files, edited, failures = 0, 0, []
    for path in sorted(args.corpus.glob("*.bgin")):
        try:
            raw = path.read_bytes()
            doc = json.loads(dumps(parse(raw)))
            rebuilt = encode(doc)
            if rebuilt != raw:
                raise ValueError("BGIN -> JSON -> BGIN differs from input")
            reference = decode_document(rebuilt)
            if encode_document(reference, force=True) != rebuilt:
                raise ValueError("Independent codec did not reproduce the output")
            for screen in reference.screens:
                if any(not n.decoded for n in screen.node.structural_nodes()):
                    raise ValueError("Independent decoder left opaque nodes")
            files += 1
            # Renaming changes the directory identity and the byte length of an actual root.
            changed = copy.deepcopy(doc)
            changed["screens"][0]["name"] += "_converter_test"
            output = encode(changed)
            reference = decode_document(output)
            if reference.screens[0].node.name != changed["screens"][0]["name"]:
                raise ValueError("Edited name was lost")
            if reference.screens[0].name_hash != jet_hash(reference.screens[0].node.name):
                raise ValueError("Directory identity was not rebuilt")
            if encode_document(reference, force=True) != output:
                raise ValueError("Independent codec rejected the edited output")
            if parse(output) != changed:
                raise ValueError("Edited document changed on reimport")
            edited += 1
        except Exception as e:
            failures.append({"file": path.name, "error": str(e)})
    if not files and not failures:
        failures.append({"error": "No BGIN files found"})
    print(json.dumps({"files": files, "edits": edited, "failures": failures}, ensure_ascii=True))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
