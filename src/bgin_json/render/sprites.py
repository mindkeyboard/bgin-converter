"""Sprite modules, nested movies, interpolation and nine-slice drawing."""

import math
from xml.sax.saxutils import quoteattr

from .model import enum, number, properties, value, vector


def easing(t, mode):
    if mode == 0:
        return 0
    if mode == 2:
        return t * t * (3 - 2 * t)
    if mode == 3:
        return t * t * t * (t * (6 * t - 15) + 10)
    if mode >= 4 and mode <= 12:
        power = (2, 4, 8)[(mode - 4) // 3]
        return (
            t**power
            if (mode - 4) % 3 == 0
            else 1 - (1 - t) ** power
            if (mode - 4) % 3 == 1
            else ((2 * t) ** power / 2 if t < 0.5 else 1 - (-2 * t + 2) ** power / 2)
        )
    return t


def channel(track, key, frame, default, interpolate=True):
    entries = [f for f in track.get("keyframes", []) if key in f]
    entries.sort(key=lambda f: f["frame"])
    if not entries:
        return default
    before = entries[0]
    for after in entries:
        if after["frame"] > frame:
            if after is before or not interpolate:
                return before[key]["value"]
            t = easing(
                max(
                    0,
                    min(
                        1,
                        (frame - before["frame"])
                        / max(1, after["frame"] - before["frame"]),
                    ),
                ),
                before[key].get("interpolation", 0),
            )
            a, b = before[key]["value"], after[key]["value"]
            return (
                [x + (y - x) * t for x, y in zip(a, b)]
                if isinstance(a, list)
                else a + (b - a) * t
            )
        before = after
    return before[key]["value"]


def frame_color(track, frame, interpolate=True):
    entries = [
        f
        for f in track.get("keyframes", [])
        if "Color" in properties({"properties": f.get("colors", {})})
    ]
    entries.sort(key=lambda f: f["frame"])
    if not entries:
        return (1, 1, 1, 1)
    before = entries[0]

    def read(entry):
        return vector(
            properties({"properties": entry["colors"]}), "Color", (1, 1, 1, 1)
        )

    for after in entries:
        if after["frame"] > frame:
            if after is before or not interpolate:
                return read(before)
            t = max(
                0,
                min(
                    1,
                    (frame - before["frame"])
                    / max(1, after["frame"] - before["frame"]),
                ),
            )
            return tuple(a + (b - a) * t for a, b in zip(read(before), read(after)))
        before = after
    return read(before)


class Sprites:
    def __init__(self, resources, options, warnings):
        self.resources, self.options, self.warnings = resources, options, warnings
        self.crops = {}
        self.serial = 0
        self.definitions = []

    def transform(self, track):
        frame = self.options["frame"]
        if "transform" in track:
            self.warnings.add(
                "MovieModule.transform: загрузчик читает эти значения без применения; используются ключевые кадры"
            )
        return (
            channel(track, "position", frame, [0, 0], self.options["interpolate"]),
            channel(track, "rotation", frame, 0, self.options["interpolate"]),
            channel(track, "scale", frame, [1, 1], self.options["interpolate"]),
        )

    def bounds(self, root, node, depth=0):
        if depth > 20:
            raise ValueError("Sprite nesting exceeds 20 levels")
        p = properties(node)
        if node["type"] == "Module":
            w, h = vector(p, "Size", (1, 1))
            return (-w / 2, -h / 2, max(1, w), max(1, h))
        for child in node.get("children", []):
            cp = properties(child)
            if child["type"] == "SpriteMovie" and number(cp, "EnableRectangle") > 0.5:
                x, y, right, bottom = vector(cp, "Rectangle", (0, 0, 1, 1))
                return x, y, max(1, right - x), max(1, bottom - y)
        boxes = []
        for track in node.get("tracks", []):
            ref = value(properties(track), "Module", "")
            if ref:
                try:
                    r, n = self.resources.lookup(ref)
                    x, y, w, h = self.bounds(r, n, depth + 1)
                    pos, angle, scale = self.transform(track)
                    pivot = vector(properties(track), "Pivot")
                    co, si = math.cos(angle), math.sin(angle)
                    corners = [
                        (
                            pos[0]
                            + co * (a - pivot[0]) * scale[0]
                            - si * (b - pivot[1]) * scale[1],
                            pos[1]
                            + si * (a - pivot[0]) * scale[0]
                            + co * (b - pivot[1]) * scale[1],
                        )
                        for a, b in ((x, y), (x + w, y), (x, y + h), (x + w, y + h))
                    ]
                    left, top = min(c[0] for c in corners), min(c[1] for c in corners)
                    boxes.append(
                        (
                            left,
                            top,
                            max(c[0] for c in corners) - left,
                            max(c[1] for c in corners) - top,
                        )
                    )
                except KeyError:
                    pass
        if not boxes:
            return (-0.5, -0.5, 1, 1)
        x, y = min(b[0] for b in boxes), min(b[1] for b in boxes)
        return (
            x,
            y,
            max(b[0] + b[2] for b in boxes) - x,
            max(b[1] + b[3] for b in boxes) - y,
        )

    def draw(self, reference, rect, keep=True, fitting=0, alignment=0):
        try:
            root, node = self.resources.lookup(reference)
            x, y, w, h = self.bounds(root, node)
            sx, sy = rect.w / w, rect.h / h
            if keep:
                sx = sy = min(sx, sy) if fitting == 0 else max(sx, sy)
            fraction = 0.5 if alignment == 0 else 0 if alignment == 1 else 1
            dx, dy = (
                rect.x + (rect.w - w * sx) * fraction - x * sx,
                rect.y + (rect.h - h * sy) * fraction - y * sy,
            )
            output = (
                f'<g transform="translate({dx:g} {dy:g}) scale({sx:g} {sy:g})">'
                + self.node(root, node, 0, (sx, sy))
                + "</g>"
            )
            if keep and fitting == 1:
                # MovieWidget::Render (VA 0x011b3794) clips Fill to the widget rectangle.
                # This is intrinsic to Fill, independent of a container's ClipRender flag.
                self.serial += 1
                name = "movieFill" + str(self.serial)
                self.definitions.append(
                    f'<clipPath id="{name}" clipPathUnits="userSpaceOnUse"><rect x="{rect.x:g}" y="{rect.y:g}" width="{rect.w:g}" height="{rect.h:g}"/></clipPath>'
                )
                output = f'<g clip-path="url(#{name})">{output}</g>'
            return output
        except (KeyError, OSError, ValueError, ImportError) as e:
            self.warnings.add(f"Спрайт {reference}: {e}")
            self.resources.errors.append(
                {"path": "/", "message": f"Спрайт {reference}: {e}"}
            )
            return f'<rect x="{rect.x:g}" y="{rect.y:g}" width="{rect.w:g}" height="{rect.h:g}" fill="#704054" fill-opacity=".25" stroke="#d987a2"/><text x="{rect.x + 4:g}" y="{rect.y + 15:g}" font-size="12" fill="#d987a2">Missing sprite</text>'

    def image(self, uri, p, size, world_scale):
        w, h = size
        mode = enum(p, "NinePatchMode")
        left, right, top, bottom = vector(p, "NinePatchDef", (0, 0, 0, 0))
        if mode == 2:
            left, right = vector(p, "NinePatchDefFH")
            top = bottom = 0
        left, right, top, bottom = (
            min(w, max(0, left)),
            min(w, max(0, right)),
            min(h, max(0, top)),
            min(h, max(0, bottom)),
        )
        sx, sy = max(1e-6, abs(world_scale[0])), max(1e-6, abs(world_scale[1]))
        if mode and any((left, right, top, bottom)):
            dl, dr, dt, db = left / sx, right / sx, top / sy, bottom / sy
            if mode == 2:
                dl, dr, dt, db = left * sy / sx, right * sy / sx, 0, 0
                top = bottom = 0
            elif mode != 1:
                self.warnings.add("Неизвестный NinePatchMode; показан Classic")
            if left + right > w or top + bottom > h:
                self.warnings.add(
                    "NinePatchDef: пересекающиеся исходные границы; проверьте параметры модуля"
                )
            if dl + dr > w:
                factor = w / max(1, dl + dr)
                dl *= factor
                dr *= factor
            if dt + db > h:
                factor = h / max(1, dt + db)
                dt *= factor
                db *= factor
            srcx, srcy = (0, left, w - right, w), (0, top, h - bottom, h)
            dstx, dsty = (
                (-w / 2, -w / 2 + dl, w / 2 - dr, w / 2),
                (-h / 2, -h / 2 + dt, h / 2 - db, h / 2),
            )
            result = []
            for row in range(3):
                for col in range(3):
                    sw, sh = srcx[col + 1] - srcx[col], srcy[row + 1] - srcy[row]
                    dw, dh = dstx[col + 1] - dstx[col], dsty[row + 1] - dsty[row]
                    if min(sw, sh, dw, dh) > 0:
                        result.append(
                            f'<svg x="{dstx[col]:g}" y="{dsty[row]:g}" width="{dw:g}" height="{dh:g}" viewBox="{srcx[col]:g} {srcy[row]:g} {sw:g} {sh:g}" preserveAspectRatio="none" overflow="hidden"><use href={quoteattr(uri)}/></svg>'
                        )
            if enum(p, "HStretch") or enum(p, "VStretch"):
                self.warnings.add(
                    "Tile внутри NinePatch: пока применяется растяжение областей"
                )
            return "".join(result)
        if enum(p, "HStretch") or enum(p, "VStretch"):
            self.serial += 1
            name = "tile" + str(self.serial)
            tw = w / sx if enum(p, "HStretch") else w
            th = h / sy if enum(p, "VStretch") else h
            return f'<defs><pattern id="{name}" patternUnits="userSpaceOnUse" x="{-w / 2:g}" y="{-h / 2:g}" width="{tw:g}" height="{th:g}"><use href={quoteattr(uri)} transform="scale({tw / w:g} {th / h:g})"/></pattern></defs><rect x="{-w / 2:g}" y="{-h / 2:g}" width="{w:g}" height="{h:g}" fill="url(#{name})"/>'
        return f'<use href={quoteattr(uri)} x="{-w / 2:g}" y="{-h / 2:g}"/>'

    def node(self, root, node, depth, world_scale=(1, 1)):
        if depth > 20:
            raise ValueError("Cyclic or too deep sprite reference")
        if node["type"] == "Module":
            p = properties(node)
            pos, size = vector(p, "BakePosition"), vector(p, "Size", (1, 1))
            key = (id(root), id(node), self.options["alpha"])
            if key not in self.crops:
                uri = self.resources.png(root, self.options["alpha"], (*pos, *size))
                name = "spriteImage" + str(len(self.crops))
                self.crops[key] = "#" + name
                self.definitions.append(
                    f'<image id="{name}" href={quoteattr(uri)} width="{size[0]:g}" height="{size[1]:g}"/>'
                )
            return self.image(self.crops[key], p, size, world_scale)
        output = []
        for track in node.get("tracks", []):
            p = properties(track)
            ref = value(p, "Module", value(p, "Movie", ""))
            if not ref:
                continue
            try:
                r, n = self.resources.lookup(ref)
            except KeyError:
                self.warnings.add(f"Модуль не найден: {ref}")
                continue
            pos, angle, scale = self.transform(track)
            pivot = vector(p, "Pivot")
            color = frame_color(
                track, self.options["frame"], self.options["interpolate"]
            )
            anchor = enum(p, "PivotArea", 12)
            if anchor not in (0, 12):
                self.warnings.add(
                    "PivotArea: нестандартная привязка требует проверки; показано положение Pivot"
                )
            tint = ""
            if any(c != 1 for c in color[:3]):
                self.serial += 1
                name = "tint" + str(self.serial)
                matrix = " ".join(
                    str(v)
                    for v in (
                        color[0],
                        0,
                        0,
                        0,
                        0,
                        0,
                        color[1],
                        0,
                        0,
                        0,
                        0,
                        0,
                        color[2],
                        0,
                        0,
                        0,
                        0,
                        0,
                        1,
                        0,
                    )
                )
                output.append(
                    f'<defs><filter id="{name}" color-interpolation-filters="sRGB"><feColorMatrix type="matrix" values="{matrix}"/></filter></defs>'
                )
                tint = f' filter="url(#{name})"'
            output.append(
                f'<g opacity="{max(0, min(1, color[3])):g}"{tint} transform="translate({pos[0]:g} {pos[1]:g}) rotate({angle * 180 / math.pi:g}) scale({scale[0]:g} {scale[1]:g}) translate({-pivot[0]:g} {-pivot[1]:g})">'
                + self.node(
                    r,
                    n,
                    depth + 1,
                    (world_scale[0] * scale[0], world_scale[1] * scale[1]),
                )
                + "</g>"
            )
        return "".join(output)
