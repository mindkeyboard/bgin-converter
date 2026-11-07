"""Stdio MCP entrypoint. No game resources are bundled."""

import argparse
import asyncio
import base64
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent

from bgin_json.catalog import catalog
from .service import Service


def create_server(service):
    server = FastMCP(
        "BGIN",
        instructions="Read bgin://skill before editing. Use bgin_catalog for exact property names. Render is a preview, not a running game.",
    )

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
    def bgin_edit(source: dict, operations: list[dict]) -> dict:
        """Apply atomic in-memory JSON pointer add/replace/remove/test operations, validate, return the document and differences. Does not write files."""
        return service.edit(source, operations)

    @server.tool()
    def bgin_resource_report(source: dict, resources: dict | None = None) -> dict:
        """Check resource folders and BGIN namespace references without rasterization."""
        return service.resource_report(source, resources)

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
        from .sheets import render_sheets

        async with render_lock:
            sheets, metadata = await render_sheets(
                service, requests, tile_width, tile_height
            )
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
    args = parser.parse_args()
    create_server(Service(args.config, args.core_path)).run(transport="stdio")
