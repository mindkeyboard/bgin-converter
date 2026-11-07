"""Editable vocabulary and explicit preview coverage, independent of game assets."""

import json
from pathlib import Path

from .engine_params import OBJECT_CLASSES, parameter
from .names import TYPE_NAMES
from .vocabulary import ENUMS, PROPERTY_KINDS

LAYOUT = {
        "MinSize",
        "MaxSize",
        "Size",
        "StretchFactor",
        "Margins",
        "MarginFactors",
        "Spacing",
        "SpacingPolicy",
        "EmptySpaceFillPolicy",
        "EnableRightToLeftLayout",
        "Direction",
        "ColumnCount",
        "ItemAspectRatio",
        "ItemAspectRatioMode",
        "LeftAspectRatio",
        "RightAspectRatio",
        "EnableFixedWidth",
        "EnableFixedHeight",
        "FixedWidthFactor",
        "FixedHeightFactor",
        "Visible",
        "Enabled",
        "RenderLayer",
        "ClipRender",
    }
SPRITES = {
        "Source",
        "BakePosition",
        "Size",
        "Module",
        "Movie",
        "Rectangle",
        "EnableRectangle",
        "Pivot",
        "Color",
        "KeepAspectRatio",
        "Fitting",
        "Alignment",
        "Background",
        "NormalBackground",
        "PressedBackground",
        "DisabledBackground",
        "ToggledBackground",
        "FillBackground",
        "FillBackground0",
        "KnobAspectRatio",
        "KnobBackground",
        "NormalKnob",
        "PressedKnob",
        "NinePatchMode",
        "NinePatchDef",
        "NinePatchDefFH",
        "HStretch",
        "VStretch",
        "LeftBackground",
        "RightBackground",
        "PressedLeftBackground",
        "PressedRightBackground",
        "ToggledLeftBackground",
        "ToggledRightBackground",
        "DisabledLeftBackground",
        "DisabledRightBackground",
    }
TEXT = {
        "Text",
        "TestString",
        "TextStyle",
        "PressedTextStyle",
        "ToggledTextStyle",
        "DisabledTextStyle",
        "FontHeight",
        "FontHeightFactor",
        "HeightFactor",
        "PrimaryColor",
        "SecondaryColor",
        "ColorMode",
        "InvertAlignmentRTL",
        "OutlineColor",
        "OutlineThickness",
        "ShadowColor",
        "ShadowThickness",
        "Style",
        "TextPolicy",
        "VerticalTextPolicy",
    }


def catalog():
    from .engine_catalog import LOADERS
    from .observed import OBSERVED

    kinds = {
        **PROPERTY_KINDS,
        "Toggleable": "number",
        "DisabledMargin": "number",
        "EnabledMargin": "number",
        "EnabledTextStyle": "path",
    }

    def inherited(method, visited=None):
        visited = set() if visited is None else visited
        if method in visited:
            return set()
        visited.add(method)
        data = LOADERS.get(method, {})
        result = set(data.get("names", [])) & kinds.keys()
        for called in data.get("calls", []):
            result |= inherited(called, visited)
        return result

    owners = {t: inherited("Load" + t) for t in TYPE_NAMES.values()}
    owners["Module"] |= inherited("LoadModuleParam")
    owners["MovieModule"] |= inherited("LoadMovieModuleParam")
    owners["SpriteMovie"] |= inherited("LoadMovieSpriteMovie")
    owners["Sprite"] |= inherited("LoadSpriteParam")
    owners["Movie"] |= inherited("LoadSpriteMovie")
    owners["TextStyle"] |= inherited("LoadTextStyleParam")
    entries = {}
    for name, kind in sorted(kinds.items()):
        effect = (
            "layout"
            if name in LAYOUT
            else "sprite"
            if name in SPRITES
            else "text"
            if name in TEXT or name.startswith(("FontName", "FontScaling"))
            else "preserved"
        )
        entries[name] = {
            "kind": kind,
            "choices": list(ENUMS.get(name, {})),
            "objects": OBSERVED.get(name, {}),
            "appliesTo": sorted(t for t, names in owners.items() if name in names),
            "preview": effect,
        }
    schemas = {t: sorted(names) for t, names in owners.items()}
    help_text = json.loads((Path(__file__).parent / "parameter_help.json").read_text(encoding="utf-8"))
    parameters = {
        obj: {
            name: spec
            for name in sorted(names)
            if (spec := parameter(obj, name, kinds[name], LAYOUT, ENUMS, help_text))
        }
        for obj, names in owners.items()
    }

    containers = [
        t
        for t in TYPE_NAMES.values()
        if t.endswith("Container") or t == "CompoundButton"
    ]
    return {
        "types": sorted(TYPE_NAMES.values()),
        "creation": {
            "objects": sorted(set(TYPE_NAMES.values()) - {"Sprite", "Module", "SpriteMovie", "MovieModule", "TextStyle"}),
            "screens": {
                "ui": sorted(containers),
                "templates": sorted([*containers, "TextStyle"]),
                "sprites": ["Sprite"],
            },
        },
        "properties": entries,
        "schemas": schemas,
        "parameters": parameters,
        "documentation": {obj: classes[0] for obj, classes in OBJECT_CLASSES.items()},
        "containers": containers,
    }
