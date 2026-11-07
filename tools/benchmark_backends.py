"""Compare interpreter and optional native RPC workers against the same external resources."""

import argparse
import base64
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path


class Worker:
    def __init__(self, command, env):
        self.next_id = 0
        self.lines = queue.Queue()
        self.errors = []
        started = time.perf_counter()
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.spawn_ms = (time.perf_counter() - started) * 1000

        def read():
            for line in self.process.stdout:
                self.lines.put(line)
            self.lines.put(None)

        def errors():
            self.errors.extend(self.process.stderr)

        threading.Thread(target=read, daemon=True).start()
        threading.Thread(target=errors, daemon=True).start()

    def call(self, method, params=None):
        self.next_id += 1
        started = time.perf_counter()
        self.process.stdin.write(
            json.dumps({"id": self.next_id, "method": method, "params": params or {}})
            + "\n"
        )
        self.process.stdin.flush()
        try:
            line = self.lines.get(timeout=120)
        except queue.Empty:
            raise RuntimeError("Timed out waiting for " + method) from None
        if line is None:
            raise RuntimeError("Worker exited: " + "".join(self.errors))
        response = json.loads(line)
        if response.get("id") != self.next_id:
            raise RuntimeError("Unexpected response identity")
        if "error" in response:
            raise RuntimeError(str(response["error"]))
        return response["result"], round((time.perf_counter() - started) * 1000, 3)

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(self.process.pid), "/T", "/F"], check=False
                )
            else:
                self.process.kill()
            self.process.wait()


def run(command, env, raw, source, assets, screen):
    started = time.perf_counter()
    worker = Worker(command, env)
    results = {}
    metrics = {"command": command, "spawnMs": round(worker.spawn_ms, 3)}
    try:
        results["ping"], metrics["pingMs"] = worker.call("ping")
        metrics["readyMs"] = round((time.perf_counter() - started) * 1000, 3)
        results["decode"], metrics["decodeMs"] = worker.call(
            "decode", {"data": base64.b64encode(raw).decode("ascii")}
        )
        results["catalog"], metrics["catalogMs"] = worker.call("catalog")
        params = {
            "text": results["decode"]["text"],
            "source": str(source),
            "options": {"screen": screen},
            "resources": {
                "assetRoot": str(assets),
                "bindings": {
                    name: str(assets / "gui" / (name.lower() + ".bgin"))
                    for name in ("Widgets", "Sprites")
                },
            },
        }
        metrics["renderMs"] = []
        metrics["renderTimings"] = []
        for _ in range(4):
            rendered, elapsed = worker.call("render", params)
            metrics["renderMs"].append(elapsed)
            metrics["renderTimings"].append(rendered.pop("timings", None))
            if "render" in results and results["render"] != rendered:
                raise AssertionError("Cold and warm render results differ")
            results["render"] = rendered
        results["encode"], metrics["encodeMs"] = worker.call(
            "encode", {"text": params["text"]}
        )
        if base64.b64decode(results["encode"]["data"]) != raw:
            raise AssertionError("Encoded output differs from the original binary")
        metrics["svgBytes"] = len(results["render"]["svg"].encode("utf-8"))
        metrics["nodes"] = len(results["render"]["geometry"])
        return results, metrics
    finally:
        worker.close()


def main():
    root = Path(__file__).resolve().parents[1]
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--python", type=Path, default=Path(sys.executable))
    cli.add_argument("--native", type=Path, required=True)
    cli.add_argument("--file", type=Path, required=True)
    cli.add_argument("--assets", type=Path, required=True)
    cli.add_argument("--screen", type=int, default=0)
    cli.add_argument("--native-first", action="store_true")
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    env = dict(os.environ, PYTHONPATH=str(root / "src"), PYTHONIOENCODING="utf-8")
    source, assets = args.file.resolve(), args.assets.resolve()
    commands = [
        ("interpreter", [str(args.python.resolve()), "-u", "-m", "bgin_json.rpc"]),
        ("compiled", [str(args.native.resolve())]),
    ]
    if args.native_first:
        commands.reverse()
    measurements = {}
    for label, command in commands:
        worker_env = dict(env)
        if label == "compiled":
            # The standalone worker must not resolve the source tree or a local Python installation.
            worker_env.pop("PYTHONPATH", None)
            worker_env.pop("PYTHONHOME", None)
            worker_env["PYTHONNOUSERSITE"] = "1"
        measurements[label] = run(
            command, worker_env, source.read_bytes(), source, assets, args.screen
        )
    interpreted, baseline = measurements["interpreter"]
    compiled, native = measurements["compiled"]
    for key in ("ping", "decode", "catalog", "render", "encode"):
        if interpreted[key] != compiled[key]:
            raise AssertionError("Interpreter and compiled output differ for " + key)
    dist = args.native.resolve().parent
    report = {
        "source": str(source),
        "assets": str(assets),
        "screen": args.screen,
        "order": [label for label, _ in commands],
        "matching": [
            "ping",
            "decoded JSON",
            "catalog",
            "SVG",
            "geometry",
            "encoded original binary",
        ],
        "packageBytes": sum(
            path.stat().st_size for path in dist.rglob("*") if path.is_file()
        ),
        "packageFiles": sum(1 for path in dist.rglob("*") if path.is_file()),
        "interpreter": baseline,
        "compiled": native,
        "notes": "RPC round-trip includes request/response JSON, IPC and response parsing. Cold/warm mean process resource caches; operating-system file caches are not cleared.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
