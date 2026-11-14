"""Two real adapters share one real TypeScript bridge and a revision-aware host."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack, asynccontextmanager
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib import request, error

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from bgin_json.mcp_server.bridge import BridgeClient, BridgeError, ConnectedService

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from pydantic import AnyUrl
except ImportError:
    ClientSession = None


@unittest.skipUnless(shutil.which("node") and (PROJECT / "vscode/node_modules/esbuild").exists(), "Node and editor dependencies required")
class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.host = subprocess.Popen(["node", str(PROJECT / "vscode/test/mcpBridgeHost.cjs")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        self.addCleanup(self.stop_host)
        initial = self.host.stdout.readline()
        self.assertTrue(initial, self.host.stderr.read() if self.host.poll() is not None else "Host did not start")
        self.initial = json.loads(initial)
        self.temporary = tempfile.TemporaryDirectory(prefix="bgin-connected-test-")
        self.addCleanup(self.temporary.cleanup)
        self.config = Path(self.temporary.name) / "settings.json"
        self.a = self.service("First AI")
        self.b = self.service("Second AI")
        self.source = {"documentId": "doc-one"}

    def service(self, name):
        service = ConnectedService(self.initial["discoveryFile"], name, self.config, PROJECT / "vendor")
        self.addCleanup(service.bridge.close)
        return service

    def control(self, **arguments):
        self.host.stdin.write(json.dumps(arguments) + "\n")
        self.host.stdin.flush()
        response = json.loads(self.host.stdout.readline())
        self.assertNotIn("error", response)
        return response

    def stop_host(self):
        if self.host.poll() is None:
            self.host.stdin.write('{"action":"stop"}\n')
            self.host.stdin.flush()
            try:
                self.host.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.host.kill()
                self.host.wait(timeout=5)
        for stream in (self.host.stdin, self.host.stdout, self.host.stderr):
            stream.close()

    def test_two_clients_unsaved_changes_conflicts_and_retry_identity(self):
        left, right = self.a.read(self.source), self.b.read(self.source)
        self.assertEqual(left["revision"], right["revision"])
        patch = [{"op": "replace", "path": "/screens/0/name", "value": "by first AI"}]
        result = self.a.edit(self.source, patch, left["revision"], "first-edit")
        self.assertEqual(result["revision"], 1)
        replayed = self.a.edit(self.source, patch, left["revision"], "first-edit")
        self.assertTrue(replayed["replayed"])
        self.assertEqual(replayed["revision"], 1)
        with self.assertRaisesRegex(BridgeError, "operation_reused"):
            self.a.edit(self.source, [{"op": "replace", "path": "/name", "value": "different"}], 0, "first-edit")
        changed = self.b.read(self.source)
        self.assertEqual(changed["document"]["screens"][0]["name"], "by first AI")
        self.assertTrue(changed["editor"]["changes"])
        self.control(action="user", text=json.dumps({"name": "manual unsaved", "screens": [{"type": "StackContainer", "name": "human"}]}))
        with self.assertRaisesRegex(BridgeError, "revision_conflict"):
            self.b.edit(self.source, patch, right["revision"], "stale-edit")
        current = self.b.read(self.source)
        self.assertEqual(current["document"]["name"], "manual unsaved")
        self.assertEqual(current["revision"], 2)
        self.assertTrue(any(item["origin"] == "user" for item in current["editor"]["changes"]))

    def test_invalid_text_never_uses_last_valid_document(self):
        self.assertTrue(self.a.read(self.source)["valid"])
        self.control(action="user", text='{"name": broken manual edit')
        invalid = self.a.read(self.source)
        self.assertFalse(invalid["valid"])
        self.assertEqual(invalid["text"], '{"name": broken manual edit')
        self.assertNotIn("document", invalid)
        with self.assertRaises(ValueError):
            self.a.edit(self.source, [{"op": "replace", "path": "/name", "value": "no"}], invalid["revision"], "invalid-edit")
        with self.assertRaises(ValueError):
            self.a.validate(self.source)

    def test_pause_cancel_and_concurrent_manual_edit_during_commit(self):
        self.control(action="pause", sessionId=self.a.bridge.session_id, paused=True)
        with self.assertRaisesRegex(BridgeError, "paused"):
            self.a.edit(self.source, [{"op": "replace", "path": "/name", "value": "blocked"}], 0, "paused-edit")
        self.control(action="pause", sessionId=self.a.bridge.session_id, paused=False)
        with ThreadPoolExecutor(max_workers=1) as workers:
            result = workers.submit(self.a.edit, self.source, [{"op": "replace", "path": "/name", "value": "cancel me"}], 0, "cancelled-edit")
            self.wait_operation("cancelled-edit")
            self.control(action="cancel", sessionId=self.a.bridge.session_id, operationId="cancelled-edit")
            with self.assertRaisesRegex(BridgeError, "cancelled"):
                result.result()
        self.assertEqual(self.b.read(self.source)["revision"], 0)
        with ThreadPoolExecutor(max_workers=1) as workers:
            result = workers.submit(self.a.edit, self.source, [{"op": "replace", "path": "/name", "value": "stale"}], 0, "race-edit")
            self.wait_operation("race-edit")
            self.control(action="user", text=json.dumps({"name": "user wins", "screens": [{"type": "StackContainer", "name": "human"}]}))
            with self.assertRaisesRegex(BridgeError, "revision_conflict"):
                result.result()
        self.assertEqual(self.b.read(self.source)["document"]["name"], "user wins")

    def wait_operation(self, operation_id):
        for _ in range(100):
            state = self.control(action="state")["state"]
            if any(item.get("operation", {}).get("id") == operation_id for item in state["sessions"]):
                return
            time.sleep(0.005)
        self.fail("Operation did not begin")

    def test_render_publication_stale_revision_and_cancel(self):
        client = self.a.bridge
        client.call("operations/begin", {"operationId": "render", "name": "render", "documentId": "doc-one"})
        self.control(action="user", text=self.initial["document"]["text"])
        visible = client.call("renders/publish", {"operationId": "render", "documentId": "doc-one", "revision": 0, "images": [], "metadata": {"renders": []}})
        self.assertTrue(visible["stale"])
        self.assertEqual(len(self.control(action="state")["renders"]), 1)
        self.control(action="cancel", sessionId=client.session_id, operationId="render")
        with self.assertRaisesRegex(BridgeError, "cancelled"):
            client.call("renders/publish", {"operationId": "render", "documentId": "doc-one", "revision": 0, "images": [], "metadata": {}})

    def test_resource_change_during_render_marks_incoming_gallery_stale(self):
        # Exercise adapter snapshot/publication ordering independently of browser speed.
        async def pending_rasterizer(service, requests, width, height):
            self.control(action="resources")
            await asyncio.sleep(0.01)
            return [b"test sheet"], {"renders": [], "sheetCount": 1}

        with patch("bgin_json.mcp_server.sheets.render_sheets", pending_rasterizer):
            _, metadata = asyncio.run(self.a.render([{"source": self.source}], 128, 128))
        self.assertTrue(metadata["stale"])
        self.assertEqual(metadata["resourceRevision"], 0)
        shown = self.control(action="state")["renders"][0]
        self.assertTrue(shown["metadata"]["stale"])

    def test_explicit_connection_auth_disconnect_and_settings(self):
        self.assertEqual(self.a.configure()["scope"], "Connected VS Code window")
        with self.assertRaisesRegex(ValueError, "belong to VS Code"):
            self.a.configure({"preview": {"width": 400}})
        with self.assertRaisesRegex(ValueError, "connected source"):
            self.a.read({"document": {"name": "detached", "screens": []}})
        discovery = json.loads(Path(self.initial["discoveryFile"]).read_text())
        with self.assertRaises(error.HTTPError) as caught:
            request.urlopen(request.Request(discovery["endpoint"], data=b'{}', method="POST"))
        self.assertEqual(caught.exception.code, 403)
        self.control(action="disconnect", sessionId=self.a.bridge.session_id)
        with self.assertRaisesRegex(BridgeError, "disconnected"):
            self.a.read(self.source)
        self.assertTrue(self.b.read(self.source)["valid"])
        with self.assertRaisesRegex(BridgeError, "editor_unavailable"):
            BridgeClient(Path(self.temporary.name) / "missing.json")


@unittest.skipUnless(ClientSession and shutil.which("node") and (PROJECT / "vscode/node_modules/esbuild").exists(), "MCP SDK, Node and editor dependencies required")
class ConnectedProtocolTests(unittest.IsolatedAsyncioTestCase):
    setUp = BridgeTests.setUp
    stop_host = BridgeTests.stop_host
    control = BridgeTests.control
    service = BridgeTests.service

    @asynccontextmanager
    async def server(self, name, handler=None):
        environment = dict(os.environ, PYTHONPATH=str(PROJECT / "src"), PYTHONUTF8="1")
        params = StdioServerParameters(command=sys.executable, args=["-m", "bgin_json.mcp_server", "--mode", "connected", "--editor-bridge", self.initial["discoveryFile"], "--client-name", name], env=environment, cwd=self.temporary.name)
        with (Path(self.temporary.name) / (name + ".log")).open("w", encoding="utf-8") as log:
            async with stdio_client(params, errlog=log) as (reader, writer):
                async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=30), message_handler=handler) as session:
                    initialized = await session.initialize()
                    self.assertTrue(initialized.capabilities.resources.subscribe)
                    yield session

    async def call(self, session, name, **arguments):
        result = await session.call_tool(name, arguments)
        self.assertFalse(result.isError, result)
        return result.structuredContent or json.loads(next(item.text for item in result.content if item.type == "text"))

    async def test_real_stdio_clients_notifications_and_live_conflicts(self):
        changed = asyncio.Event()

        async def notifications(message):
            root = getattr(message, "root", None)
            if getattr(root, "method", None) == "notifications/resources/updated":
                changed.set()

        async with AsyncExitStack() as stack:
            first = await stack.enter_async_context(self.server("Client-One"))
            second = await stack.enter_async_context(self.server("Client-Two", notifications))
            await second.subscribe_resource(AnyUrl("bgin://editor/state"))
            source = {"documentId": "doc-one"}
            left = await self.call(first, "bgin_read", source=source)
            right = await self.call(second, "bgin_read", source=source)
            result = await self.call(first, "bgin_edit", source=source, operations=[{"op": "replace", "path": "/name", "value": "first client"}], base_revision=left["revision"], operation_id="stdio-edit")
            self.assertEqual(result["revision"], 1)
            await asyncio.wait_for(changed.wait(), timeout=4)
            user_document = {"name": "unsaved human text", "screens": [{"type": "StackContainer", "name": "main"}]}
            self.control(action="user", text=json.dumps(user_document))
            conflict = await second.call_tool("bgin_edit", {"source": source, "operations": [{"op": "replace", "path": "/name", "value": "stale client"}], "base_revision": right["revision"], "operation_id": "stdio-stale"})
            self.assertTrue(conflict.isError)
            self.assertIn("revision_conflict", "".join(item.text for item in conflict.content if item.type == "text"))
            current = await self.call(second, "bgin_read", source=source)
            self.assertEqual(current["document"], user_document)
            self.assertTrue(any(change["origin"] == "user" for change in current["editor"]["changes"]))
            saved = await self.call(second, "bgin_save", source=source, base_revision=current["revision"], operation_id="stdio-save")
            self.assertTrue(saved["saved"])
            if os.environ.get("BGIN_MCP_SKIP_BROWSER") != "1":
                import base64
                rendered = await second.call_tool("bgin_render", {"requests": [{"source": source, "options": {"width": 128, "height": 128, "text": False, "bounds": False}}], "tile_width": 128, "tile_height": 128})
                self.assertFalse(rendered.isError, rendered.content)
                self.assertFalse(rendered.structuredContent["stale"])
                image = next(item for item in rendered.content if item.type == "image")
                self.assertTrue(base64.b64decode(image.data).startswith(b"\x89PNG"))
                gallery = self.control(action="state")["renders"]
                self.assertEqual(len(gallery), 1)
                self.assertEqual(gallery[0]["metadata"]["resourceRevision"], 0)
            await second.unsubscribe_resource(AnyUrl("bgin://editor/state"))


if __name__ == "__main__":
    unittest.main()
