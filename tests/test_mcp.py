"""Public MCP contract tests using the official SDK and a real stdio process.

Run: python -m unittest discover -s tests -p test_mcp.py -v
Browser tests run by default. BGIN_MCP_BROWSER=msedge selects installed Edge;
BGIN_MCP_SKIP_BROWSER=1 explicitly omits only the browser scenarios.
Every server gets a temporary config, working directory and resource files.
"""
import base64
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import timedelta
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:
    ClientSession = None


def document():
    return {"name": "mcp-test", "screens": [{
        "type": "HorizontalContainer", "name": "main", "children": [
            {"type": "StackContainer", "name": "Left", "properties": {"StretchFactor": 1}},
            {"type": "StackContainer", "name": "Right", "properties": {"StretchFactor": 3},
             "children": [{"type": "Label", "name": "caption", "properties": {"TestString": "Привет 🌍"}}]},
        ]}]}


@unittest.skipIf(ClientSession is None, "Install the mcp extra to run official SDK integration tests")
class MCPBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bgin-mcp-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / "settings.json"
        self.core = Path(os.environ.get("BGIN_CORE_PATH", str(PROJECT.parent / "tools")))

    @asynccontextmanager
    async def server(self, *, core=None):
        # Preserve interpreter/browser discovery, but never use global MCP settings.
        env = dict(os.environ)
        env["PYTHONPATH"] = str(PROJECT / "src")
        env["PYTHONUTF8"] = "1"
        args = ["-m", "bgin_json.mcp_server", "--config", str(self.config),
                "--core-path", str(core if core is not None else self.core)]
        params = StdioServerParameters(command=sys.executable, args=args, env=env, cwd=str(self.root))
        with (self.root / "server.log").open("a", encoding="utf-8") as errors:
            async with stdio_client(params, errlog=errors) as (reader, writer):
                async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=90)) as session:
                    await session.initialize()
                    yield session

    async def call(self, session, tool_name, **arguments):
        result = await session.call_tool(tool_name, arguments)
        self.assertFalse(result.isError, [getattr(item, "text", "") for item in result.content])
        payload = result.structuredContent
        if payload is None:
            payload = json.loads(next(item.text for item in result.content if item.type == "text"))
        self.assertIsInstance(payload, dict)
        return payload

    async def error(self, session, tool_name, **arguments):
        result = await session.call_tool(tool_name, arguments)
        self.assertTrue(result.isError, result)
        message = "\n".join(getattr(item, "text", "") for item in result.content)
        self.assertTrue(message.strip())
        return message


class MCPProtocolTests(MCPBase):
    async def test_discovery_resource_read_and_relative_file_sources(self):
        from bgin_json import encode
        authored = document()
        (self.root / "source.json").write_text(json.dumps(authored, ensure_ascii=False), encoding="utf-8-sig")
        (self.root / "source.bgin").write_bytes(encode(authored))
        async with self.server() as session:
            names = {tool.name for tool in (await session.list_tools()).tools}
            self.assertTrue({"bgin_read", "bgin_validate", "bgin_search", "bgin_compare",
                             "bgin_settings", "bgin_catalog", "bgin_export", "bgin_render"} <= names)
            resources = await session.list_resources()
            self.assertIn("bgin://skill", {str(item.uri) for item in resources.resources})
            skill = await session.read_resource("bgin://skill")
            self.assertTrue(any("BGIN" in getattr(item, "text", "") for item in skill.contents))
            for filename in ("source.json", "source.bgin"):
                with self.subTest(filename=filename):
                    read = await self.call(session, "bgin_read", source={"path": filename}, depth=0)
                    self.assertEqual(read["document"], authored)
                    self.assertFalse(read["draft"])
                    self.assertEqual(Path(read["source"]), self.root / filename)
                    self.assertEqual(read["tree"][0]["childrenCount"], 2)
                    self.assertNotIn("children", read["tree"][0])
            leaf = await self.call(session, "bgin_read", source={"document": authored},
                                   pointer="/screens/0/children/1/children/0/properties/TestString")
            self.assertEqual(leaf["document"], "Привет 🌍")
            validation = await self.call(session, "bgin_validate", source={"document": authored})
            self.assertTrue(validation["valid"])
            self.assertGreater(validation["bytes"], 0)
            catalog = await self.call(session, "bgin_catalog", type_name="Label")
            self.assertIn("TestString", catalog["properties"])

    async def test_invalid_json_sources_pointers_and_drafts(self):
        invalid = ['{"name":"a","name":"b","screens":[]}',
                   '{"name":"a","screens":[],"value":NaN}',
                   '{"name":"a","screens":[],"value":Infinity}']
        (self.root / "blank.bgin").write_bytes(b"")
        async with self.server() as session:
            for raw in invalid:
                await self.error(session, "bgin_read", source={"document": raw})
            for source in ({}, {"path": "missing.json"}, {"path": "x", "document": document()},
                           {"document": document(), "unexpected": True}):
                await self.error(session, "bgin_read", source=source)
            for pointer in ("screens/0", "/screens/-1", "/screens/00", "/screens/2", "/missing"):
                await self.error(session, "bgin_read", source={"document": document()}, pointer=pointer)
            for source in ({"path": "blank.bgin"}, {"document": {"name": "draft", "screens": []}}):
                draft = await self.call(session, "bgin_read", source=source)
                self.assertTrue(draft["draft"])
                self.assertEqual(draft["tree"], [])
                if "path" in source:
                    self.assertNotIn("name", draft["document"])
                    checked = await self.call(session, "bgin_validate", source=source)
                    self.assertTrue(checked["valid"])
                    self.assertTrue(checked["warnings"])
                    saved = await self.call(session, "bgin_export", source=source, destination="empty-copy.bgin")
                    self.assertEqual((self.root / "empty-copy.bgin").read_bytes(), b"")
                    self.assertFalse(saved["independentBinaryCheck"])
                else:
                    await self.error(session, "bgin_validate", source=source)
            # A rejected request must not terminate the process or poison its state.
            self.assertTrue((await self.call(session, "bgin_validate", source={"document": document()}))["valid"])

    async def test_search_compare_and_bounded_results(self):
        before = document()
        after = deepcopy(before)
        after["name"] = "changed"
        after["screens"][0]["children"][1]["children"][0]["properties"]["TestString"] = "new text"
        async with self.server() as session:
            found = await self.call(session, "bgin_search", source={"document": before}, query="rIgHt")
            self.assertEqual(found["matches"], [{"path": "/screens/0/children/1", "name": "Right", "type": "StackContainer"}])
            limited = await self.call(session, "bgin_search", source={"document": before}, type_name="StackContainer", limit=1)
            self.assertEqual(limited["total"], 2)
            self.assertEqual(len(limited["matches"]), 1)
            self.assertTrue(limited["truncated"])
            diff = await self.call(session, "bgin_compare", before={"document": before}, after={"document": after})
            self.assertFalse(diff["equal"])
            self.assertEqual({item["path"] for item in diff["changes"]},
                             {"/name", "/screens/0/children/1/children/0/properties/TestString"})
            limited = await self.call(session, "bgin_compare", before={"document": before}, after={"document": after}, limit=1)
            self.assertEqual(len(limited["changes"]), 1)
            self.assertTrue(limited["truncated"])
            same = await self.call(session, "bgin_compare", before={"document": before}, after={"document": before})
            self.assertEqual(same, {"equal": True, "changes": [], "truncated": False})

    async def test_settings_import_persistence_and_invalid_path_atomicity(self):
        (self.root / "textures").mkdir()
        async with self.server() as session:
            initial = await self.call(session, "bgin_settings")
            self.assertEqual(Path(initial["path"]), self.config)
            self.assertFalse(self.config.exists())
            configured = await self.call(session, "bgin_settings", editor_settings={
                "bgin.preview": {"width": 320, "height": 240, "grid": True},
                "bgin.resourceFolders": {"textureRoot": "textures"},
                "editor.fontSize": 16,
            }, changes={"preview": {"width": 400, "height": 240, "grid": True}})
            self.assertEqual(configured["effectivePreview"]["width"], 400)
            original = self.config.read_bytes()
            for changes in ({"resources": {"textureRoot": "missing"}},
                            {"resources": {"bindings": {"widgets": "missing.bgin"}}},
                            {"preview": {"width": True}}, {"preview": {"screen": -1}},
                            {"preview": {"invented": True}}, {"browserChannel": "unknown"}):
                await self.error(session, "bgin_settings", changes=changes)
                self.assertEqual(self.config.read_bytes(), original)
            updated = await self.call(session, "bgin_settings", changes={"preview": {"height": 300}})
            self.assertEqual(Path(updated["saved"]["backup"]).read_bytes(), original)
        async with self.server() as session:
            restored = await self.call(session, "bgin_settings")
            self.assertEqual(restored["effectivePreview"]["width"], 400)
            self.assertEqual(restored["effectivePreview"]["height"], 300)
            self.assertTrue(restored["effectivePreview"]["grid"])
            self.assertEqual(restored["settings"]["resources"]["textureRoot"], "textures")

    async def test_export_independent_codec_nonoverwrite_backup_and_recovery(self):
        if not (self.core / "bgin_core" / "__init__.py").is_file():
            self.skipTest("Set BGIN_CORE_PATH to the parent of the independent bgin_core package")
        sys.path.insert(0, str(self.core))
        import bgin_core
        from bgin_json import parse
        target = self.root / "export.bgin"
        sentinel = b"existing user bytes\x00\xff"
        target.write_bytes(sentinel)
        async with self.server() as session:
            await self.error(session, "bgin_export", source={"document": document()}, destination="export.bgin")
            self.assertEqual(target.read_bytes(), sentinel)
            result = await self.call(session, "bgin_export", source={"document": document()}, destination="export.bgin", overwrite=True)
            self.assertTrue(result["independentBinaryCheck"])
            backup = Path(result["backup"])
            self.assertEqual(backup.read_bytes(), sentinel)
            raw = target.read_bytes()
            independent = bgin_core.BginSession(raw, "ui")
            self.assertEqual(bgin_core.encode_document(independent.snapshot(), force=True), raw)
            self.assertEqual(parse(raw), document())
            await self.error(session, "bgin_export", source={"path": "export.bgin"}, destination="export.bgin", overwrite=True)
            self.assertEqual(target.read_bytes(), raw)
            target.write_bytes(backup.read_bytes())
            self.assertEqual(target.read_bytes(), sentinel)
            exported = await self.call(session, "bgin_export", source={"document": document()}, destination="export.json", format="json")
            self.assertIsNone(exported["backup"])
            self.assertEqual(json.loads((self.root / "export.json").read_text(encoding="utf-8")), document())

    async def test_missing_independent_codec_cannot_publish_binary(self):
        async with self.server(core=self.root / "no-core") as session:
            message = await self.error(session, "bgin_export", source={"document": document()}, destination="blocked.bgin")
            self.assertIn("bgin_core", message)
            self.assertFalse((self.root / "blocked.bgin").exists())
            await self.call(session, "bgin_export", source={"document": document()}, destination="usable.json", format="json")

    async def test_create_edit_validate_export_workflow_is_atomic(self):
        async with self.server() as session:
            created = await self.call(session, "bgin_create", name="new", root_type="StackContainer")
            node = await self.call(session, "bgin_create", root_type="Label", screen_name="added", node_only=True)
            original = created["document"]
            source_file = self.root / "editing.json"
            source_file.write_text(json.dumps(original), encoding="utf-8")
            before_bytes = source_file.read_bytes()
            edited = await self.call(session, "bgin_edit", source={"path": "editing.json"}, operations=[
                {"op": "test", "path": "/name", "value": "new"},
                {"op": "add", "path": "/screens/0/children/-", "value": node["node"]},
                {"op": "add", "path": "/screens/0/children/0/properties/TestString", "value": "created through MCP"},
                {"op": "replace", "path": "/screens/0/name", "value": "edited"},
            ])
            self.assertTrue(edited["validation"]["valid"])
            self.assertEqual(edited["document"]["screens"][0]["children"][0]["properties"]["TestString"], "created through MCP")
            self.assertEqual(source_file.read_bytes(), before_bytes)
            await self.error(session, "bgin_edit", source={"path": "editing.json"}, operations=[
                {"op": "replace", "path": "/name", "value": "must not leak"},
                {"op": "test", "path": "/screens/0/name", "value": "wrong precondition"},
            ])
            self.assertEqual(source_file.read_bytes(), before_bytes)
            reread = await self.call(session, "bgin_read", source={"path": "editing.json"})
            self.assertEqual(reread["document"], original)
            removed = await self.call(session, "bgin_edit", source={"document": edited["document"]}, operations=[
                {"op": "remove", "path": "/screens/0/children/0"}])
            self.assertEqual(removed["document"]["screens"][0]["children"], [])
            await self.call(session, "bgin_export", source={"document": edited["document"]}, destination="edited.json", format="json")
            self.assertEqual(json.loads((self.root / "edited.json").read_text(encoding="utf-8")), edited["document"])

    async def test_resource_report_and_repair_missing_saved_directory(self):
        self.config.write_text(json.dumps({"resources": {"textureRoot": "removed-directory"}}), encoding="utf-8")
        async with self.server() as session:
            report = await self.call(session, "bgin_resource_report", source={"document": document()})
            self.assertTrue(any("textureRoot" in item["message"] for item in report["errors"]))
            await self.call(session, "bgin_settings", changes={"resources": {"textureRoot": ""}})
            repaired = await self.call(session, "bgin_resource_report", source={"document": document()})
            self.assertEqual(repaired["errors"], [])
            for topic in ("skill", "objects", "json-format", "design"):
                guide = await session.call_tool("bgin_guide", {"topic": topic})
                self.assertFalse(guide.isError)
                self.assertGreater(sum(len(getattr(item, "text", "")) for item in guide.content), 100)
            await self.error(session, "bgin_guide", topic="../../settings")
            prompt = await session.get_prompt("edit_bgin", {"task": "Create a label"})
            self.assertIn("Create a label", prompt.messages[0].content.text)

    async def test_render_rejects_invalid_requests_before_browser_launch(self):
        async with self.server() as session:
            for requests in ([], [{"source": {"document": document()}}] * 37,
                             [{"source": {"document": document()}, "options": {"selected": "/screens/0/name"}}],
                             [{"source": {"document": document()}, "options": {"screen": 8}}],
                             [{"source": {"document": document()}, "resources": {"textureRoot": "missing"}}]):
                await self.error(session, "bgin_render", requests=requests)
            await self.error(session, "bgin_render", requests=[{"source": {"document": document()}}], tile_width=127)


@unittest.skipIf(os.environ.get("BGIN_MCP_SKIP_BROWSER") == "1", "Browser tests explicitly disabled")
class MCPBrowserTests(MCPBase):
    async def setup_browser(self, session):
        await self.call(session, "bgin_settings", changes={
            "browserChannel": os.environ.get("BGIN_MCP_BROWSER", ""),
            "preview": {"width": 128, "height": 128, "bounds": False,
                        "checkerboard": False, "text": False, "background": "#123456"}})

    async def test_ten_renders_produce_two_numbered_sheets_and_real_pixels(self):
        from PIL import Image
        colors = ["#%02x%02x%02x" % (20 + n * 15, 40 + n * 10, 60 + n * 5) for n in range(10)]
        async with self.server() as session:
            await self.setup_browser(session)
            result = await session.call_tool("bgin_render", {"requests": [
                {"source": {"document": document()}, "label": f"variant {n + 1}", "options": {"background": color}}
                for n, color in enumerate(colors)], "tile_width": 128, "tile_height": 128})
            self.assertFalse(result.isError, result.content)
            metadata = result.structuredContent
            self.assertEqual(metadata["sheetCount"], 2)
            self.assertEqual(metadata["maxPerSheet"], 9)
            images = [Image.open(BytesIO(base64.b64decode(item.data))).convert("RGB")
                      for item in result.content if item.type == "image"]
            self.assertEqual([im.size for im in images], [(384, 468), (128, 156)])
            self.assertEqual(len(metadata["renders"]), 10)
            for index, row in enumerate(metadata["renders"]):
                self.assertEqual(row["number"], index + 1)
                self.assertEqual(row["sheet"], index // 9 + 1)
                self.assertEqual(row["label"], f"variant {index + 1}")
                self.assertEqual(row["errors"], [])
                x, y, width, height = row["imageRect"]
                self.assertEqual((x, y, width, height), ((index % 9) % 3 * 128, (index % 9) // 3 * 156 + 28, 128, 128))
                expected = tuple(int(colors[index][i:i + 2], 16) for i in (1, 3, 5))
                image = images[row["sheet"] - 1]
                self.assertEqual(image.getpixel((x + 64, y + 64)), expected)
                # The number band contains rasterized white glyph pixels, not just metadata.
                band = image.crop((x, y - 28, x + 36, y))
                self.assertTrue(any(min(band.getpixel((bx, by))) > 180
                                    for bx in range(band.width) for by in range(band.height)))
            defaults = await self.call(session, "bgin_settings")
            self.assertEqual(defaults["effectivePreview"]["background"], "#123456")

    async def test_selected_descendant_retains_ancestor_geometry_in_actual_image(self):
        from PIL import Image
        # A 1:3 split puts the selected right child at x=32, width=96.
        authored = document()
        authored["screens"][0]["children"][1].pop("children")
        async with self.server() as session:
            await self.setup_browser(session)
            result = await session.call_tool("bgin_render", {"requests": [{
                "source": {"document": authored}, "include_geometry": True,
                "options": {"selected": "/screens/0/children/1", "debugFill": True}}],
                "tile_width": 128, "tile_height": 128})
            self.assertFalse(result.isError, result.content)
            row = result.structuredContent["renders"][0]
            self.assertEqual(row["selected"], "/screens/0/children/1")
            right = next(box for box in row["geometry"] if box["name"] == "Right")
            self.assertEqual(tuple(right[key] for key in ("x", "y", "width", "height")), (32, 0, 96, 128))
            image_data = next(item.data for item in result.content if item.type == "image")
            image = Image.open(BytesIO(base64.b64decode(image_data))).convert("RGB")
            self.assertEqual(image.getpixel((16, 28 + 64)), (18, 52, 86))
            self.assertNotEqual(image.getpixel((64, 28 + 64)), (18, 52, 86))
            background = (18, 52, 86)
            painted = [x for x in range(128) if image.getpixel((x, 28 + 64)) != background]
            self.assertEqual((min(painted), max(painted), len(painted)), (32, 127, 96))


if __name__ == "__main__":
    unittest.main()
