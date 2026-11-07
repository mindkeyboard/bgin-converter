"""Local line-delimited protocol shared by the editor and host tests."""

import base64
import importlib
import json
import sys
import time
from pathlib import Path

from . import dumps, encode, parse
from .export import _constant, _pairs
from .drafts import draft_warnings

MAX_LINE = 96 * 1024 * 1024


def document(text):
    if len(text) > 64 * 1024 * 1024:
        raise ValueError("Document exceeds 64 MiB")
    return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)


class Server:
    def __init__(self):
        self.cache_key = None
        self.cache = None
        self.last_text = None
        self.last_document = None
        self.last_validated = False

    def call(self, method, p):
        if method == "decode":
            decoded = parse(base64.b64decode(p["data"], validate=True))
            return {"text": dumps(decoded), "warnings": draft_warnings(decoded)}
        if method == "catalog":
            from .catalog import catalog
            from .render.scene import DEFAULTS

            return dict(**catalog(), defaults=DEFAULTS)
        if method == "ping":
            for module in ("PIL.Image", "texture2ddecoder"):
                importlib.import_module(module)

            return {"ready": True}
        if method == "convert":
            from .file_conversion import convert_saved_file

            expected = p.get("expected")
            return convert_saved_file(
                p["source"], p["destination"], p["to"],
                overwrite=p.get("overwrite", False),
                expected=base64.b64decode(expected, validate=True) if expected is not None else None,
            )
        started = time.perf_counter()
        if p["text"] == self.last_text:
            doc = self.last_document
        else:
            doc = document(p["text"])
            self.last_text, self.last_document = p["text"], doc
            self.last_validated = False
        if method == "encode":
            from .file_conversion import verified_binary
            binary = verified_binary(doc)
            self.last_validated = True
            return {"data": base64.b64encode(binary).decode("ascii")}
        if method == "validate":
            if not self.last_validated:
                encode(doc)
                self.last_validated = True
            return {"valid": True, "warnings": draft_warnings(doc)}
        if method == "render":
            from .render.resources import Resources
            from .render.scene import render

            config, source = p.get("resources", {}), p.get("source", "")
            key = (json.dumps(config, sort_keys=True), str(Path(source).parent))
            if key != self.cache_key:
                self.cache = Resources(config, source, set())
                self.cache_key = key
            parsed = time.perf_counter()
            result = render(doc, p.get("options"), config, source, self.cache)
            result.setdefault("timings", {})["documentMs"] = round((parsed - started) * 1000, 2)
            result["timings"]["totalMs"] = round(
                (time.perf_counter() - started) * 1000, 2
            )
            return result
        raise ValueError("Unknown request: " + method)

    def response(self, request):
        try:
            return {
                "id": request["id"],
                "result": self.call(request["method"], request.get("params", {})),
            }
        except Exception as e:  # noqa: BLE001 - A failed request must not stop the RPC worker.
            error = {"message": str(e), "path": getattr(e, "path", "/")}
            if isinstance(e, json.JSONDecodeError):
                error.update(line=e.lineno - 1, column=e.colno - 1)
            return {"id": request.get("id"), "error": error}


def main():
    server = Server()
    for raw in sys.stdin.buffer:
        try:
            if len(raw) > MAX_LINE:
                raise ValueError("Request exceeds protocol budget")
            request = json.loads(raw)
            response = server.response(request)
        except Exception as e:  # noqa: BLE001 - Malformed protocol input must produce a reply.
            response = {"id": None, "error": {"message": str(e)}}
        sys.stdout.write(
            json.dumps(response, ensure_ascii=True, allow_nan=False) + "\n"
        )
        sys.stdout.flush()


if __name__ == "__main__":
    main()
