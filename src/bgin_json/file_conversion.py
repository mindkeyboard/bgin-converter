"""Verified conversion of saved files for the VS Code sidebar."""

import importlib
import os
from pathlib import Path
import sys

from . import dumps, encode, parse
from .export import load_json
from .parser import Limits
from .publication import atomic_write
from .drafts import draft_warnings


def independent_core():
    try:
        return importlib.import_module("bgin_core")
    except ModuleNotFoundError as error:
        if error.name != "bgin_core":
            raise
    # Source checkouts use the authoritative workspace package. VSIX bundles it.
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "tools"
        if (candidate / "bgin_core" / "__init__.py").is_file():
            sys.path.insert(0, str(candidate))
            return importlib.import_module("bgin_core")
    raise ValueError("Independent BGIN verifier is missing. Reinstall the extension.")


def verified_binary(document):
    compiled = encode(document)
    if not compiled:
        return compiled
    core = independent_core()
    session = core.BginSession(compiled, document.get("dialect", "auto"))
    if core.encode_document(session.snapshot(), force=True) != compiled:
        raise ValueError("Independent BGIN verification failed")
    if encode(parse(compiled)) != compiled:
        raise ValueError("BGIN round-trip verification failed")
    return session.data


def convert_saved_file(source, destination, to, *, overwrite=False, expected=None):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or (destination.exists() and os.path.samefile(source, destination)):
        raise ValueError("Source and destination must be different files")
    if to not in ("json", "bgin"):
        raise ValueError("Conversion format must be json or bgin")
    if destination.suffix.lower() != "." + to:
        raise ValueError(f"Destination must have the .{to} extension")
    if source.suffix.lower() != (".bgin" if to == "json" else ".json"):
        raise ValueError("Source extension does not match the conversion direction")
    if to == "json":
        with source.open("rb") as stream:
            raw = stream.read(Limits().max_bytes + 1)
        document = parse(raw)
        if encode(document) != raw:
            raise ValueError("BGIN cannot be represented as editable JSON without loss")
        data = dumps(document).encode("utf-8")
    else:
        document = load_json(source)
        data = verified_binary(document)
    # expected is the bytes observed by the host before overwrite confirmation.
    return {**atomic_write(destination, data, overwrite=overwrite, expected=expected), "format": to, "warnings": draft_warnings(document)}
