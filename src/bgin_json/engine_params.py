"""Parameter contract of gin::GUILoader for the editor; see development/notes/atlas-parameter-types-ru.md.

Domains come from the Find* functions and inline comparisons of the loader, which
select a value by the hash of its name. Option codes are the BGIN wire numbers.
"""

_SPACING = (("Mm", 0, "millimetres"), ("Factor", 1, "percent of the container"),
            ("ScreenHeightFactor", 2, "percent of screen height"),
            ("ScreenWidthFactor", 3, "percent of screen width"))
_DIRECTION = (("Horizontal", 0), ("Vertical", 1))
_TEXT_ALIGNMENT = (("TopLeft", 0), ("Top", 1), ("TopRight", 2), ("Left", 3), ("Center", 4),
                   ("Right", 5), ("BottomLeft", 6), ("Bottom", 7), ("BottomRight", 8))
_STRETCH = (("Stretch", 0), ("Tile", 1))

# Options are (name, wire code) or (name, wire code, hint).
ENGINE_ENUMS = {
    "Alignment": _TEXT_ALIGNMENT,
    "BarSizePolicy": _SPACING,
    "BarVisibility": (("Hidden", 0), ("AutoHide", 1, "only while scrolling"), ("Always", 2)),
    "ButtonEventPolicy": (("Default", 0), ("Autopress", 1, "press starts on touch")),
    "ColorMode": (("Normal", 0, "one colour"), ("GradientLeftRight", 1), ("GradientRightLeft", 2),
                  ("GradientTopBottom", 3), ("GradientBottomTop", 4)),
    "Direction": _DIRECTION,
    "EmptySpaceFillPolicy": (("UnnamedOption1", 0, "share by StretchFactor"),
                             ("ArrangeTopOrLeft", 1, "minimum sizes at the start"),
                             ("ArrangeCenter", 2, "minimum sizes in the centre"),
                             ("ArrangeBottomOrRight", 3, "minimum sizes at the end")),
    "Fitting": (("Fit", 0, "keep width"), ("Fill", 1, "keep height, crop the rest")),
    "HStretch": _STRETCH,
    "InterpolationMode": (("linear", 0), ("smooth", 1), ("smoother", 2), ("quadratic_i", 3),
                          ("quadratic_o", 4), ("quadratic_io", 5), ("quartic_i", 6), ("quartic_o", 7),
                          ("quartic_io", 8), ("octic_i", 9), ("octic_o", 10), ("octic_io", 11),
                          ("step", 12)),
    "ItemAspectRatioMode": _DIRECTION,
    "NinePatchMode": (("Simple", 0, "stretch the whole image"), ("Classic", 1, "fixed corners"),
                      ("FixedHorizontalAspectRatio", 2, "fixed side proportions")),
    "PivotArea": (("TopLeftCorner", 0), ("TopRightCorner", 1), ("BottomLeftCorner", 2),
                  ("BottomRightCorner", 3), ("TopLeftPoint", 4), ("TopRightPoint", 5),
                  ("BottomLeftPoint", 6), ("BottomRightPoint", 7), ("TopLeftArea", 8), ("TopArea", 9),
                  ("TopRightArea", 10), ("LeftArea", 11), ("CenterArea", 12), ("RightArea", 13),
                  ("BottomLeftArea", 14), ("BottomArea", 15), ("BottomRightArea", 16)),
    "SpacingPolicy": _SPACING,
    "Style": (("Normal", 0), ("Shadow", 1), ("Outline", 2)),
    "TextPolicy": (("Fit", 0, "ask for the full width"), ("Scroll", 1, "scroll a long line"),
                   ("ScrollWrap", 2, "scroll and repeat")),
    "TransitionType": (("None", 0), ("Left", 1), ("Right", 2), ("Top", 3), ("Bottom", 4)),
    "VStretch": _STRETCH,
    "VerticalTextPolicy": (("Default", 0, "fit the height"), ("HeightFactor", 1, "use HeightFactor"),
                           ("Fit", 2, "fit width and height")),
}
# LoadMovie compares its own names; text alignment values do nothing there.
OBJECT_ENUMS = {
    ("Movie", "Alignment"): (("Center", 0), ("TopOrLeft", 1), ("BottomOrRight", 2)),
}
# Names whose hash was resolved after files could have been saved with the alias.
LEGACY_NAMES = {"UnnamedOption3": 1191184187, "UnnamedOption9": 2710529581}
ENUM_LABELS = {"UnnamedOption1": "Fill"}

# (token name, wire code, file name) of the fonts the game ships.
FONTS = (
    ("UnnamedOption4", 11, "accid.ttf"),
    ("UnnamedOption6", 10, "cuprum-bold.ttf"),
    ("UnnamedOption11", 9, "monkirta pursuit nc.ttf"),
    ("UnnamedOption7", 8, "nanumgothicbold.ttf"),
    ("UnnamedOption8", 7, "palatinosansarabic-regular.ttf"),
    ("UnnamedOption5", 6, "quark-bold.ttf"),
    ("UnnamedOption10", 3, "rodinntlgpro-db.ttf"),
    ("UnnamedOption2", 5, "roboto-thin.ttf"),
    ("UnnamedOption12", 2, "wqg-zenhei-prop.ttf"),
    ("UnnamedOption13", 1, "wqy_zenhei.ttf"),
)
FONT_PARAMETERS = {"FontName", "FontNameAR", "FontNameID", "FontNameJA", "FontNameKO", "FontNameRU",
                   "FontNameTH", "FontNameTR", "FontNameZH", "FontNameZH_HANT"}

_BOOL = {"Visible", "Enabled", "ClipRender", "ClipChildrenEvents", "EnableRightToLeftLayout",
         "EnableFixedWidth", "EnableFixedHeight", "EnableAspectRatio", "InvertAlignmentRTL", "Toggleable",
         "LeftOverlap", "RightOverlap", "KeepAspectRatio", "EnableRectangle", "SnapAtEdges"}
_INTEGER = {"RenderLayer": {}, "ShadowThickness": {}, "OutlineThickness": {}, "SnapAtChildren": {},
            "ColumnCount": {"min": 1}, "ScrollDelay": {"unit": "ms"}, "Delay": {"unit": "ms"},
            "Duration": {"unit": "ms", "min": 1}}
_PERCENT = {"FixedWidthFactor", "FixedHeightFactor", "HeightFactor", "FontHeightFactor", "KnobFactor",
            "SpacingFactor", "FontScalingAR", "FontScalingID", "FontScalingJA", "FontScalingKO",
            "FontScalingRU", "FontScalingTH", "FontScalingTR", "FontScalingZH", "FontScalingZH_HANT"}
_FLOAT = {"StretchFactor", "Spacing", "AspectRatio", "ItemAspectRatio", "ItemHeightAspectRatio",
          "ItemMainScale", "KnobAspectRatio", "LeftAspectRatio", "RightAspectRatio", "ScrollSpeed",
          "BarSize"}
_SIDES = ("Left", "Right", "Top", "Bottom")
_VECTORS = {
    "Size": {"fields": ("Width", "Height"), "unit": "mm"},
    "MinSize": {"fields": ("Width", "Height"), "unit": "mm"},
    "MaxSize": {"fields": ("Width", "Height"), "unit": "mm"},
    "Margins": {"fields": _SIDES, "unit": "mm"},
    "MarginFactors": {"fields": _SIDES, "unit": "%"},
    "TouchAreaGrowFactors": {"fields": _SIDES, "unit": "%"},
    "FontHeight": {"fields": ("Min", "Max")},
    "BakePosition": {"fields": ("X", "Y")},
    "Pivot": {"fields": ("X", "Y")},
    "NinePatchDef": {"fields": _SIDES},
    "NinePatchDefFH": {"fields": ("Left", "Right")},
    "Rectangle": {"fields": ("Left", "Top", "Right", "Bottom")},
}
_COLORS = {"PrimaryColor", "SecondaryColor", "ShadowColor", "OutlineColor", "Color"}
_STYLES = {"TextStyle", "PressedTextStyle", "ToggledTextStyle", "DisabledTextStyle", "EnabledTextStyle"}
_TEXT = {"TestString", "Source", "Movie", "Module"}
# Loader methods behind these parameters have empty bodies.
_NO_EFFECT = {"SnapAtEdges", "SnapAtChildren"}
# The loader drops these unless the named parameter was read before them.
READ_AFTER = {
    "ShadowColor": "Style", "OutlineColor": "Style", "ShadowThickness": "Style",
    "OutlineThickness": "Style", "NinePatchDef": "NinePatchMode", "NinePatchDefFH": "NinePatchMode",
}
_SPRINGS = {
    ("HorizontalSpring", "MinSize"): "Minimum height", ("HorizontalSpring", "MaxSize"): "Maximum width",
    ("VerticalSpring", "MinSize"): "Minimum width", ("VerticalSpring", "MaxSize"): "Maximum height",
}

# First class documents the object; the rest supply inherited parameter descriptions.
_CONTAINER = ("gin::WidgetContainer", "gin::Widget")
_TEXT_WIDGET = ("gin::LabelWidget", "gin::Widget")
OBJECT_CLASSES = {
    "HorizontalContainer": ("gin::HVContainer", *_CONTAINER),
    "VerticalContainer": ("gin::HVContainer", *_CONTAINER),
    "StackContainer": ("gin::StackContainer", *_CONTAINER),
    "GridContainer": ("gin::GridContainer", *_CONTAINER),
    "PageContainer": ("gin::PageContainer", *_CONTAINER),
    "ScrollContainer": ("gin::ScrollContainer", *_CONTAINER),
    "ThreeCellContainer": ("gin::ThreeCellContainer", *_CONTAINER),
    "MarginContainer": ("gin::MarginContainer", *_CONTAINER),
    "CoverFlowContainer": ("gin::CoverFlowContainer", *_CONTAINER),
    "AspectRatioContainer": ("gin::AspectRatioContainer", *_CONTAINER),
    "TransformContainer": ("gin::TransformContainer", *_CONTAINER),
    "FixedSizeContainer": ("gin::FixedSizeContainer", *_CONTAINER),
    "CompoundButton": ("gin::CompoundButtonWidget", *_CONTAINER),
    "Label": _TEXT_WIDGET,
    "Button": ("gin::ButtonWidget", *_TEXT_WIDGET),
    "ThreeCellButton": ("gin::ThreeCellButtonWidget", "gin::ButtonWidget", *_TEXT_WIDGET),
    "TextArea": ("gin::TextAreaWidget", "gin::Widget"),
    "Slider": ("gin::SliderWidget", "gin::Widget"),
    "Progress": ("gin::SliderWidget", "gin::Widget"),
    "Switch": ("gin::SwitchWidget", "gin::SliderWidget", "gin::Widget"),
    "MultiProgress": ("gin::MultiProgressWidget", "gin::Widget"),
    "CircularSlider": ("gin::CircularSliderWidget", "gin::Widget"),
    "CircularProgress": ("gin::CircularSliderWidget", "gin::Widget"),
    "HorizontalSpring": ("gin::SpringWidget", "gin::Widget"),
    "VerticalSpring": ("gin::SpringWidget", "gin::Widget"),
    "Movie": ("gin::MovieWidget", "gin::Widget"),
    "TextStyle": ("gin::TextStyle",),
    "Sprite": ("gin::SpriteBase", "gin::Sprite"),
    "Module": ("gin::SpriteBase", "gin::NinePatchDef"),
    "SpriteMovie": ("gin::SpriteBase",),
    "MovieModule": ("gin::SpriteBase",),
}


def _shape(obj, name, kind):
    if (obj, name) in _SPRINGS:
        return {"type": "float", "unit": "mm", "label": _SPRINGS[obj, name]}
    if obj == "Switch" and name in ("EnabledMargin", "DisabledMargin"):
        return {"type": "float"}
    if name in _BOOL:
        return {"type": "bool"}
    if name in _INTEGER:
        return {"type": "integer", "min": 0, **_INTEGER[name]}
    if name in _PERCENT:
        return {"type": "float", "unit": "%"}
    if name in _FLOAT:
        return {"type": "float"}
    if name in _VECTORS:
        return {"type": "vector", **_VECTORS[name]}
    if name in _COLORS:
        return {"type": "color"}
    if name in FONT_PARAMETERS:
        return {"type": "font"}
    if name in _STYLES:
        return {"type": "style"}
    if name in _TEXT:
        return {"type": "text"}
    if name in ENGINE_ENUMS or (obj, name) in OBJECT_ENUMS:
        return {"type": "enum"}
    return {"type": "sprite" if kind == "path" else "text" if kind == "string" else None}


def _group(spec, name, layout_names):
    if spec["type"] == "sprite" or name in ("Movie", "Module", "Source"):
        return "Images"
    if spec["type"] in ("font", "style", "color") or name.startswith("Font") or name in (
        "TestString", "TextPolicy", "VerticalTextPolicy", "HeightFactor", "ColorMode", "Style",
        "ShadowThickness", "OutlineThickness", "InvertAlignmentRTL", "ScrollSpeed", "ScrollDelay",
    ):
        return "Text"
    return "Layout" if name in layout_names else "Behaviour"


def _token(name, label, code, text, registered):
    token = {"enum": label}
    default = registered.get(name, {}).get(label)
    if default is None or default[0] != code:
        token["value"] = code
    if (default[2] if default else "") != text:
        token["text"] = text
    return token


def parameter(obj, name, kind, layout_names, registered, help_text):
    """Describe one parameter of one object for the inspector."""
    spec = _shape(obj, name, kind)
    if spec["type"] is None:
        return None
    if spec["type"] == "enum":
        options = OBJECT_ENUMS.get((obj, name), ENGINE_ENUMS[name])
        spec["options"] = [
            {
                "value": option[0],
                "label": ENUM_LABELS.get(option[0], option[0]),
                "hint": option[2] if len(option) > 2 else "",
                "token": _token(name, option[0], option[1], "", registered),
            }
            for option in options
        ]
    if spec["type"] == "font":
        fallback = "Default font" if name == "FontName" else "Use the base font"
        spec["options"] = [
            {"value": "Unspecified", "label": fallback, "hint": "", "token": {"enum": "Unspecified"}},
            *(
                {"value": label, "label": file, "hint": "",
                 "token": _token(name, label, code, file, registered)}
                for label, code, file in FONTS
            ),
        ]
    if name in _NO_EFFECT:
        spec["noEffect"] = True
    if name in READ_AFTER:
        spec["readAfter"] = READ_AFTER[name]
    spec["group"] = _group(spec, name, layout_names)
    described = help_text.get(obj, {}).get(name)
    if described:
        spec["help"] = described
    return spec
