"""Stdio MCP entrypoint. No game resources are bundled."""

import argparse
import asyncio
import base64
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent
from pydantic import AnyUrl

from bgin_json.catalog import catalog
from .service import Service


def create_server(service):
    subscriptions = {}

    @asynccontextmanager
    async def lifespan(_):
        try:
            yield {}
        finally:
            for task in subscriptions.values():
                task.cancel()
            if subscriptions:
                await asyncio.gather(*subscriptions.values(), return_exceptions=True)
            if getattr(service, "connected", False):
                await asyncio.to_thread(service.bridge.close)

    server = FastMCP(
        "BGIN",
        instructions="Read bgin://skill before editing. Use bgin_catalog for exact property names. Render is a preview, not a running game. " + (
            "Connected mode shares unsaved VS Code documents. Read their documentId and revision; edits require base_revision and operation_id. Human changes invalidate stale edits. Subscribe to bgin://editor/state or call bgin_editor to receive changes."
            if getattr(service, "connected", False) else
            "Standalone mode edits detached copies. It is not connected to a live VS Code document."
        ),
        lifespan=lifespan,
    )

    if getattr(service, "connected", False):
        # MCP 1.x FastMCP advertises subscribe=False even when low-level
        # subscription handlers are registered; advertise the implemented path.
        original_capabilities = server._mcp_server.get_capabilities

        def capabilities(notification_options, experimental_capabilities):
            result = original_capabilities(notification_options, experimental_capabilities)
            if result.resources is not None:
                result.resources.subscribe = True
            return result

        server._mcp_server.get_capabilities = capabilities

        @server.resource("bgin://editor/state")
        def editor_state() -> str:
            """Live document revisions and pending manual/client changes."""
            return json.dumps(service.changes(), ensure_ascii=False)

        @server._mcp_server.subscribe_resource()
        async def subscribe(uri: AnyUrl):
            if str(uri) != "bgin://editor/state":
                raise ValueError("Subscribe to bgin://editor/state")
            key = str(uri)
            if key in subscriptions:
                return
            session = server._mcp_server.request_context.session

            async def monitor():
                cursor = service.bridge.cursor
                while True:
                    await asyncio.sleep(0.5)
                    try:
                        await asyncio.to_thread(service.bridge.call, "documents/changes")
                        updated = service.bridge.cursor
                        if updated != cursor:
                            cursor = updated
                            await session.send_resource_updated(AnyUrl(key))
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # A disconnected editor is reported by the next call;
                        # notifications never trigger a detached disk fallback.
                        await asyncio.sleep(1)

            subscriptions[key] = asyncio.create_task(monitor())

        @server._mcp_server.unsubscribe_resource()
        async def unsubscribe(uri: AnyUrl):
            task = subscriptions.pop(str(uri), None)
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    @server.tool()
    def bgin_editor(action: str = "documents") -> dict:
        """Read connected editor documents or changes. Standalone mode has no shared editor state."""
        if not getattr(service, "connected", False):
            return {"mode": "standalone", "connected": False}
        if action not in ("documents", "changes"):
            raise ValueError("action must be documents or changes")
        return service.documents() if action == "documents" else service.changes()

    @server.tool()
    def bgin_save(source: dict, base_revision: int, operation_id: str) -> dict:
        """Save a live document through VS Code using its current revision; retains editor save and conflict checks."""
        if not getattr(service, "connected", False):
            raise ValueError("bgin_save requires explicit connected mode; standalone exports use bgin_export")
        return service.save(source, base_revision, operation_id)

    @server.resource("bgin://skill")
    def skill() -> str:
        return (Path(__file__).parent / "skills/bgin-edit/SKILL.md").read_text(
            encoding="utf-8"
        )

    @server.resource("bgin://guide/{topic}")
    def guide_resource(topic: str) -> str:
        return guide(topic)

    def guide(topic):
        if topic == "skill":
            return skill()
        if topic not in ("objects", "json-format", "design"):
            raise ValueError("topic must be skill, objects, json-format or design")
        return (
            Path(__file__).parent / "skills/bgin-edit/references" / (topic + ".md")
        ).read_text(encoding="utf-8")

    @server.tool()
    def bgin_guide(topic: str = "skill") -> str:
        """Read the bundled editing skill or a reference: objects, json-format, design."""
        return guide(topic)

    @server.prompt()
    def edit_bgin(task: str) -> str:
        """Load the bundled BGIN skill with the user's editing task."""
        return skill() + "\n\nUser task:\n" + task

    @server.tool()
    def bgin_read(
        source: dict, pointer: str = "", depth: int = 2, include_document: bool = True
    ) -> dict:
        """Parse a path or inspect an editable document. Source contains path OR document. Use include_document=false for a compact tree, or pointer to return one subtree/value."""
        return service.read(source, pointer, depth, include_document)

    @server.tool()
    def bgin_validate(source: dict) -> dict:
        """Validate editable JSON and compile it in memory; report loader coverage warnings."""
        return service.validate(source)

    @server.tool()
    def bgin_search(
        source: dict, query: str = "", type_name: str = "", limit: int = 100
    ) -> dict:
        """Find node names/types and their JSON pointers without modifying the document."""
        return service.search(source, query, type_name, limit)

    @server.tool()
    def bgin_compare(before: dict, after: dict, limit: int = 200) -> dict:
        """Compare two sources and return structured changes."""
        return service.compare(before, after, limit)

    @server.tool()
    def bgin_create(
        name: str = "Untitled",
        dialect: str = "ui",
        root_type: str = "StackContainer",
        screen_name: str = "main",
        node_only: bool = False,
    ) -> dict:
        """Create editable JSON in memory. Properties remain unset, using loader defaults. node_only returns a node for insertion."""
        return service.create(name, dialect, root_type, screen_name, node_only)

    @server.tool()
    def bgin_edit(source: dict, operations: list[dict], base_revision: int | None = None, operation_id: str = "") -> dict:
        """Apply atomic JSON-pointer operations. Connected mode requires base_revision and operation_id and updates the live editor with undo; standalone returns a detached copy."""
        if getattr(service, "connected", False):
            return service.edit(source, operations, base_revision, operation_id)
        if base_revision is not None or operation_id:
            raise ValueError("Revision arguments require connected mode")
        return service.edit(source, operations)

    @server.tool()
    def bgin_resource_report(source: dict, resources: dict | None = None, target_format: str | None = None) -> dict:
        """Check resource folders and BGIN namespace references without rasterization."""
        return service.resource_report(source, resources, target_format)

    @server.tool()
    def bgin_export(
        source: dict, destination: str, format: str = "bgin", overwrite: bool = False
    ) -> dict:
        """Export JSON or independently verified BGIN. Existing destinations require overwrite and receive a backup."""
        return service.export(source, destination, format, overwrite)

    @server.tool()
    def bgin_settings(
        changes: dict | None = None, editor_settings: dict | None = None
    ) -> dict:
        """Read defaults, or persist preview/resource overrides. Accepts parsed VS Code settings."""
        return service.configure(changes, editor_settings)

    @server.tool()
    def bgin_catalog(type_name: str = "") -> dict:
        """Get supported types, loader properties, enum choices and preview coverage."""
        result = catalog()
        if not type_name:
            return result
        if type_name not in result["schemas"]:
            raise ValueError("Unknown type")
        names = result["schemas"][type_name]
        return {
            "type": type_name,
            "properties": {n: result["properties"][n] for n in names},
        }

    @server.tool()
    async def bgin_render(
        requests: list[dict], tile_width: int = 640, tile_height: int = 400
    ) -> CallToolResult:
        """Render 1..36 requests into numbered PNG sheets (at most 9 per sheet) plus JSON index. Each request has source and optional options/resources/label/include_geometry. Select nodes with options.selected and keep the full document to preserve ancestor layout. Tile dimensions control output size, not layout resolution."""
        async with render_lock:
            if getattr(service, "connected", False):
                sheets, metadata = await service.render(requests, tile_width, tile_height)
            else:
                from .sheets import render_sheets
                sheets, metadata = await render_sheets(service, requests, tile_width, tile_height)
        return CallToolResult(
            content=[
                TextContent(type="text", text=json.dumps(metadata, ensure_ascii=False)),
                *[
                    ImageContent(
                        type="image",
                        mimeType="image/png",
                        data=base64.b64encode(data).decode(),
                    )
                    for data in sheets
                ],
            ],
            structuredContent=metadata,
        )

    render_lock = asyncio.Lock()
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--core-path")
    parser.add_argument("--mode", choices=("connected", "standalone"), default=None)
    parser.add_argument("--editor-bridge", default=os.getenv("BGIN_EDITOR_BRIDGE"), help="Discovery JSON of the target VS Code window; implies connected mode")
    parser.add_argument("--client-name", default="BGIN MCP", help="Name shown in the editor connections panel")
    args = parser.parse_args()
    mode = args.mode or ("connected" if args.editor_bridge else "standalone")
    if mode == "connected":
        if not args.editor_bridge:
            parser.error("connected mode requires --editor-bridge or BGIN_EDITOR_BRIDGE")
        from .bridge import ConnectedService
        service = ConnectedService(args.editor_bridge, args.client_name, args.config, args.core_path)
    else:
        if args.editor_bridge:
            parser.error("--editor-bridge cannot be used with standalone mode")
        service = Service(args.config, args.core_path)
    create_server(service).run(transport="stdio")
