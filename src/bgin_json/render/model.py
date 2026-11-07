"""Shared numeric model. JSON properties remain untouched by preview operations."""

import math
from dataclasses import dataclass

from ..vocabulary import ENUMS


def properties(node):
    raw = node.get("properties", {})
    if isinstance(raw, list):
        return {k: v for item in raw for k, v in item.items()}
    return raw


def value(props, name, default=None):
    result = props.get(name, default)
    if isinstance(result, dict):
        for kind in ("number", "vector", "string", "path"):
            if kind in result:
                return result[kind]
    return result


def number(props, name, default=0):
    result = value(props, name, default)
    return (
        float(result)
        if isinstance(result, (int, float)) and math.isfinite(result)
        else float(default)
    )


def vector(props, name, default=(0, 0)):
    result = value(props, name, default)
    if not isinstance(result, (list, tuple)) or len(result) != len(default):
        return tuple(default)
    return tuple(
        float(x) if isinstance(x, (int, float)) and math.isfinite(x) else default[i]
        for i, x in enumerate(result)
    )


def enum(props, name, default=0):
    raw = value(props, name)
    if isinstance(raw, dict) and "enum" in raw:
        return raw.get("value", ENUMS.get(name, {}).get(raw["enum"], (default,))[0])
    return int(raw) if isinstance(raw, (int, float)) else default


def margins(props, name="Margins", factor=1):
    # BGIN order is left, right, top, bottom. LoadContainerParam reorders the runtime vec4.
    left, right, top, bottom = vector(props, name, (0, 0, 0, 0))
    return top * factor, bottom * factor, left * factor, right * factor


def factor_margins(props, size):
    """Apply the loader and ComputeMarginsFromFactors rules to a full widget size."""
    top, bottom, left, right = (
        max(0, part) for part in margins(props, "MarginFactors", 0.01)
    )
    horizontal, vertical = max(1, left + right), max(1, top + bottom)
    width, height = size
    return (
        height * top / vertical,
        height * bottom / vertical,
        width * left / horizontal,
        width * right / horizontal,
    )


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    def inset(self, margins):
        top, bottom, left, right = margins
        return Rect(
            self.x + left,
            self.y + top,
            max(0, self.w - left - right),
            max(0, self.h - top - bottom),
        )


@dataclass
class Item:
    node: dict
    path: str
    rect: Rect
    clip: Rect | None
    visible: bool
    enabled: bool
    layer: int


def intersect(a, b):
    if a is None:
        return b
    x, y = max(a.x, b.x), max(a.y, b.y)
    return Rect(
        x,
        y,
        max(0, min(a.x + a.w, b.x + b.w) - x),
        max(0, min(a.y + a.h, b.y + b.h) - y),
    )
