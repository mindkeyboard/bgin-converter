"""Document operations independent of the MCP transport and image rasterizer."""

from __future__ import annotations

import copy
import importlib
import json
import os
import re
from pathlib import Path
import sys
import threading
import uuid

from bgin_json import dumps, encode, parse
from bgin_json.publication import atomic_write
from bgin_json.drafts import draft_warnings
from bgin_json.catalog import catalog
from bgin_json.rpc import document as read_json
from bgin_json.render.scene import DEFAULTS, options as renderer_options

MAX_BYTES = 64 * 1024 * 1024
RESOURCE_KEYS = {"assetRoot", "bginRoot", "textureRoot", "fontRoot", "bindings"}


def strict_object(value, allowed, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    extra = value.keys() - allowed
    if extra:
        raise ValueError(f"Unknown {label} fields: {', '.join(sorted(extra))}")


def preview_options(raw):
    strict_object(raw, DEFAULTS.keys(), "preview")
    result = renderer_options(raw)
    for key in ("screen", "page"):
        if type(result[key]) is not int or result[key] < 0:
            raise ValueError(f"{key} must be a nonnegative integer")
    for key in ("selected", "language"):
        if not isinstance(result[key], str):
            raise ValueError(f"{key} must be a string")
    for key, value in result.items():
        if type(DEFAULTS[key]) in (int, float) and type(value) is bool:
            raise ValueError(f"{key} must be a number, not a boolean")
    return result


def walk(document):
    def visit(node, path):
        yield path, node
        for field in ("children", "tracks"):
            for index, child in enumerate(node.get(field, [])):
                yield from visit(child, f"{path}/{field}/{index}")

    for index, screen in enumerate(document["screens"]):
        yield from visit(screen, f"/screens/{index}")


def at(document, pointer):
    if pointer == "":
        return document
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(
            "Use an absolute JSON pointer, for example /screens/0/children/1"
        )
    item = document
    try:
        for part in pointer[1:].split("/"):
            if re.search(r"~(?![01])", part):
                raise ValueError("JSON pointers escape ~ as ~0 and / as ~1")
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(item, list):
                if not part.isdecimal() or (len(part) > 1 and part.startswith("0")):
                    raise ValueError("Invalid array index")
                item = item[int(part)]
            else:
                item = item[part]
        return item
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError(f"JSON pointer does not exist: {pointer}") from error


def differences(left, right, limit=200):
    rows = []
    truncated = False

    def visit(a, b, path):
        nonlocal truncated
        if a == b:
            return
        if len(rows) >= limit:
            truncated = True
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(a.keys() | b.keys()):
                pointer = path + "/" + key.replace("~", "~0").replace("/", "~1")
                if key not in a or key not in b:
                    if len(rows) < limit:
                        row = {
                            "path": pointer,
                            "operation": "remove" if key in a else "add",
                        }
                        row["before" if key in a else "after"] = (
                            a[key] if key in a else b[key]
                        )
                        rows.append(row)
                    else:
                        truncated = True
                else:
                    visit(a[key], b[key], pointer)
        elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            for index, (old, new) in enumerate(zip(a, b)):
                visit(old, new, f"{path}/{index}")
        else:
            rows.append({"path": path, "operation": "replace", "before": a, "after": b})

    visit(left, right, "")
    return {"changes": rows, "truncated": truncated}


class Service:
    def __init__(self, config_path=None, core_path=None):
        self.config_lock = threading.RLock()
        self.config_path = Path(
            config_path or os.getenv("BGIN_MCP_CONFIG", ".bgin-mcp.json")
        ).resolve()
        self.root = self.config_path.parent
        self.core_path = core_path or os.getenv("BGIN_CORE_PATH")
        self.settings = {"preview": {}, "resources": {}, "browserChannel": ""}
        if self.config_path.exists():
            # A removed resource directory must not prevent settings repair over MCP.
            self.settings = self.checked_settings(
                read_json(self.config_path.read_text(encoding="utf-8-sig")),
                check_paths=False,
            )

    def path(self, name):
        if not isinstance(name, str) or not name:
            raise ValueError("Path must be a nonempty string")
        path = Path(name).expanduser()
        return (path if path.is_absolute() else self.root / path).resolve()

    def resources(self, raw, check_paths=True):
        strict_object(raw, RESOURCE_KEYS, "resources")
        result = {}
        for key, value in raw.items():
            if key == "bindings":
                if not isinstance(value, dict) or any(
                    not isinstance(k, str) or not k for k in value
                ):
                    raise ValueError("bindings must map names to BGIN paths")
                result[key] = {
                    alias: str(self.path(path)) for alias, path in value.items()
                }
                for alias, path in result[key].items():
                    if (
                        check_paths
                        and not raw.get("bginRoot")
                        and not Path(path).is_file()
                    ):
                        raise ValueError(f"Resource {alias}: file not found: {path}")
            elif value == "":
                result[key] = ""
            else:
                result[key] = str(self.path(value))
                if check_paths and not Path(result[key]).is_dir():
                    raise ValueError(
                        f"Resource directory {key} does not exist: {result[key]}"
                    )
        return result

    def checked_settings(self, raw, check_paths=True):
        strict_object(raw, {"preview", "resources", "browserChannel"}, "settings")
        preview_options(raw.get("preview", {}))
        self.resources(raw.get("resources", {}), check_paths=check_paths)
        channel = raw.get("browserChannel", "")
        if channel not in ("", "msedge", "chrome"):
            raise ValueError(
                "browserChannel must be empty (Playwright Chromium), msedge or chrome"
            )
        return {
            "preview": raw.get("preview", {}),
            "resources": raw.get("resources", {}),
            "browserChannel": channel,
        }

    def configure(self, changes=None, editor_settings=None):
        with self.config_lock:
            return self._configure(changes, editor_settings)

    def _configure(self, changes=None, editor_settings=None):
        if changes is None and editor_settings is None:
            return {
                "path": str(self.config_path),
                "settings": copy.deepcopy(self.settings),
                "effectivePreview": preview_options(self.settings["preview"]),
                "resourceBase": str(self.root),
            }
        changes = changes or {}
        if editor_settings is not None:
            if not isinstance(editor_settings, dict):
                raise ValueError(
                    "editor_settings must be the parsed VS Code settings object"
                )
            folders = {
                key: editor_settings.get("bgin." + key, "")
                for key in RESOURCE_KEYS - {"bindings"}
            }
            folders.update(editor_settings.get("bgin.resourceFolders", {}))
            if not folders.get("bginRoot"):
                folders["bindings"] = editor_settings.get("bgin.resourceBindings", {})
            imported = {
                "preview": editor_settings.get("bgin.preview", {}),
                "resources": folders,
            }
            for key, value in changes.items():
                if (
                    key in ("preview", "resources")
                    and isinstance(value, dict)
                    and isinstance(imported[key], dict)
                ):
                    imported[key] = {**imported[key], **value}
                else:
                    imported[key] = value
            changes = imported
        strict_object(changes, {"preview", "resources", "browserChannel"}, "settings")
        candidate = copy.deepcopy(self.settings)
        for key, value in changes.items():
            if key in ("preview", "resources"):
                if not isinstance(value, dict):
                    raise ValueError(f"{key} must be an object")
                candidate[key].update(value)
            else:
                candidate[key] = value
        candidate = self.checked_settings(candidate)
        saved = atomic_write(
            self.config_path,
            (json.dumps(candidate, indent=2, ensure_ascii=False) + "\n").encode(),
            overwrite=True,
        )
        self.settings = candidate
        return {**self.configure(), "saved": saved}

    def load(self, source):
        strict_object(source, {"path", "document"}, "source")
        if ("path" in source) == ("document" in source):
            raise ValueError("Supply exactly one of source.path or source.document")
        origin = ""
        if "path" in source:
            path = self.path(source["path"])
            if path.stat().st_size > MAX_BYTES:
                raise ValueError("Document exceeds 64 MiB")
            data = path.read_bytes()
            origin = str(path)
            if path.suffix.lower() == ".bgin":
                doc = parse(data)
            else:
                doc = read_json(data.decode("utf-8-sig"))
        else:
            raw = source["document"]
            doc = read_json(raw) if isinstance(raw, str) else copy.deepcopy(raw)
        # The compiler validates the real wire contract, including sprite dialects.
        # Empty editor drafts remain readable but cannot be compiled or rendered.
        if isinstance(doc, dict) and doc.get("screens") == [] and "name" in doc:
            candidate = {
                **doc,
                "screens": [{"type": "StackContainer", "name": "validation"}],
            }
            encode(candidate)
        else:
            encode(doc)
        return doc, origin

    def read(self, source, pointer="", depth=2, include_document=True):
        if type(depth) is not int or not 0 <= depth <= 32:
            raise ValueError("depth must be between 0 and 32")
        doc, origin = self.load(source)
        target = at(doc, pointer)

        def outline(node, path, level):
            row = {
                "path": path,
                "type": node["type"],
                "name": node["name"],
                "childrenCount": len(node.get("children", [])),
                "tracksCount": len(node.get("tracks", [])),
            }
            if level:
                row["children"] = [
                    outline(n, f"{path}/{field}/{i}", level - 1)
                    for field in ("children", "tracks")
                    for i, n in enumerate(node.get(field, []))
                ]
            return row

        result = {
            "source": origin,
            "draft": not doc["screens"],
            **({"name": doc["name"]} if "name" in doc else {}),
            "warnings": draft_warnings(doc),
            "tree": [
                outline(node, f"/screens/{i}", depth)
                for i, node in enumerate(doc["screens"])
            ],
        }
        if include_document:
            result["document"] = target
        return result

    def validate(self, source):
        doc, _ = self.load(source)
        binary = encode(doc)
        warnings = draft_warnings(doc)
        schemas = catalog()["schemas"]
        for path, node in walk(doc):
            props = node.get("properties", {})
            names = (
                props.keys()
                if isinstance(props, dict)
                else [k for row in props for k in row]
            )
            for name in names:
                if name not in schemas.get(node["type"], []):
                    warnings.append(
                        {
                            "path": path + "/properties",
                            "message": f"{name} is preserved but not confirmed for {node['type']} by its loader",
                        }
                    )
        duplicates = set()
        seen = set()
        for screen in doc["screens"]:
            name = screen["name"]
            if name in seen:
                duplicates.add(name)
            seen.add(name)
        if duplicates:
            warnings.append(
                {
                    "path": "/screens",
                    "message": "Duplicate screen names: "
                    + ", ".join(sorted(duplicates)),
                }
            )
        return {
            "valid": True,
            "bytes": len(binary),
            "warnings": warnings,
            "scope": "Editable JSON and binary encoding; preview and game behavior are separate checks",
        }

    def search(self, source, query="", type_name="", limit=100):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        doc, _ = self.load(source)
        needle = query.casefold()
        matches = [
            {"path": path, "name": node["name"], "type": node["type"]}
            for path, node in walk(doc)
            if (not type_name or node["type"] == type_name)
            and (needle in node["name"].casefold() or needle in node["type"].casefold())
        ]
        return {
            "matches": matches[:limit],
            "total": len(matches),
            "truncated": len(matches) > limit,
        }

    def core(self):
        # The workspace transaction codec is the independent authority for writes.
        # A standalone install supplies its tools directory via --core-path.
        candidates = (
            [Path(self.core_path)]
            if self.core_path
            else [p / "tools" for p in Path(__file__).resolve().parents]
        )
        for candidate in candidates:
            if (candidate / "bgin_core" / "__init__.py").is_file():
                if str(candidate) not in sys.path:
                    sys.path.insert(0, str(candidate))
                return importlib.import_module("bgin_core")
        raise ValueError(
            "Binary export requires the verified tools/bgin_core. Set --core-path or BGIN_CORE_PATH to its parent directory. Parsing and rendering remain available."
        )

    def export(self, source, destination, format="bgin", overwrite=False):
        doc, origin = self.load(source)
        target = self.path(destination)
        if format not in ("bgin", "json"):
            raise ValueError("format must be bgin or json")
        if origin and Path(origin) == target:
            raise ValueError(
                "Export to a separate path, compare it, then replace through the editor transaction workflow"
            )
        if format == "bgin":
            binary = encode(doc)
            if binary:
                core = self.core()
                session = core.BginSession(binary, doc.get("dialect", "auto"))
                if core.encode_document(session.snapshot(), force=True) != binary:
                    raise ValueError(
                        "Independent bgin_core check did not reproduce the compiled bytes"
                    )
                if encode(parse(binary)) != binary:
                    raise ValueError(
                        "Editable JSON round trip did not reproduce the compiled bytes"
                    )
                data = session.data
            else:
                data = b""
        else:
            data = dumps(doc).encode("utf-8")
        saved = atomic_write(target, data, overwrite=overwrite)
        return {**saved, "format": format, "independentBinaryCheck": format == "bgin" and bool(data), "warnings": draft_warnings(doc)}

    def create(
        self,
        name="Untitled",
        dialect="ui",
        root_type="StackContainer",
        screen_name="main",
        node_only=False,
    ):
        data = catalog()
        if dialect not in data["creation"]["screens"]:
            raise ValueError("dialect must be ui, templates or sprites")
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(screen_name, str)
            or not screen_name.strip()
        ):
            raise ValueError("Document and node names must be nonempty strings")
        allowed = data["types"] if node_only else data["creation"]["screens"][dialect]
        if root_type not in allowed:
            raise ValueError(
                "Unsupported type in this context; consult bgin_catalog.creation"
            )
        node = {"type": root_type, "name": screen_name, "properties": {}}
        if root_type in data["containers"] or root_type in ("Sprite", "SpriteMovie"):
            node["children"] = []
        if dialect == "sprites" and root_type == "Movie":
            node = {
                "type": root_type,
                "name": screen_name,
                "children": [],
                "tracks": [],
            }
        doc = {"name": name, "dialect": dialect, "screens": [node]}
        encode(doc)
        return {
            "node" if node_only else "document": node if node_only else doc,
            "note": "Unset properties use loader defaults; consult the catalog before assigning them",
        }

    def edit(self, source, operations):
        """Apply a whole patch to a copy and validate before returning it; never writes."""
        if not isinstance(operations, list) or not 1 <= len(operations) <= 200:
            raise ValueError("Supply 1 to 200 JSON-pointer operations")
        original, _ = self.load(source)
        doc = copy.deepcopy(original)
        for operation in operations:
            strict_object(operation, {"op", "path", "value"}, "edit operation")
            action, pointer = operation.get("op"), operation.get("path")
            if action not in ("add", "replace", "remove", "test"):
                raise ValueError("Supported operations: add, replace, remove, test")
            if action != "remove" and "value" not in operation:
                raise ValueError("This operation requires value")
            if action == "test":
                if at(doc, pointer) != operation["value"]:
                    raise ValueError(f"Edit precondition failed: {pointer}")
                continue
            if pointer == "":
                if action == "remove":
                    raise ValueError("Cannot remove the document")
                doc = copy.deepcopy(operation["value"])
                continue
            if (
                not isinstance(pointer, str)
                or not pointer.startswith("/")
                or re.search(r"~(?![01])", pointer)
            ):
                raise ValueError("Invalid JSON pointer")
            parent_path, key = pointer.rsplit("/", 1)
            parent = at(doc, parent_path)
            key = key.replace("~1", "/").replace("~0", "~")
            value = copy.deepcopy(operation.get("value"))
            if isinstance(parent, list):
                if action == "add" and key == "-":
                    index = len(parent)
                elif (
                    key.isascii()
                    and key.isdecimal()
                    and (len(key) == 1 or not key.startswith("0"))
                ):
                    index = int(key)
                else:
                    raise ValueError("Invalid array index")
                maximum = len(parent) if action == "add" else len(parent) - 1
                if not 0 <= index <= maximum:
                    raise ValueError(f"Array index out of range: {pointer}")
                if action == "add":
                    parent.insert(index, value)
                elif action == "remove":
                    parent.pop(index)
                else:
                    parent[index] = value
            elif isinstance(parent, dict):
                if action != "add" and key not in parent:
                    raise ValueError(f"JSON pointer does not exist: {pointer}")
                if action == "remove":
                    del parent[key]
                else:
                    parent[key] = value
            else:
                raise ValueError("Edit parent must be an object or array")
        validation = self.validate({"document": doc})
        return {
            "document": doc,
            "changes": differences(original, doc),
            "validation": validation,
        }

    def resource_report(self, source, resources=None):
        from bgin_json.render.resources import Resources

        doc, origin = self.load(source)
        config = self.resources(
            {**self.settings["resources"], **(resources or {})}, check_paths=False
        )
        warnings = set()
        cache = Resources(config, origin, warnings)
        if "name" in doc:
            cache.add_binding(doc["name"], doc)
        cache.audit(doc)
        for key, path in config.items():
            if key != "bindings" and path and not Path(path).is_dir():
                cache.errors.append(
                    {
                        "path": "/",
                        "message": f"Resource directory {key} does not exist: {path}",
                    }
                )
        return {
            "resources": config,
            "namespaces": {name: str(path) for name, path in cache.sources.items()},
            "errors": cache.errors,
            "warnings": sorted(warnings),
            "scope": "BGIN references and configured directories; texture/font decoding is checked during render",
        }

    def compare(self, before, after, limit=200):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        left, _ = self.load(before)
        right, _ = self.load(after)
        return {"equal": left == right, **differences(left, right, limit)}
