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
    # Source checkouts carry the same independently maintained codec as the VSIX.
    # Prefer that version over an older workspace copy with fewer wire profiles.
    for parent in Path(__file__).resolve().parents:
        for folder in ("vendor", "tools"):
            candidate = parent / folder
            if (candidate / "bgin_core" / "__init__.py").is_file():
                sys.path.insert(0, str(candidate))
                return importlib.import_module("bgin_core")
    raise ValueError("Independent BGIN verifier is missing. Reinstall the extension.")


def verified_binary(document):
    compiled = encode(document)
    if not compiled:
        return compiled
    core = independent_core()
    profile = document.get("format", "a8-1.6.0")
    snapshot = core.decode_document(compiled, document.get("dialect", "auto"), wire_format=profile)
    if core.encode_document(snapshot, force=True) != compiled:
        raise ValueError("Independent BGIN verification failed")
    if encode(parse(compiled, format=profile)) != compiled:
        raise ValueError("BGIN round-trip verification failed")
    return compiled


def convert_saved_file(source, destination, to, *, overwrite=False, expected=None,
                       target_format=None):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or (destination.exists() and os.path.samefile(source, destination)):
        raise ValueError("Source and destination must be different files")
    if to not in ("json", "bgin"):
        raise ValueError("Conversion format must be json or bgin")
    if destination.suffix.lower() != "." + to:
        raise ValueError(f"Destination must have the .{to} extension")
    allowed_sources = (".bgin",) if to == "json" else (".json", ".bgin")
    if source.suffix.lower() not in allowed_sources:
        raise ValueError("Source extension does not match the conversion direction")
    binary_source = source.suffix.lower() == ".bgin"
    if binary_source:
        with source.open("rb") as stream:
            raw = stream.read(Limits().max_bytes + 1)
        document = parse(raw)
    else:
        document = load_json(source)
    if to == "json":
        if encode(document) != raw:
            raise ValueError("BGIN cannot be represented as editable JSON without loss")
    if target_format is not None:
        from .writer import convert_document

        document = convert_document(document, target_format)
    elif to == "bgin" and binary_source:
        raise ValueError("BGIN to BGIN conversion requires an explicit target format")
    if to == "json":
        data = dumps(document).encode("utf-8")
    else:
        data = verified_binary(document)
    # expected is the bytes observed by the host before overwrite confirmation.
    return {**atomic_write(destination, data, overwrite=overwrite, expected=expected), "format": to, "warnings": draft_warnings(document)}
