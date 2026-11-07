"""Widget-specific image composition; runtime interaction is supplied by preview state."""

import math

from .model import Rect, enum, number, properties, value


def paint(item, scene):
    p, r, kind = properties(item.node), item.rect, item.node["type"]
    state = "disabled" if not item.enabled else scene.o["state"]
    prefix = dict(normal="", pressed="Pressed", toggled="Toggled", disabled="Disabled")[
        state
    ]
    output = []
    reference = value(
        p,
        prefix + "Background",
        value(p, "Background", value(p, "NormalBackground", "")),
    )
    if kind == "Movie":
        reference = value(p, "Movie", value(p, "Sprite", reference))

    def image(ref, rect, keep=False):
        return (
            scene.sprites.draw(
                ref, rect, keep, enum(p, "Fitting"), enum(p, "Alignment")
            )
            if ref and scene.o["sprites"]
            else ""
        )

    if reference:
        output.append(
            image(
                reference,
                r,
                number(p, "KeepAspectRatio", 1) > 0.5 if kind == "Movie" else False,
            )
        )
    if kind == "ThreeCellButton":
        left = min(r.w, r.h * number(p, "LeftAspectRatio", 1))
        right = min(r.w, r.h * number(p, "RightAspectRatio", 1))
        for side, rect in (
            ("Left", Rect(r.x, r.y, left, r.h)),
            ("Right", Rect(r.x + r.w - right, r.y, right, r.h)),
        ):
            ref = value(
                p, prefix + side + "Background", value(p, side + "Background", "")
            )
            output.append(image(ref, rect))
        if number(p, "LeftOverlap") > 0.5 or number(p, "RightOverlap") > 0.5:
            scene.warnings.add(
                "ThreeCellButton: изображения секций показаны; точное перекрытие текста секциями пока не воспроизведено"
            )
    if kind in (
        "Progress",
        "MultiProgress",
        "Slider",
        "CircularProgress",
        "CircularSlider",
        "Switch",
    ):
        fraction = scene.o["progress"]
        horizontal = enum(p, "Direction") == 0
        fill = value(p, "FillBackground", value(p, "FillBackground0", ""))
        if kind in ("CircularProgress", "CircularSlider"):
            cx, cy, rad = r.x + r.w / 2, r.y + r.h / 2, min(r.w, r.h) / 2
            if fraction >= 1:
                shape = f'<circle cx="{cx:g}" cy="{cy:g}" r="{rad:g}"/>'
            else:
                angle = fraction * math.tau - math.pi / 2
                ex, ey = cx + rad * math.cos(angle), cy + rad * math.sin(angle)
                shape = (
                    f'<path d="M {cx:g} {cy:g} L {cx:g} {cy - rad:g} A {rad:g} {rad:g} 0 {int(fraction > 0.5)} 1 {ex:g} {ey:g} Z"/>'
                    if fraction
                    else ""
                )
            name = "progress" + str(len(scene.definitions))
            scene.definitions.append(f'<clipPath id="{name}">{shape}</clipPath>')
            output.append(
                f'<g clip-path="url(#{name})">'
                + (
                    image(fill, r)
                    or f'<circle cx="{cx:g}" cy="{cy:g}" r="{rad:g}" fill="#6a96bf" fill-opacity=".55"/>'
                )
                + "</g>"
            )
            scene.warnings.add(
                "Круговой индикатор: сектор предпросмотра; точная геометрия заливки движка ещё не воспроизведена"
            )
        else:
            fr = Rect(
                r.x,
                r.y,
                r.w * fraction if horizontal else r.w,
                r.h if horizontal else r.h * fraction,
            )
            output.append(
                image(fill, fr)
                or f'<rect x="{fr.x:g}" y="{fr.y:g}" width="{fr.w:g}" height="{fr.h:g}" fill="#6a96bf" fill-opacity=".55"/>'
            )
        if kind == "MultiProgress":
            scene.warnings.add(
                "MultiProgress: показан первый канал; распределение остальных каналов задаётся кодом игры"
            )
        if kind == "Slider":
            knob = value(
                p,
                "PressedKnob" if state == "pressed" else "NormalKnob",
                value(p, "KnobBackground", ""),
            )
            ratio = max(0.01, number(p, "KnobAspectRatio", 1))
            kw, kh = (r.h * ratio, r.h) if horizontal else (r.w, r.w / ratio)
            kr = (
                Rect(r.x + max(0, r.w - kw) * fraction, r.y, kw, kh)
                if horizontal
                else Rect(r.x, r.y + max(0, r.h - kh) * fraction, kw, kh)
            )
            if knob:
                output.append(image(knob, kr))
        if kind == "Switch":
            scene.warnings.add(
                "Switch: состояние предпросмотра предварительное; подписи и внутреннее устройство переключателя пока не воспроизведены"
            )
    return "".join(output)
