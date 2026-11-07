"""Measure cold/warm render requests against explicit external assets."""

import argparse
import cProfile
import io
import json
import pstats
import time
from pathlib import Path

from bgin_json import dumps, load
from bgin_json.rpc import Server

cli = argparse.ArgumentParser(description=__doc__)
cli.add_argument("file", type=Path)
cli.add_argument("--assets", type=Path, required=True)
cli.add_argument("--screen", type=int, default=0)
cli.add_argument("--output", type=Path)
cli.add_argument("--profile", action="store_true", help="Profile the first request; adds measurement overhead")
args = cli.parse_args()
assets = args.assets.resolve()
server = Server()
params = {
    "text": dumps(load(args.file)),
    "source": str(args.file.resolve()),
    "options": {"screen": args.screen},
    "resources": {
        "assetRoot": str(assets),
        "bindings": {
            n: str(assets / "gui" / (n.lower() + ".bgin"))
            for n in ("Widgets", "Sprites")
        },
    },
}
profile = cProfile.Profile()
runs = []
for i in range(3):
    start = time.perf_counter()
    if i == 0 and args.profile:
        profile.enable()
    result = server.call("render", params)
    if i == 0 and args.profile:
        profile.disable()
    runs.append(
        {
            "seconds": round(time.perf_counter() - start, 4),
            "bytes": len(result["svg"]),
            "nodes": len(result["geometry"]),
            "timings": result.get("timings"),
        }
    )
out = io.StringIO()
if args.profile:
    pstats.Stats(profile, stream=out).sort_stats("cumulative").print_stats(22)
report = json.dumps(runs, indent=2) + "\n" + out.getvalue()
if args.output:
    args.output.write_text(report, encoding="utf-8")
print(report)
