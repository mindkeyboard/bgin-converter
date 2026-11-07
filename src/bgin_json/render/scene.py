"""Generate an SVG scene from calculated geometry and external project resources."""

import math
from xml.sax.saxutils import escape, quoteattr

from .layout import Layout
from .model import Rect, enum, factor_margins, margins, number, properties, value
from .resources import Resources
from .sprites import Sprites
from .text import advance, initial_offsets, wrapped_lines
from .widgets import paint

DEFAULTS = dict(
    width=1280,
    height=720,
    screen=0,
    selected="",
    pixelsPerMm=3.78,
    frame=0,
    interpolate=True,
    alpha=True,
    clipping=True,
    rtl=False,
    page=0,
    scrollX=0,
    scrollY=0,
    showHidden=False,
    bounds=True,
    names=False,
    sizes=False,
    margins=False,
    grid=False,
    gridSize=32,
    background="#20242b",
    checkerboard=True,
    smooth=True,
    text=True,
    sprites=True,
    debugFill=False,
    opacity=1,
    state="normal",
    progress=0.5,
    fontScale=1,
    language="",
    selectionOnly=True,
)


def options(raw):
    out = {**DEFAULTS, **(raw or {})}
    for key, lo, hi in (
        ("width", 16, 8192),
        ("height", 16, 8192),
        ("pixelsPerMm", 0.01, 100),
        ("frame", 0, 1000000),
        ("page", 0, 10000),
        ("scrollX", -100000, 100000),
        ("scrollY", -100000, 100000),
        ("gridSize", 1, 1024),
        ("opacity", 0, 1),
        ("progress", 0, 1),
        ("fontScale", 0.1, 10),
    ):
        v = out[key]
        if not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
            raise ValueError(f"Invalid preview option: {key}")
    if out["state"] not in ("normal", "pressed", "toggled", "disabled"):
        raise ValueError("Invalid widget state")
    for key, default in DEFAULTS.items():
        if isinstance(default, bool) and type(out[key]) is not bool:
            raise ValueError(f"Invalid preview boolean: {key}")
    if not isinstance(out["background"], str) or len(out["background"]) > 32:
        raise ValueError("Invalid background color")
    return out


def color(values, default="#ffffff"):
    if not isinstance(values, (list, tuple)) or len(values) < 3:
        return default
    return "#" + "".join(
        f"{round(max(0, min(1, float(c))) * 255):02x}" for c in values[:3]
    )


class Scene:
    def __init__(
        self, document, raw_options=None, config=None, source="", resources=None
    ):
        self.document, self.o = document, options(raw_options)
        self.warnings = set()
        if document.get("format") == "legacy":
            self.warnings.add("Legacy BGIN: layout uses the current preview model; older engine behaviour may differ")
        self.resources = resources or Resources(config or {}, source, self.warnings)
        self.resources.configure(config or {}, source, self.warnings)
        # The open document provides its own namespace; other aliases are explicit bindings.
        self.resources.add_binding(document["name"], document)
        if source:
            from pathlib import Path

            for alias, path in (config or {}).get("bindings", {}).items():
                if Path(path).resolve() == Path(source).resolve():
                    self.resources.add_binding(alias, document)
        self.resources.audit(document)
        self.sprites = Sprites(self.resources, self.o, self.warnings)
        self.definitions = []
        self.text_data = {}
        self.content_sizes = {}
        self.text_reference_sizes = {}
        self.font_ids = {}

    def text_style(self, node, content_rect=None):
        p = properties(node)
        style = {**self.resources.style(value(p, "TextStyle", "")), **p}
        state = self.o["state"]
        key = {
            "pressed": "PressedTextStyle",
            "toggled": "ToggledTextStyle",
            "disabled": "DisabledTextStyle",
        }.get(state)
        if key and key in p:
            style = {**style, **self.resources.style(value(p, key))}
        font_height = value(style, "FontHeight", 20)
        font_bounds = None
        if isinstance(font_height, list):
            if (
                node["type"] in ("Label", "Button", "TextArea")
                and len(font_height) == 2
                and all(isinstance(part, (int, float)) and math.isfinite(part) for part in font_height)
            ):
                # GetJetTextStyle clamps world units before converting to pixels.
                font_bounds = tuple(part * self.o["pixelsPerMm"] for part in font_height)
            else:
                self.warnings.add(
                    "FontHeight: размер пары применяется в предпросмотре; все режимы единиц движка ещё не воспроизведены"
                )
            font_height = font_height[-1] if font_height else 20
        if not isinstance(font_height, (int, float)):
            font_height = 20
        if node["type"] == "TextArea":
            # LoadTextAreaParam stores a screen-height percentage, not a font scale.
            font_height = self.o["height"] * number(p, "FontHeightFactor", 10) / 100
            if font_bounds is not None:
                font_height = min(max(font_height, font_bounds[0]), font_bounds[1])
        elif (
            node["type"] in ("Label", "Button")
            and enum(p, "VerticalTextPolicy") == 1
            and "HeightFactor" in p
        ):
            font_height = self.o["height"] * number(p, "HeightFactor") / 100
            top, bottom, _, _ = factor_margins(p, (0, font_height))
            font_height -= top + bottom
            if font_bounds is not None:
                font_height = min(max(font_height, font_bounds[0]), font_bounds[1])
        elif font_bounds is not None and enum(p, "VerticalTextPolicy") == 2:
            # RefreshMinLabelSize measures at the lower bound. RenderText fits
            # that reference width into the final inner rectangle instead.
            font_height = font_bounds[0]
            if content_rect is not None:
                _, reference_height, text, font, _ = self.text_data.get(id(node)) or self.text_style(node)
                # Raster metrics use integer font sizes; SVG preserves the style scale.
                width = advance(font, text, reference_height)
                ppm = self.o["pixelsPerMm"]
                available_width = math.floor(content_rect.w / ppm) * ppm
                requested = content_rect.h
                if width > 0:
                    requested = min(requested, available_width / width * font_bounds[0])
                font_height = min(max(requested, font_bounds[0]), font_bounds[1])
        elif font_bounds is not None and node["type"] in ("Label", "Button"):
            # Default uses the final inner height when drawing and the style
            # minimum for the vertical layout constraint.
            requested = content_rect.h if content_rect is not None else font_bounds[0]
            font_height = min(max(requested, font_bounds[0]), font_bounds[1])
        height = max(
            1,
            min(
                512,
                float(font_height)
                * self.o["fontScale"]
                * (100 if node["type"] == "TextArea" else number(style, "FontHeightFactor", 100))
                / 100,
            ),
        )
        if self.o["language"]:
            height *= number(style, "FontScaling" + self.o["language"], 100) / 100
            height = max(1, min(512, height))
        token = str(value(p, "TestString", value(p, "Text", node["name"])))
        font, path = self.resources.font(style, height, self.o["language"])
        return style, height, token, font, path

    def minimum_content(self, node, size=None):
        p = properties(node)
        dependent = node["type"] == "TextArea" or (
            node["type"] in ("Label", "Button") and enum(p, "VerticalTextPolicy") == 0
        )
        key = (id(node), size) if dependent else id(node)
        if key not in self.content_sizes:
            self.content_sizes[key] = self._minimum_content(node, size) if dependent else self._minimum_content(node)
        return self.content_sizes[key]

    def _minimum_content(self, node, size=None):
        """Return the virtual GetContentSize contribution, not the sprite's pixel bounds."""
        p, kind = properties(node), node["type"]
        if kind == "CompoundButton":
            # CompoundButton inherits StackContainer; its children determine layout size.
            return 0, 0
        if kind in (
            "Label",
            "TextArea",
            "Button",
            "ThreeCellButton",
            "TextStyle",
        ):
            style, height, text, font, path = self.text_style(node)
            box = font.getbbox(text)
            self.text_data[id(node)] = style, height, text, font, path
            content_height = max(height, box[3] - box[1])
            if kind == "TextArea":
                lines, line_height = wrapped_lines(font, text, height, size[0] if size else 0, self.o["language"] == "ZH")
                return 0, len(lines) * line_height if text else 0
            if kind not in ("Label", "Button"):
                return max(0, box[2] - box[0]), content_height
            policy = enum(p, "TextPolicy")
            content_width = advance(font, text, height)
            if enum(p, "VerticalTextPolicy") == 0 and size is not None:
                inner = Rect(0, 0, *size).inset(factor_margins(p, size))
                _, draw_height, _, draw_font, _ = self.text_style(node, inner)
                content_width = advance(draw_font, text, draw_height)
            if enum(p, "VerticalTextPolicy") == 1 and "HeightFactor" in p:
                content_height = self.o["height"] * number(p, "HeightFactor") / 100
            self.text_reference_sizes[id(node)] = content_width, content_height
            if policy == 0:
                return content_width, content_height
            if policy in (1, 2):
                return 0, content_height
            return 0, 0
        # Movie inherits Widget::GetContentSize, which returns zero on both axes.
        # Sprite bounds are used only while drawing into the assigned rectangle.
        return (0, 0)

    def text(self, item):
        node, r = item.node, item.rect
        p = properties(node)
        area = node["type"] == "TextArea"
        verified_label = node["type"] in ("Label", "Button")
        if verified_label:
            r = r.inset(factor_margins(p, (r.w, r.h)))
        elif not area:
            top, bottom, left, right = margins(p, "MarginFactors", 0.01)
            r = r.inset((r.h * top, r.h * bottom, r.w * left, r.w * right))
        style, height, text, font, path = self.text_data.get(
            id(node)
        ) or self.text_style(node)
        if verified_label and enum(p, "VerticalTextPolicy") in (0, 2):
            style, height, text, font, path = self.text_style(node, r)
        family = "sans-serif"
        if path:
            font_id = self.font_ids.get(str(path))
            import base64

            if font_id is None:
                font_bytes = path.read_bytes()
                if len(font_bytes) <= 8 * 1024 * 1024:
                    font_id = "font" + str(len(self.font_ids))
                    self.font_ids[str(path)] = font_id
                    uri = "data:font/ttf;base64," + base64.b64encode(font_bytes).decode(
                        "ascii"
                    )
                    self.definitions.append(
                        f"<style>@font-face{{font-family:{font_id};src:url('{uri}')}}</style>"
                    )
            family = font_id or family
        align = value(p, "Alignment", {})
        label = align.get("enum", "Center") if isinstance(align, dict) else "Center"
        fraction, vertical = {
            "TopLeft": (0, 0),
            "TopRight": (1, 0),
            "Top": (0.5, 0),
            "Left": (0, 0.5),
            "Right": (1, 0.5),
            "BottomLeft": (0, 1),
            "Bottom": (0.5, 1),
            "BottomRight": (1, 1),
        }.get(label, (0.5, 0.5))
        if self.o["rtl"]:
            fraction = 1 - fraction
        if self.o["language"] == "AR" and number(p, "InvertAlignmentRTL") > 0.5:
            fraction = 1 - fraction
        text_clip = ""
        if area:
            text_clip = "textClip" + str(len(self.definitions))
            self.definitions.append(
                f'<clipPath id="{text_clip}"><rect x="{r.x:g}" y="{r.y:g}" width="{r.w:g}" height="{r.h:g}"/></clipPath>'
            )
        reference_width, reference_height = self.text_reference_sizes.get(
            id(node), (advance(font, text, height), height)
        )
        overflowing = verified_label and reference_width > r.w
        if overflowing:
            # RenderText tests cached width, before applying the final draw style.
            fraction = 0
            clip_id = "textClip" + str(len(self.definitions))
            self.definitions.append(
                f'<clipPath id="{clip_id}"><rect x="{r.x:g}" y="{r.y:g}" width="{r.w:g}" height="{r.h:g}"/></clipPath>'
            )
            text_clip = clip_id
        anchor = "start" if fraction == 0 else "end" if fraction == 1 else "middle"
        if not verified_label and not area and enum(p, "TextPolicy") == 0:
            length = max(1, font.getlength(text))
            height *= min(1, r.w / length) if r.w > 0 else 1
        x, y = r.x + r.w * fraction, r.y + (r.h - height) * vertical + height * 0.86
        content = escape(text)
        if area:
            lines, line_height = wrapped_lines(font, text, height, r.w, self.o["language"] == "ZH")
            y = r.y + (r.h - len(lines) * line_height) * vertical + font.getmetrics()[0] * height / max(1, font.size)
            content = "".join(f'<tspan x="{x:g}" y="{y + i * line_height:g}">{escape(line)}</tspan>' for i, line in enumerate(lines))
        text_color = color(
            value(style, "PrimaryColor", value(style, "Color", [1, 1, 1, 1]))
        )
        mode = value(style, "ColorMode", {})
        gradient = mode.get("enum", "") if isinstance(mode, dict) else ""
        if gradient.startswith("Gradient"):
            coords = {
                "GradientLeftRight": ("0%", "0%", "100%", "0%"),
                "GradientRightLeft": ("100%", "0%", "0%", "0%"),
                "GradientTopBottom": ("0%", "0%", "0%", "100%"),
                "GradientBottomTop": ("0%", "100%", "0%", "0%"),
            }
            x1, y1, x2, y2 = coords.get(gradient, ("0%", "0%", "100%", "0%"))
            name = "textGradient" + str(len(self.definitions))
            self.definitions.append(
                f'<linearGradient id="{name}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"><stop stop-color="{text_color}"/><stop offset="1" stop-color="{color(value(style, "SecondaryColor"))}"/></linearGradient>'
            )
            text_color = f"url(#{name})"
        attrs = f'x="{x:g}" y="{y:g}" font-size="{height:g}" font-family="{family}" text-anchor="{anchor}"'
        outline = ""
        effect = enum(style, "Style")
        if effect == 2:
            outline = f' stroke="{color(value(style, "OutlineColor"))}" stroke-width="{number(style, "OutlineThickness", 1):g}" paint-order="stroke fill"'
        shadow = ""
        if effect == 1:
            d = number(style, "ShadowThickness", 1)
            shadow = f'<text {attrs} transform="translate({d:g} {d:g})" fill="{color(value(style, "ShadowColor"), "#000000")}">{content}</text>'
        markup = shadow + f'<text {attrs} fill="{text_color}"{outline}>{content}</text>'
        if overflowing:
            offsets = initial_offsets(enum(p, "TextPolicy"), reference_width, r.w, reference_height, self.o["rtl"])
            markup = "".join(f'<g transform="translate({offset:g} 0)">{markup}</g>' for offset in offsets)
        return f'<g clip-path="url(#{text_clip})">{markup}</g>' if text_clip else markup

    def widget(self, item):
        node, r = item.node, item.rect
        p, kind = properties(node), node["type"]
        output = []
        if self.o["debugFill"]:
            output.append(
                f'<rect x="{r.x:g}" y="{r.y:g}" width="{r.w:g}" height="{r.h:g}" fill="#5795c4" fill-opacity=".08"/>'
            )
        output.append(paint(item, self))
        if self.o["text"] and kind in (
            "Label",
            "TextArea",
            "Button",
            "CompoundButton",
            "ThreeCellButton",
            "TextStyle",
        ):
            output.append(self.text(item))
        if self.o["margins"] and "Margins" in p:
            inner = r.inset(factor_margins(p, (r.w, r.h)) if kind == "MarginContainer" else margins(p))
            output.append(
                f'<rect x="{inner.x:g}" y="{inner.y:g}" width="{inner.w:g}" height="{inner.h:g}" fill="none" stroke="#e0ab54" stroke-dasharray="3 3"/>'
            )
        if self.o["bounds"]:
            output.append(
                f'<rect x="{r.x:g}" y="{r.y:g}" width="{r.w:g}" height="{r.h:g}" fill="none" stroke="#78abc9" stroke-width=".7" vector-effect="non-scaling-stroke"/>'
            )
        label = node["name"] if self.o["names"] else ""
        if self.o["sizes"]:
            label += f" {r.w:.0f}×{r.h:.0f}"
        if label:
            output.append(
                f'<text x="{r.x + 3:g}" y="{r.y + 12:g}" font-size="11" fill="#b6dbef">{escape(label)}</text>'
            )
        return "".join(output)

    def build(self):
        screen = self.o["screen"]
        if type(screen) is not int or not 0 <= screen < len(self.document["screens"]):
            raise ValueError("Invalid screen index")
        root = self.document["screens"][screen]
        path = f"/screens/{screen}"
        w, h = self.o["width"], self.o["height"]
        layout = Layout(self.o, self.minimum_content, self.warnings)
        layout.solve(root, path, Rect(0, 0, w, h), Rect(0, 0, w, h))
        selected = self.o["selected"]
        if selected and not any(i.path == selected for i in layout.items):
            self.warnings.add("Выбранный объект отсутствует в текущем экране")
            selected = ""
        body, geometry = [], []
        for i, item in enumerate(layout.items):
            rect = item.rect
            geometry.append(
                dict(
                    path=item.path,
                    name=item.node["name"],
                    type=item.node["type"],
                    x=rect.x,
                    y=rect.y,
                    width=rect.w,
                    height=rect.h,
                    visible=item.visible,
                )
            )
            if not item.visible and not self.o["showHidden"]:
                continue
            if (
                selected
                and self.o["selectionOnly"]
                and item.path != selected
                and not item.path.startswith(selected + "/")
            ):
                continue
            clip = ""
            if item.clip:
                c = item.clip
                self.definitions.append(
                    f'<clipPath id="c{i}"><rect x="{c.x:g}" y="{c.y:g}" width="{c.w:g}" height="{c.h:g}"/></clipPath>'
                )
                clip = f' clip-path="url(#c{i})"'
            opacity = self.o["opacity"] * (1 if item.visible else 0.25)
            body.append(
                f'<g data-path={quoteattr(item.path)} opacity="{opacity:g}"{clip}><title>{escape(item.node["name"])}</title>'
                + self.widget(item)
                + "</g>"
            )
        # Resource documents have no widget layout. Show their actual selected resource.
        if root["type"] == "Sprite":
            body = []
            try:
                chosen = next((i for i in layout.items if i.path == selected), None)
                if chosen and chosen.node["type"] in ("Movie", "Module"):
                    body.append(
                        self.sprites.draw(
                            f"/{self.document['name']}/{root['name']}/{chosen.node['name']}",
                            Rect(0, 0, w, h),
                        )
                    )
                else:
                    uri = self.resources.png(root, self.o["alpha"])
                    body.append(
                        f'<image href={quoteattr(uri)} width="{w:g}" height="{h:g}" preserveAspectRatio="xMidYMid meet"/>'
                    )
            except (ValueError, OSError, ImportError) as e:
                self.warnings.add(str(e))
        background = (
            f'<rect width="100%" height="100%" fill={quoteattr(self.o["background"])}/>'
        )
        if self.o["checkerboard"]:
            self.definitions.append(
                '<pattern id="checks" width="16" height="16" patternUnits="userSpaceOnUse"><rect width="8" height="8" fill="#ffffff" fill-opacity=".04"/><rect x="8" y="8" width="8" height="8" fill="#ffffff" fill-opacity=".04"/></pattern>'
            )
            background += '<rect width="100%" height="100%" fill="url(#checks)"/>'
        if self.o["grid"]:
            grid = self.o["gridSize"]
            self.definitions.append(
                f'<pattern id="grid" width="{grid:g}" height="{grid:g}" patternUnits="userSpaceOnUse"><path d="M {grid:g} 0 H 0 V {grid:g}" fill="none" stroke="#8090a0" stroke-opacity=".3"/></pattern>'
            )
            body.append(
                '<rect width="100%" height="100%" fill="url(#grid)" pointer-events="none"/>'
            )
        smooth = "auto" if self.o["smooth"] else "pixelated"
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:g} {h:g}" width="{w:g}" height="{h:g}" style="image-rendering:{smooth}"><defs>'
            + "".join(self.definitions + self.sprites.definitions)
            + "</defs>"
            + background
            + "".join(body)
            + "</svg>"
        )
        if len(svg) > 32 * 1024 * 1024:
            raise ValueError("Preview SVG exceeds size limit")
        return dict(
            svg=svg,
            geometry=geometry,
            warnings=sorted(self.warnings),
            errors=self.resources.errors,
            width=w,
            height=h,
        )


def render(document, options=None, resources=None, source="", cache=None):
    return Scene(document, options, resources, source, cache).build()
