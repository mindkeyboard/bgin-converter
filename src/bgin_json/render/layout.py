"""Measure first, then arrange the complete tree before selecting draw output.

HV weights, margin order and spacing follow WidgetContainer::RefreshLayoutHV.
Preview-only controls model runtime page/scroll state without altering the file.
"""

import math

from .model import (
    Item,
    Rect,
    enum,
    factor_margins,
    intersect,
    margins,
    number,
    properties,
    vector,
)


class Layout:
    def __init__(self, options, minimum_content, warnings):
        self.options, self.minimum_content, self.warnings = options, minimum_content, warnings
        self.measured, self.items = {}, []
        self.assigned_sizes, self.margin_feedback = {}, {}
        self.fixed_layout_sizes = {}
        self.count = 0

    @staticmethod
    def size_changed(before, after):
        # Preview convergence tolerance; the engine also limits dirty-layout work.
        return any(abs(a - b) > max(1, abs(a), abs(b)) * 0.001 for a, b in zip(before, after))

    def solve(self, root, path, rect, clip):
        """Bound feedback from size-dependent margins without claiming the engine dirty loop."""
        for _ in range(11):
            self.count = 0
            self.measure(root, path)
            self.items = []
            self.margin_feedback = {}
            self.arrange(root, path, rect, clip)
            if not any(
                self.size_changed(self.measured[child_path], required)
                for child_path, required in self.margin_feedback.items()
            ):
                return
        self.warnings.add(
            "Layout: size-dependent minimum did not converge within 11 preview passes; "
            "the engine's nested dirty-layout scheduling is not reproduced"
        )

    def spacing(self, p, size, axis):
        n, policy = number(p, "Spacing"), enum(p, "SpacingPolicy")
        if policy == 1:
            return size[axis] * n / 100
        # Ghidra 0x011CA878 uses screen width for 2, screen height for 3.
        if policy in (2, 3):
            return self.options["width" if policy == 2 else "height"] * n / 100
        return n * self.options["pixelsPerMm"]

    def measure(self, node, path, depth=0):
        if depth > 128:
            raise ValueError("Preview tree is too deep")
        self.count += 1
        if self.count > 50000:
            raise ValueError("Preview exceeds 50000 nodes")
        p = properties(node)
        children = node.get("children", [])
        sizes = [
            self.measure(c, f"{path}/children/{i}", depth + 1)
            for i, c in enumerate(children)
        ]
        kind = node["type"]
        natural = self.minimum_content(node, self.assigned_sizes.get(path))
        if children:
            gap = self.spacing(
                p,
                (self.options["width"], self.options["height"]),
                int(kind == "VerticalContainer"),
            )
            if kind in ("HorizontalContainer", "VerticalContainer", "ScrollContainer"):
                axis = int(
                    kind == "VerticalContainer"
                    or kind == "ScrollContainer"
                    and enum(p, "Direction") == 1
                )
                natural = (
                    (
                        sum(s[0] for s in sizes) + gap * max(0, len(sizes) - 1),
                        max(s[1] for s in sizes),
                    )
                    if axis == 0
                    else (
                        max(s[0] for s in sizes),
                        sum(s[1] for s in sizes) + gap * max(0, len(sizes) - 1),
                    )
                )
            else:
                natural = (max(s[0] for s in sizes), max(s[1] for s in sizes))
            margin = (
                factor_margins(p, self.assigned_sizes.get(path, (0, 0)))
                if kind == "MarginContainer"
                else (0, 0, 0, 0) if kind == "FixedSizeContainer" else margins(p)
            )
            natural = (
                natural[0] + margin[2] + margin[3],
                natural[1] + margin[0] + margin[1],
            )
            if kind == "MarginContainer":
                maximum = vector(p, "MaxSize", (5000, 5000))
                natural = tuple(min(natural[i], maximum[i]) for i in (0, 1))
        elif kind == "MarginContainer":
            top, bottom, left, right = factor_margins(p, self.assigned_sizes.get(path, (0, 0)))
            maximum = vector(p, "MaxSize", (5000, 5000))
            natural = (min(left + right, maximum[0]), min(top + bottom, maximum[1]))
        if kind.endswith("Spring"):
            natural = (0, 0)
        if kind == "FixedSizeContainer":
            # RefreshLayout keeps its uncapped local requirement for child placement,
            # while SetLayoutSize caps the stored minimum by this container's MaxSize.
            required = self.fixed_size(p, natural, minimum=True)
            self.fixed_layout_sizes[path] = required
            maximum = vector(p, "MaxSize", (5000, 5000))
            natural = tuple(min(required[i], maximum[i]) for i in (0, 1))
        minimum = vector(p, "MinSize")
        # GetMinSize is independent of GetMaxSize; SetSize applies the upper bound later.
        result = tuple(max(0, minimum[i], natural[i]) for i in (0, 1))
        self.measured[path] = result
        return result

    def fixed_size(self, p, size, *, minimum=False):
        """BGIN factors are screen percentages; the aspect factor multiplies the other axis."""
        enabled = (
            number(p, "EnableFixedWidth") > 0.5,
            number(p, "EnableFixedHeight") > 0.5,
        )
        result = list(size)
        for axis, (screen, field) in enumerate(
            (("width", "FixedWidthFactor"), ("height", "FixedHeightFactor"))
        ):
            if enabled[axis]:
                fixed = self.options[screen] * number(p, field, 10) / 100
                result[axis] = max(result[axis], fixed) if minimum else fixed
        if number(p, "EnableAspectRatio") > 0.5 and enabled[0] != enabled[1]:
            fixed_axis = 0 if enabled[0] else 1
            result[1 - fixed_axis] = result[fixed_axis] * number(p, "AspectRatio", 1)
        return tuple(result)

    def clamp(self, node, path, size):
        p = properties(node)
        maximum = vector(p, "MaxSize", (5000, 5000))
        return tuple(
            min(maximum[i], max(0, self.measured[path][i], size[i]))
            for i in (0, 1)
        )

    def arrange(self, node, path, rect, clip=None, visible=True, enabled=True, depth=0):
        p, kind = properties(node), node["type"]
        size = self.clamp(node, path, (rect.w, rect.h))
        rect = Rect(rect.x, rect.y, *size)
        self.assigned_sizes[path] = size
        visible = visible and number(p, "Visible", 1) > 0.5
        enabled = enabled and number(p, "Enabled", 1) > 0.5
        self.items.append(
            Item(
                node,
                path,
                rect,
                clip,
                visible,
                enabled,
                max(0, int(number(p, "RenderLayer"))),
            )
        )
        child_clip = (
            intersect(clip, rect)
            if self.options["clipping"] and number(p, "ClipRender") > 0.5
            else clip
        )
        children = node.get("children", [])
        if kind == "TextArea" or kind in ("Label", "Button") and enum(p, "VerticalTextPolicy") == 0:
            content = self.minimum_content(node, size)
            minimum = vector(p, "MinSize")
            self.margin_feedback[path] = tuple(max(0, minimum[i], content[i]) for i in (0, 1))
        if not children and kind != "MarginContainer":
            return
        inner = rect.inset(margins(p))
        if kind == "MarginContainer":
            # Its virtual SetMargins is a no-op; factors use the full current size.
            top, bottom, left, right = factor_margins(p, size)
            required = (
                max((self.measured[f"{path}/children/{i}"][0] for i in range(len(children))), default=0) + left + right,
                max((self.measured[f"{path}/children/{i}"][1] for i in range(len(children))), default=0) + top + bottom,
            )
            minimum, maximum = vector(p, "MinSize"), vector(p, "MaxSize", (5000, 5000))
            self.margin_feedback[path] = tuple(
                max(0, minimum[i], min(required[i], maximum[i])) for i in (0, 1)
            )
            inner = Rect(
                rect.x + left,
                rect.y + top,
                max(0, max(rect.w, required[0]) - left - right),
                max(0, max(rect.h, required[1]) - top - bottom),
            )
        assigned = [inner for _ in children]
        if kind == "FixedSizeContainer":
            required = self.fixed_layout_sizes[path]
            available = (max(rect.w, required[0]), max(rect.h, required[1]))
            width, height = self.fixed_size(p, available)
            assigned = [Rect(
                rect.x + (rect.w - width) / 2,
                rect.y + (rect.h - height) / 2,
                width,
                height,
            )] * len(children)
        elif kind in ("HorizontalContainer", "VerticalContainer", "ScrollContainer"):
            axis = int(
                kind == "VerticalContainer"
                or kind == "ScrollContainer"
                and enum(p, "Direction") == 1
            )
            assigned = self.linear(node, path, inner, axis)
            if kind == "ScrollContainer":
                assigned = [
                    Rect(
                        r.x - self.options["scrollX"],
                        r.y - self.options["scrollY"],
                        r.w,
                        r.h,
                    )
                    for r in assigned
                ]
        elif kind == "PageContainer":
            axis = enum(p, "Direction")
            page = self.options["page"]
            assigned = [
                Rect(
                    inner.x + (i - page) * inner.w * (axis == 0),
                    inner.y + (i - page) * inner.h * (axis == 1),
                    inner.w,
                    inner.h,
                )
                for i in range(len(children))
            ]
        elif kind == "GridContainer":
            columns = max(1, int(number(p, "ColumnCount", 1)))
            if enum(p, "Direction") == 1:
                columns = max(1, math.ceil(len(children) / columns))
            gap = self.spacing(p, (inner.w, inner.h), 0)
            rows = max(1, math.ceil(len(children) / columns))
            w, h = (
                max(0, (inner.w - gap * (columns - 1)) / columns),
                max(0, (inner.h - gap * (rows - 1)) / rows),
            )
            ratio = number(p, "ItemAspectRatio", 0)
            if ratio > 0:
                h = w * ratio if enum(p, "ItemAspectRatioMode", 1) == 1 else w / ratio
            assigned = [
                Rect(
                    inner.x + i % columns * (w + gap),
                    inner.y + i // columns * (h + gap),
                    w,
                    h,
                )
                for i in range(len(children))
            ]
        elif kind == "ThreeCellContainer":
            left, right = (
                inner.h * number(p, "LeftAspectRatio", 1),
                inner.h * number(p, "RightAspectRatio", 1),
            )
            assigned = [
                Rect(inner.x, inner.y, left, inner.h),
                Rect(inner.x + left, inner.y, max(0, inner.w - left - right), inner.h),
                Rect(inner.x + inner.w - right, inner.y, right, inner.h),
            ]
            assigned += [inner] * max(0, len(children) - 3)
        elif kind == "AspectRatioContainer":
            ratio = number(p, "ItemAspectRatio", 1)
            if ratio > 0:
                ratio = 1 / ratio if enum(p, "ItemAspectRatioMode", 1) == 1 else ratio
                w, h = inner.w, inner.w / ratio
                if h > inner.h:
                    w, h = inner.h * ratio, inner.h
                assigned = [
                    Rect(
                        # The loader exposes no axis alignment; both constructor defaults center.
                        inner.x + (rect.w - w) * 0.5,
                        inner.y + (rect.h - h) * 0.5,
                        w,
                        h,
                    )
                ] * len(children)
        elif kind == "CoverFlowContainer":
            self.warnings.add(
                "CoverFlowContainer: статический предпросмотр; перспективное преобразование движка не воспроизведено"
            )
            w = (
                inner.w
                * number(p, "ItemMainScale", 1)
                / max(1, number(p, "VisibleItemsCount", 3))
            )
            h = min(inner.h, w * number(p, "ItemAspectRatio", 1))
            gap = w * number(p, "SpacingFactor", 1)
            assigned = [
                Rect(
                    inner.x + inner.w / 2 - w / 2 + (i - self.options["page"]) * gap,
                    inner.y + (inner.h - h) / 2,
                    w,
                    h,
                )
                for i in range(len(children))
            ]
        # Sibling layout precedes drawing order and selection filtering.
        for i in sorted(
            range(len(children)),
            key=lambda i: number(properties(children[i]), "RenderLayer"),
        ):
            child, child_path = children[i], f"{path}/children/{i}"
            r = assigned[i]
            transform = child.get("transform", [0, 0, 0, 1, 1])
            # Ordinary loaders apply position; their remaining editor fields are not proven transforms.
            if kind not in (
                "HorizontalContainer",
                "VerticalContainer",
                "ScrollContainer",
                "GridContainer",
                "PageContainer",
                "AspectRatioContainer",
                "FixedSizeContainer",
                "MarginContainer",
            ):
                r = Rect(r.x + transform[0], r.y + transform[1], r.w, r.h)
            self.arrange(child, child_path, r, child_clip, visible, enabled, depth + 1)

    def linear(self, node, path, rect, axis):
        children, p = node["children"], properties(node)
        gap = self.spacing(p, (rect.w, rect.h), axis)
        available = max(0, (rect.w, rect.h)[axis] - max(0, len(children) - 1) * gap)
        minima = [
            self.measured[f"{path}/children/{i}"][axis] for i in range(len(children))
        ]
        weights = [max(0, number(properties(c), "StretchFactor")) for c in children]
        total = sum(weights)
        policy = enum(p, "EmptySpaceFillPolicy")
        sizes = list(minima)
        if policy == 0 and total > 0:
            sizes = [
                self.clamp(
                    c,
                    f"{path}/children/{i}",
                    (available * weights[i] / total, rect.h)
                    if axis == 0
                    else (rect.w, available * weights[i] / total),
                )[axis]
                for i, c in enumerate(children)
            ]
            # Redistribute after clamping; bounded work replaces the engine's convergence loop.
            for _ in range(11):
                remainder = available - sum(sizes)
                if abs(remainder) < 0.1:
                    break
                new = [
                    self.clamp(
                        c,
                        f"{path}/children/{i}",
                        (sizes[i] + remainder * weights[i] / total, rect.h)
                        if axis == 0
                        else (rect.w, sizes[i] + remainder * weights[i] / total),
                    )[axis]
                    for i, c in enumerate(children)
                ]
                if all(abs(a - b) < 1e-6 for a, b in zip(new, sizes)):
                    break
                sizes = new
        offset = max(0, available - sum(sizes)) * (
            0.5 if policy == 2 else 1 if policy == 3 else 0
        )
        rtl = (
            axis == 0
            and self.options["rtl"]
            and number(p, "EnableRightToLeftLayout") > 0.5
        )
        result = []
        for size in sizes:
            pos = rect.w - offset - size if rtl else offset
            result.append(
                Rect(
                    rect.x + pos if axis == 0 else rect.x,
                    rect.y + pos if axis else rect.y,
                    size if axis == 0 else rect.w,
                    rect.h if axis == 0 else size,
                )
            )
            offset += size + gap
        return result
