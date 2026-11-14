"""Explicit stdio MCP adapter for a live VS Code window; never falls back to disk."""

from __future__ import annotations

import asyncio
import base64
from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path
import threading
from urllib import error, parse, request
import uuid

from bgin_json import dumps
from bgin_json.rpc import document as read_json
from .service import Service, strict_object


class BridgeError(ValueError):
    def __init__(self, code, message, details=None):
        self.code, self.details = code, details
        super().__init__(f"{code}: {message}" + (f"; {json.dumps(details, ensure_ascii=False)}" if details is not None else ""))


class BridgeClient:
    def __init__(self, discovery_file, name="BGIN MCP"):
        self.discovery_file = Path(discovery_file).expanduser().resolve()
        try:
            data = json.loads(self.discovery_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BridgeError("editor_unavailable", f"Cannot read editor discovery file: {self.discovery_file}. Open VS Code and select its connection file.") from exc
        endpoint = parse.urlsplit(data.get("endpoint", ""))
        if data.get("version") != 1 or endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1" or endpoint.path != "/rpc" or not endpoint.port or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            raise BridgeError("invalid_discovery", "Editor discovery must identify a version 1 loopback HTTP bridge")
        token = data.get("token", "")
        if not isinstance(token, str) or len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
            raise BridgeError("invalid_discovery", "Invalid editor bridge token")
        self.endpoint, self.token = data["endpoint"], token
        self.lock = threading.RLock()
        self.cursor = 0
        self.pending = []
        self.truncated = False
        self.session_id = None
        connected = self.call("connect", {"name": name})
        self.session_id = connected["sessionId"]
        self.window_id = connected["windowId"]

    def call(self, method, params=None):
        with self.lock:
            body = json.dumps({"method": method, "params": params or {}, "sessionId": self.session_id, "cursor": self.cursor}, ensure_ascii=False, allow_nan=False).encode("utf-8")
            req = request.Request(self.endpoint, data=body, headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"}, method="POST")
            try:
                # Disable inherited HTTP proxies: the capability token stays on loopback.
                opener = request.build_opener(request.ProxyHandler({}))
                with opener.open(req, timeout=60) as response:
                    raw = response.read(96 * 1024 * 1024 + 1)
                    if len(raw) > 96 * 1024 * 1024:
                        raise BridgeError("response_limit", "Editor response exceeds 96 MiB")
                    result = json.loads(raw)
            except (OSError, error.URLError, ValueError) as exc:
                if isinstance(exc, BridgeError):
                    raise
                raise BridgeError("editor_unavailable", "The connected VS Code window is unavailable; reconnect explicitly. No standalone fallback was used.") from exc
            self.cursor = result.get("cursor", self.cursor)
            self.pending.extend(result.get("changes", []))
            self.truncated |= result.get("changesTruncated", False)
            if len(self.pending) > 1000:
                self.pending = self.pending[-1000:]
                self.truncated = True
            if "error" in result:
                problem = result["error"]
                raise BridgeError(problem.get("code", "editor_error"), problem.get("message", "Editor request failed"), problem.get("details"))
            return result["result"]

    def updates(self):
        with self.lock:
            result = {"mode": "connected", "sessionId": self.session_id, "windowId": self.window_id, "cursor": self.cursor, "changes": self.pending, "changesTruncated": self.truncated}
            self.pending = []
            self.truncated = False
            return result

    def close(self):
        if self.session_id:
            try:
                self.call("sessions/disconnect")
            except BridgeError:
                pass


class ConnectedService(Service):
    """Codec work runs locally; the extension is the only live document owner."""

    connected = True

    def __init__(self, discovery_file, client_name="BGIN MCP", config_path=None, core_path=None):
        super().__init__(config_path, core_path, load_config=False)
        self.bridge = BridgeClient(discovery_file, client_name)

    def decorate(self, result):
        return {**result, "editor": self.bridge.updates()}

    def snapshot(self, source):
        strict_object(source, {"path", "documentId"}, "connected source")
        if ("path" in source) == ("documentId" in source):
            raise ValueError("Connected mode requires exactly one source.path or source.documentId; detached document copies are not live documents")
        if "path" in source:
            snapshot = self.bridge.call("documents/open", {"path": source["path"]})
        else:
            snapshot = self.bridge.call("documents/read", {"documentId": source["documentId"]})
        return snapshot

    def load(self, source):
        snapshot = self.snapshot(source)
        # Parse the actual current text; never substitute a last-valid document.
        return self.local().load({"document": snapshot["text"]})[0], snapshot["path"]

    def local(self):
        local = Service(self.config_path, self.core_path, load_config=False)
        local.settings = copy.deepcopy(self.settings)
        return local

    def local_settings(self, document_id=None):
        settings = self.bridge.call("settings/read", {"documentId": document_id})
        raw = settings.get("settings", settings)
        canonical = self.checked_settings({key: raw.get(key, {} if key != "browserChannel" else "") for key in ("preview", "resources", "browserChannel")}, check_paths=False)
        self.settings = canonical
        return {**canonical, "resourceRevision": settings.get("resourceRevision", raw.get("resourceRevision"))}

    @contextmanager
    def operation(self, name, snapshot=None, operation_id=None):
        operation_id = operation_id or uuid.uuid4().hex
        self.bridge.call("operations/begin", {"name": name, "operationId": operation_id, "documentId": snapshot.get("documentId") if snapshot else None})
        try:
            yield operation_id
        except BaseException:
            try:
                self.bridge.call("operations/finish", {"operationId": operation_id, "failed": True})
            except BridgeError:
                pass
            raise
        else:
            self.bridge.call("operations/finish", {"operationId": operation_id})

    def documents(self):
        return self.decorate(self.bridge.call("documents/list"))

    def changes(self):
        return self.decorate(self.bridge.call("documents/changes"))

    def read(self, source, pointer="", depth=2, include_document=True):
        snapshot = self.snapshot(source)
        with self.operation("read", snapshot):
            try:
                result = self.local().read({"document": snapshot["text"]}, pointer, depth, include_document)
            except (ValueError, TypeError) as exc:
                result = {"valid": False, "diagnostics": [{"message": str(exc)}], "text": snapshot["text"], "source": snapshot["path"]}
            else:
                result.update(valid=True, source=snapshot["path"])
            return self.decorate({**result, "documentId": snapshot["documentId"], "revision": snapshot["revision"]})

    def validate(self, source):
        snapshot = self.snapshot(source)
        with self.operation("validate", snapshot):
            result = self.local().validate({"document": snapshot["text"]})
            return self.decorate({**result, "documentId": snapshot["documentId"], "revision": snapshot["revision"]})

    def search(self, source, query="", type_name="", limit=100):
        snapshot = self.snapshot(source)
        with self.operation("search", snapshot):
            result = self.local().search({"document": snapshot["text"]}, query, type_name, limit)
            return self.decorate({**result, "documentId": snapshot["documentId"], "revision": snapshot["revision"]})

    def edit(self, source, operations, base_revision=None, operation_id=""):
        if base_revision is None or not operation_id:
            raise ValueError("Connected edits require base_revision from bgin_read and a unique operation_id; repeat the same operation_id when retrying after a transport failure")
        input_key = hashlib.sha256(json.dumps({"source": source, "operations": operations, "baseRevision": base_revision}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        previous = self.bridge.call("documents/result", {"operationId": operation_id, "inputKey": input_key})
        if previous is not None:
            return self.decorate({"document": read_json(previous["text"]), "documentId": previous["documentId"], "revision": previous["revision"], "replayed": True})
        snapshot = self.snapshot(source)
        with self.operation("edit", snapshot, operation_id):
            # super.edit calls self.validate; use a detached codec service to avoid
            # accidentally treating the candidate copy as an authoritative source.
            local = self.local()
            result = local.edit({"document": snapshot["text"]}, operations)
            updated = self.bridge.call("documents/edit", {"documentId": snapshot["documentId"], "baseRevision": base_revision, "operationId": operation_id, "inputKey": input_key, "text": dumps(result["document"])})
            return self.decorate({**result, "documentId": updated["documentId"], "revision": updated["revision"]})

    def save(self, source, base_revision, operation_id):
        snapshot = self.snapshot(source)
        with self.operation("save", snapshot, operation_id):
            saved = self.bridge.call("documents/save", {"documentId": snapshot["documentId"], "baseRevision": base_revision, "operationId": operation_id})
            return self.decorate({"saved": True, "documentId": saved["documentId"], "revision": saved["revision"], "path": saved["path"]})

    def configure(self, changes=None, editor_settings=None):
        if changes is not None or editor_settings is not None:
            raise ValueError("Connected settings belong to VS Code; change them in its Binary GIN resource/settings controls")
        return self.decorate({"settings": self.local_settings(), "scope": "Connected VS Code window"})

    def export(self, source, destination, format="bgin", overwrite=False):
        # Connected saves always use the extension's undo/save owner. A caller
        # can explicitly start standalone mode for detached conversion/export.
        raise ValueError("Connected mode saves through bgin_save. Use the editor converter or explicit standalone mode to export a separate file")

    def create(self, *args, **kwargs):
        if not kwargs.get("node_only", False) and not (len(args) >= 5 and args[4]):
            raise ValueError("Create a live file with VS Code's BGIN: New File command; node_only=true creates a detached node for insertion")
        return self.decorate(self.local().create(*args, **kwargs))

    def compare(self, before, after, limit=200):
        left, right = self.snapshot(before), self.snapshot(after)
        local = self.local()
        with self.operation("compare", left):
            return self.decorate(local.compare({"document": left["text"]}, {"document": right["text"]}, limit))

    def resource_report(self, source, resources=None, target_format=None):
        snapshot = self.snapshot(source)
        self.local_settings(snapshot["documentId"])
        local = self.local()
        local.settings = copy.deepcopy(self.settings)
        with self.operation("resources", snapshot):
            doc, _ = local.load({"document": snapshot["text"]})
            original = local.load
            local.load = lambda source: (doc, snapshot["path"])
            try:
                return self.decorate(local.resource_report({"document": doc}, resources, target_format))
            finally:
                local.load = original

    async def render(self, requests, tile_width, tile_height):
        from .sheets import render_sheets

        if not isinstance(requests, list) or not 1 <= len(requests) <= 36:
            raise ValueError("Supply 1 to 36 render requests")
        snapshots = [self.snapshot(item["source"]) for item in requests]
        # Each request resolves resources using the live document's project.
        settings = [copy.deepcopy(self.local_settings(snapshot["documentId"])) for snapshot in snapshots]
        if any(item != settings[0] for item in settings[1:]):
            raise ValueError("A render sheet must use documents with the same project resource settings")
        local = self.local()
        local.settings = settings[0]
        prepared = []
        origins = {}
        for index, (item, snapshot) in enumerate(zip(requests, snapshots)):
            candidate = copy.deepcopy(item)
            # render_sheets calls Service.load for its source; this map preserves
            # the origin without allowing it to re-read a stale disk version.
            key = str(index)
            origins[key] = (local.load({"document": snapshot["text"]})[0], snapshot["path"])
            candidate["source"] = {"snapshot": key}
            prepared.append(candidate)
        local.load = lambda source: origins[source["snapshot"]]
        with self.operation("render", snapshots[0]) as operation_id:
            task = asyncio.create_task(render_sheets(local, prepared, tile_width, tile_height))
            try:
                while not task.done():
                    await asyncio.sleep(0.2)
                    await asyncio.to_thread(self.bridge.call, "operations/check", {"operationId": operation_id})
                images, metadata = await task
                metadata["documents"] = [{"documentId": snapshot["documentId"], "revision": snapshot["revision"]} for snapshot in snapshots]
                metadata["resourceRevision"] = settings[0]["resourceRevision"]
                pngs = [{"mimeType": "image/png", "data": base64.b64encode(image).decode("ascii")} for image in images]
                visibility = []
                # One gallery event contains the sheet; all source revisions are
                # retained in metadata, and the UI labels outdated snapshots.
                first = snapshots[0]
                for snapshot, previous_settings in zip(snapshots, settings):
                    current = self.bridge.call("documents/read", {"documentId": snapshot["documentId"]})
                    visibility.append(current["revision"] != snapshot["revision"])
                    current_settings = self.local_settings(snapshot["documentId"])
                    visibility.append(current_settings != previous_settings)
                metadata["stale"] = any(visibility)
                self.bridge.call("renders/publish", {"operationId": operation_id, "documentId": first["documentId"], "revision": first["revision"], "images": pngs, "metadata": metadata})
                return images, self.decorate(metadata)
            finally:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
