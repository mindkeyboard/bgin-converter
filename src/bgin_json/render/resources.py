"""Explicit, reloadable project assets with bounded caches and path containment."""

import base64
import struct
from collections import OrderedDict
from io import BytesIO
from pathlib import Path

from ..parser import load
from ..header import read_namespace
from ..vocabulary import ENUMS
from . import textures
from .model import properties, value


class Resources:
    def __init__(self, config, source, warnings):
        self.config, self.warnings = config, warnings
        self.source = Path(source).resolve() if source else None
        self.root = (
            Path(config["assetRoot"]).resolve()
            if config.get("assetRoot")
            else self.source.parent
            if self.source
            else None
        )
        self.styles, self.sprites, self.index = {}, {}, {}
        self.bindings, self.errors = {}, []
        self.image_cache, self.image_bytes = OrderedDict(), 0
        self.uri_cache, self.uri_bytes = OrderedDict(), 0
        self.file_cache = {}
        self.header_cache = {}
        self.fonts = {}
        self.directories = {}
        self.configure(config, source, warnings)

    def configure(self, config, source, warnings):
        self.config, self.warnings = config, warnings
        self.source = Path(source).resolve() if source else None
        self.root = (
            Path(config["assetRoot"]).resolve()
            if config.get("assetRoot")
            else self.source.parent
            if self.source
            else None
        )
        self.errors, self.bindings, self.index, self.sources = [], {}, {}, {}
        folder = config.get("bginRoot")
        if folder:
            self.scan_bgin_folder(Path(folder).resolve())
        else:
            # Old explicit aliases remain readable; no implicit neighboring files are bound.
            for alias, filename in config.get("bindings", {}).items():
                path = Path(filename)
                if path.is_file():
                    self.sources[alias.casefold()] = path
                else:
                    self.errors.append(
                        {
                            "path": "/",
                            "message": f"Resource {alias}: file not found: {filename}",
                        }
                    )

    def scan_bgin_folder(self, folder):
        if not folder.is_dir():
            self.errors.append(
                {"path": "/", "message": f"BGIN directory not found: {folder}"}
            )
            return
        seen, ambiguous = {}, set()
        for directory in (folder, folder / "gui"):
            if not directory.is_dir():
                continue
            for path in sorted(
                directory.iterdir(), key=lambda item: item.name.casefold()
            ):
                if not path.is_file() or path.suffix.casefold() != ".bgin":
                    continue
                try:
                    stat = path.stat()
                    key = (str(path), stat.st_mtime_ns, stat.st_size)
                    name = self.header_cache.get(key)
                    if name is None:
                        with path.open("rb") as stream:
                            name = read_namespace(stream)
                        self.header_cache = {
                            k: v
                            for k, v in self.header_cache.items()
                            if k[0] != str(path)
                        }
                        self.header_cache[key] = name
                    alias = name.casefold()
                    if alias in seen:
                        ambiguous.add(alias)
                        raise ValueError(
                            f"Duplicate BGIN namespace {name}: {seen[alias].name}, {path.name}"
                        )
                    seen[alias] = path
                except (OSError, ValueError) as error:
                    self.errors.append(
                        {"path": "/", "message": f"{path.name}: {error}"}
                    )
        self.sources = {
            alias: filename
            for alias, filename in seen.items()
            if alias not in ambiguous
        }

    def add_binding(self, alias, doc):
        self.bindings[alias.casefold()] = doc

        def visit(root, node, prefix):
            self.index[(alias.casefold(), *prefix)] = (root, node)
            for child in node.get("children", []):
                visit(root, child, (*prefix, child["name"].casefold()))

        for root in doc.get("screens", []):
            visit(root, root, (root["name"].casefold(),))

    def audit(self, document):
        from ..vocabulary import PROPERTY_KINDS

        def visit(node, path):
            for key, raw in properties(node).items():
                reference = value({key: raw}, key)
                if (
                    PROPERTY_KINDS.get(key) == "path"
                    and isinstance(reference, str)
                    and reference.startswith("/")
                ):
                    try:
                        self.lookup(reference)
                    except KeyError:
                        part = key.replace("~", "~0").replace("/", "~1")
                        self.errors.append(
                            {
                                "path": path + "/properties/" + part,
                                "message": f"Unresolved resource {reference}. Check the BGIN folder, internal namespace and object name.",
                            }
                        )
            for group in ("children", "tracks"):
                for i, child in enumerate(node.get(group, [])):
                    visit(child, f"{path}/{group}/{i}")

        for i, root in enumerate(document["screens"]):
            visit(root, f"/screens/{i}")

    def document(self, explicit, name, roots):
        candidates = (
            [Path(explicit)]
            if explicit
            else [r / name for root in roots for r in (root, root / "gui")]
        )
        for p in candidates:
            if p.is_file():
                key = (str(p.resolve()), p.stat().st_mtime_ns, p.stat().st_size)
                if key not in self.file_cache:
                    self.file_cache = {
                        k: v for k, v in self.file_cache.items() if k[0] != key[0]
                    }
                    self.file_cache[key] = load(p)
                return self.file_cache[key]
        if explicit:
            self.warnings.add(f"Ресурс не найден: {name}")
        return {}

    def resolve_file(self, reference, folder="textures_android"):
        override = self.config.get(
            "fontRoot" if folder == "texter_fonts" else "textureRoot"
        )
        search_root = Path(override).resolve() if override else self.root
        if not search_root:
            raise FileNotFoundError("Choose a resource folder")
        # Game Source paths can refer to exporter directories absent from the asset dump.
        # Texture/font basename lookup is confined to explicitly selected resource roots.
        name = Path(str(reference).replace("\\", "/")).name
        if not name or name in (".", ".."):
            raise ValueError("Invalid resource name")
        for directory in (search_root, search_root / folder):
            if not directory.is_dir():
                continue
            stamp = directory.stat().st_mtime_ns
            cached = self.directories.get(directory)
            if cached is None or cached[0] != stamp:
                cached = (
                    stamp,
                    {p.name.casefold(): p for p in directory.iterdir() if p.is_file()},
                )
                self.directories[directory] = cached
            candidate = cached[1].get(name.casefold())
            if candidate:
                resolved = candidate.resolve()
                if not resolved.is_relative_to(search_root):
                    raise ValueError("Resource path leaves selected root")
                return resolved
        raise FileNotFoundError(name)

    def texture(self, root, alpha):
        source = value(properties(root), "Source", "")
        path = self.resolve_file(source)
        mask = path.with_suffix(path.suffix + "__alpha")
        key = (
            str(path),
            path.stat().st_mtime_ns,
            mask.stat().st_mtime_ns if mask.is_file() else 0,
            alpha,
        )
        if key in self.image_cache:
            self.image_cache.move_to_end(key)
            return self.image_cache[key]
        image = textures.read(path, alpha)
        size = image.width * image.height * 4
        while self.image_cache and self.image_bytes + size > 128 * 1024 * 1024:
            _, old = self.image_cache.popitem(last=False)
            self.image_bytes -= old.width * old.height * 4
        if size <= 128 * 1024 * 1024:
            self.image_cache[key] = image
            self.image_bytes += size
        return image

    def lookup(self, reference):
        parts = str(reference).replace("\\", "/").strip("/").split("/")
        if len(parts) < 2:
            raise KeyError("A resource reference must contain a namespace and object")
        alias = parts[0].casefold()
        if alias not in self.bindings:
            filename = self.sources.get(alias)
            if filename is None:
                raise KeyError(reference)
            try:
                doc = self.document(filename, parts[0], [])
                if not doc:
                    raise FileNotFoundError(filename)
                self.add_binding(parts[0], doc)
            except (OSError, ValueError) as error:
                self.errors.append(
                    {"path": "/", "message": f"Resource {parts[0]}: {error}"}
                )
                raise KeyError(reference) from error
        return self.index[tuple(p.casefold() for p in parts)]

    def png(self, root, alpha, crop=None):
        path = self.resolve_file(value(properties(root), "Source", ""))
        mask = path.with_suffix(path.suffix + "__alpha")
        key = (
            str(path),
            path.stat().st_mtime_ns,
            mask.stat().st_mtime_ns if mask.is_file() else 0,
            alpha,
            crop,
        )
        if key in self.uri_cache:
            self.uri_cache.move_to_end(key)
            return self.uri_cache[key]
        image = self.texture(root, alpha)
        if crop is not None:
            x, y, w, h = crop
            if (
                x < 0
                or y < 0
                or w <= 0
                or h <= 0
                or x + w > image.width
                or y + h > image.height
            ):
                raise ValueError("Module rectangle exceeds decoded atlas")
            image = image.crop((round(x), round(y), round(x + w), round(y + h)))
        uri = png_uri(image)
        while self.uri_cache and self.uri_bytes + len(uri) > 64 * 1024 * 1024:
            _, old = self.uri_cache.popitem(last=False)
            self.uri_bytes -= len(old)
        if len(uri) <= 64 * 1024 * 1024:
            self.uri_cache[key] = uri
            self.uri_bytes += len(uri)
        return uri

    def style(self, reference):
        if not reference:
            return {}
        try:
            _, node = self.lookup(reference)
            return properties(node)
        except KeyError:
            return {}

    def font(self, style, height, language):
        from PIL import ImageFont

        key = "FontName" + language if language else "FontName"
        token = value(style, key, value(style, "FontName", {}))
        reference = token.get("text", "") if isinstance(token, dict) else token
        if isinstance(token, dict) and not reference:
            reference = ENUMS.get(key, {}).get(token.get("enum"), (0, 0, ""))[2]
        if not reference:
            self.warnings.add(
                "Шрифт не задан или не разрешён; метрики текста предварительные"
            )
            return ImageFont.load_default(size=max(1, int(height))), None
        try:
            path = self.resolve_file(reference, "texter_fonts")
            cache_key = (str(path), int(height), path.stat().st_mtime_ns)
            if cache_key not in self.fonts:
                if len(self.fonts) > 128:
                    self.fonts.clear()
                self.fonts[cache_key] = ImageFont.truetype(
                    str(path), max(1, min(512, int(height)))
                )
            return self.fonts[cache_key], path
        except (OSError, ValueError):
            self.warnings.add(f"Шрифт не найден: {reference}; метрики предварительные")
            return ImageFont.load_default(size=max(1, int(height))), None


def png_uri(image):
    data = BytesIO()
    image.save(data, format="PNG")
    return "data:image/png;base64," + base64.b64encode(data.getvalue()).decode("ascii")
