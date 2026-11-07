"""Browser rasterization preserves the SVG renderer's embedded fonts."""

import asyncio
import copy
import json
from io import BytesIO
import math

from PIL import Image, ImageDraw, ImageOps
from playwright.async_api import async_playwright

from bgin_json.render.scene import render
from bgin_json.render.resources import Resources
from .service import at, preview_options, strict_object


async def render_sheets(service, requests, tile_width, tile_height):
    if not isinstance(requests, list) or not 1 <= len(requests) <= 36:
        raise ValueError("Supply 1 to 36 render requests")
    if any(
        type(v) is not int or not 128 <= v <= 2048 for v in (tile_width, tile_height)
    ):
        raise ValueError("Tile dimensions must be integers between 128 and 2048")
    prepared = []
    settings = copy.deepcopy(service.settings)
    documents = {}
    for request in requests:
        strict_object(
            request,
            {"source", "options", "resources", "label", "include_geometry"},
            "render request",
        )
        key = json.dumps(
            request["source"], ensure_ascii=False, allow_nan=False, sort_keys=True
        )
        if key not in documents:
            documents[key] = service.load(request["source"])
        doc, source = documents[key]
        strict_object(
            request.get("options", {}),
            set(settings["preview"]) | set(preview_options({})),
            "options",
        )
        opts = preview_options({**settings["preview"], **request.get("options", {})})
        if opts["screen"] >= len(doc["screens"]):
            raise ValueError("Screen index is outside this document")
        if opts["selected"]:
            node = at(doc, opts["selected"])
            if (
                not isinstance(node, dict)
                or not isinstance(node.get("type"), str)
                or not isinstance(node.get("name"), str)
            ):
                raise ValueError(
                    "Selected path must identify an object, not a property"
                )
            root = f"/screens/{opts['screen']}"
            if opts["selected"] != root and not opts["selected"].startswith(root + "/"):
                raise ValueError("Selected node must belong to the requested screen")
        if not isinstance(request.get("resources", {}), dict):
            raise ValueError("resources must be an object")
        resources = service.resources(
            {**settings["resources"], **request.get("resources", {})}
        )
        if type(request.get("include_geometry", False)) is not bool:
            raise ValueError("include_geometry must be a boolean")
        prepared.append(
            (
                doc,
                source,
                opts,
                resources,
                str(request.get("label", ""))[:160],
                request.get("include_geometry", False),
            )
        )
    images, rows = [], []
    async with async_playwright() as runtime:
        try:
            browser = await runtime.chromium.launch(
                channel=settings["browserChannel"] or None
            )
        except Exception as error:
            raise ValueError(
                "Browser unavailable. Run python -m playwright install chromium, or set browserChannel to msedge/chrome for an installed browser. "
                + str(error)
            ) from error
        try:
            page = await browser.new_page(device_scale_factor=1)
            await page.route("**/*", lambda route: route.abort())
            cache_by_config = {}
            for index, (
                doc,
                source,
                opts,
                resources,
                label,
                include_geometry,
            ) in enumerate(prepared, 1):
                cache_key = (json.dumps(resources, sort_keys=True), source)
                if cache_key not in cache_by_config:
                    if len(cache_by_config) >= 4:
                        cache_by_config.pop(next(iter(cache_by_config)))
                    cache_by_config[cache_key] = Resources(resources, source, set())
                scene = await asyncio.to_thread(
                    render, doc, opts, resources, source, cache_by_config[cache_key]
                )
                await page.set_viewport_size(
                    {
                        "width": math.ceil(opts["width"]),
                        "height": math.ceil(opts["height"]),
                    }
                )
                await page.set_content(
                    "<style>html,body{margin:0;overflow:hidden}svg{display:block}</style>"
                    + scene["svg"]
                )
                await page.evaluate("document.fonts.ready")
                png = await page.screenshot(type="png")
                with Image.open(BytesIO(png)) as image:
                    images.append(
                        ImageOps.contain(
                            image.convert("RGB"), (tile_width, tile_height)
                        )
                    )
                rows.append(
                    {
                        "number": index,
                        "sheet": (index - 1) // 9 + 1,
                        "label": label,
                        "screen": opts["screen"],
                        "selected": opts["selected"],
                        "options": opts,
                        "warnings": scene["warnings"],
                        "errors": scene["errors"],
                    }
                )
                if include_geometry:
                    rows[-1]["geometry"] = scene["geometry"]
        finally:
            await browser.close()
    sheets = []
    for start in range(0, len(images), 9):
        group = images[start : start + 9]
        columns = min(3, len(group))
        sheet = Image.new(
            "RGB",
            (
                columns * tile_width,
                math.ceil(len(group) / columns) * (tile_height + 28),
            ),
            "#181b20",
        )
        draw = ImageDraw.Draw(sheet)
        for offset, image in enumerate(group):
            x = offset % columns * tile_width
            y = offset // columns * (tile_height + 28)
            draw.text((x + 8, y + 6), str(start + offset + 1), fill="white")
            px, py = (
                x + (tile_width - image.width) // 2,
                y + 28 + (tile_height - image.height) // 2,
            )
            sheet.paste(image, (px, py))
            rows[start + offset]["imageRect"] = [px, py, image.width, image.height]
        out = BytesIO()
        sheet.save(out, format="PNG")
        sheets.append(out.getvalue())
    return sheets, {"renders": rows, "sheetCount": len(sheets), "maxPerSheet": 9}
