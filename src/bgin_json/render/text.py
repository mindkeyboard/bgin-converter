"""Text metrics and initial scroller placement, independent of SVG generation."""

import re


def advance(font, text, height):
    """Keep fractional SVG style scale separate from Pillow's integer font size."""
    return font.getlength(text) * height / max(1, font.size)


def initial_offsets(policy, width, available, height, rtl):
    """Scroller::Reset state; ScrollWrap repeats after width plus twice cached height."""
    if width <= available:
        return (0,)
    overflow = width - available
    if policy == 2:
        repeat = width + 2 * height
        first = -(repeat + overflow) if rtl else 0
        return first, first + repeat
    return (-overflow if rtl else 0,)


def wrapped_lines(font, text, height, width, any_char=False):
    """Approximate Texter word wrapping; unbreakable words may exceed the clip."""
    lines = []
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        tokens = (
            list(paragraph) if any_char else re.findall(r"\S+|[^\S\r\n]+", paragraph)
        )
        line = ""
        for token in tokens:
            if (
                width > 0
                and line
                and not token.isspace()
                and advance(font, line + token, height) > width
            ):
                lines.append(line.rstrip())
                line = ""
            line += token
        lines.append(line.rstrip())
    ascent, descent = font.getmetrics()
    line_height = (ascent + descent) * height / max(1, font.size)
    return lines, line_height
