"""Exercise every screen in an external corpus without changing its files."""

import argparse
import json
import time
from pathlib import Path

from bgin_json import dumps, load
from bgin_json.rpc import Server

cli = argparse.ArgumentParser(description=__doc__)
cli.add_argument("corpus", type=Path)
cli.add_argument("--assets", type=Path, required=True)
args = cli.parse_args()
assets = args.assets.resolve()
config = dict(
    assetRoot=str(assets),
    bindings={
        name: str(assets / "gui" / (name.lower() + ".bgin"))
        for name in ("Widgets", "Sprites")
    },
)
server = Server()
count = 0
failures = []
resource_errors = 0
start = time.monotonic()
for path in sorted(args.corpus.glob("*.bgin")):
    try:
        doc = load(path)
        for i in range(len(doc["screens"])):
            result = server.call(
                "render",
                dict(
                    text=dumps(doc),
                    source=str(path.resolve()),
                    resources=config,
                    options=dict(screen=i),
                ),
            )
            assert result["svg"].startswith("<svg")
            count += 1
            resource_errors += len(result["errors"])
    except Exception as e:
        failures.append(dict(file=path.name, error=str(e)))
print(
    json.dumps(
        dict(
            screens=count,
            failures=failures,
            resourceErrors=resource_errors,
            seconds=round(time.monotonic() - start, 2),
        ),
        ensure_ascii=True,
    )
)
raise SystemExit(bool(failures))
