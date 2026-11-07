"""Atomic publication for both conversion directions."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .parser import BginError, Limits, load
from .writer import encode


def dumps(document: dict, *, indent=2) -> str:
    def scalar(value):
        return json.dumps(value, ensure_ascii=False, allow_nan=False)

    if indent is None:
        return scalar(document) + "\n"
    if type(indent) is not int or not 0 <= indent <= 8:
        raise ValueError("indent must be None or an integer from 0 to 8")

    def render(value, depth):
        prefix = " " * (depth * indent)
        child = " " * ((depth + 1) * indent)
        if isinstance(value, dict) and value:
            if set(value) <= {"enum", "value", "text"}:
                return scalar(value)
            parts = [child + scalar(k) + ": " + render(v, depth + 1) for k, v in value.items()]
            return "{\n" + ",\n".join(parts) + "\n" + prefix + "}"
        if isinstance(value, list) and value and any(isinstance(v, (dict, list)) for v in value):
            return "[\n" + ",\n".join(child + render(v, depth + 1) for v in value) + "\n" + prefix + "]"
        return scalar(value)

    return render(document, 0) + "\n"


def _pairs(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise BginError(f"Duplicate JSON key: {name}", 0, "/", "invalid_json")
        result[name] = value
    return result


def _constant(value):
    raise BginError(f"Invalid JSON constant: {value}", 0, "/", "invalid_json")


def load_json(path: str | Path, *, limits: Limits | None = None):
    limits = limits or Limits()
    with Path(path).open("rb") as stream:
        data = stream.read(limits.max_bytes + 1)
    if len(data) > limits.max_bytes:
        raise BginError("JSON file exceeds size budget", 0, "/", "limit_exceeded")
    try:
        return json.loads(data.decode("utf-8-sig"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as e:
        raise BginError(str(e), 0, "/", "invalid_json") from e


def convert_file(source: str | Path, destination: str | Path, *, to: str | None = None,
                 dialect="auto", limits: Limits | None = None, overwrite=False, indent=2):
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve() or (
            destination.exists() and os.path.samefile(source, destination)):
        raise ValueError("Source and destination must be different files")
    direction = to or ("bgin" if source.suffix.lower() == ".json" else "json")
    if direction == "json":
        document = load(source, dialect=dialect, limits=limits)
        data = dumps(document, indent=indent).encode("utf-8")
    elif direction == "bgin":
        document = load_json(source, limits=limits)
        if dialect != "auto":
            if not isinstance(document, dict):
                raise BginError("Expected a document object", 0, "/", "invalid_json")
            document = dict(document, dialect=dialect)
        data = encode(document, limits=limits)
    else:
        raise ValueError("to must be 'json' or 'bgin'")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent,
                                         prefix=".bgin-", suffix=".tmp", delete=False) as stream:
            temporary = stream.name
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, destination)
        else:
            os.link(temporary, destination)
        return document
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
