from __future__ import annotations

import argparse
import json
import sys

from .export import convert_file, dumps
from .parser import BginError, Limits, load
from .drafts import draft_warnings


def main(argv=None):
    parser = argparse.ArgumentParser(description="Convert Binary GIN <-> editable JSON")
    parser.add_argument("input")
    parser.add_argument("-o", "--output")
    parser.add_argument("--to", choices=("json", "bgin"), help="Default: infer from input extension")
    parser.add_argument("--dialect", choices=("auto", "ui", "templates", "sprites"), default="auto")
    parser.add_argument("--force", action="store_true", help="Replace an existing destination")
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--max-bytes", type=int, default=Limits().max_bytes)
    parser.add_argument("--max-depth", type=int, default=Limits().max_depth)
    args = parser.parse_args(argv)
    direction = args.to or ("bgin" if args.input.lower().endswith(".json") else "json")
    if direction == "bgin" and not args.output:
        parser.error("JSON to BGIN requires -o")
    if args.force and not args.output:
        parser.error("--force requires -o")
    try:
        limits = Limits(max_bytes=args.max_bytes, max_depth=args.max_depth)
        indent = None if args.compact else 2
        if args.output:
            document = convert_file(args.input, args.output, to=direction, dialect=args.dialect,
                         limits=limits, overwrite=args.force, indent=indent)
        else:
            document = load(args.input, dialect=args.dialect, limits=limits)
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8")
            sys.stdout.write(dumps(document, indent=indent))
        for warning in draft_warnings(document):
            print("Warning: " + warning["message"], file=sys.stderr)
        return 0
    except BginError as e:
        print(json.dumps({"error": e.message, "path": e.path, "offset": e.offset}, ensure_ascii=True), file=sys.stderr)
    except (OSError, ValueError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=True), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
