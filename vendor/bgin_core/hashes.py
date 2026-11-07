"""
Complete type and property hash mappings — VERIFIED via MurmurHash2.

Hash algorithm: MurmurHash2 (32-bit), case-insensitive
  - seed = 0xFF4F5
  - Each input byte is OR'd with 0x20 (lowercase) before hashing
  - Standard MurmurHash2 finalization

Source: Reverse-engineered from libasphalt8.so via Ghidra
  jet::StringDB::InternalizeString at 0x01341e18

All type names confirmed from _INIT_215 @ 0x0069a194.
All property names confirmed from _INIT_215 string initializations.
All hash values COMPUTED (not guessed) using the verified algorithm.
"""

def jet_hash(value: str) -> int:
    """Asphalt 8 case-insensitive MurmurHash2 with seed 0xFF4F5."""
    data = bytes((byte | 0x20) for byte in value.encode("utf-8"))
    result = 0x000FF4F5 ^ len(data)
    index = 0
    while len(data) - index >= 4:
        chunk = int.from_bytes(data[index:index + 4], "little")
        chunk = (chunk * 0x5BD1E995) & 0xFFFFFFFF
        chunk ^= chunk >> 24
        chunk = (chunk * 0x5BD1E995) & 0xFFFFFFFF
        result = ((result * 0x5BD1E995) ^ chunk) & 0xFFFFFFFF
        index += 4
    tail = data[index:]
    if len(tail) == 3:
        result ^= tail[2] << 16
    if len(tail) >= 2:
        result ^= tail[1] << 8
    if tail:
        result ^= tail[0]
        result = (result * 0x5BD1E995) & 0xFFFFFFFF
    result ^= result >> 13
    result = (result * 0x5BD1E995) & 0xFFFFFFFF
    result ^= result >> 15
    return result & 0xFFFFFFFF

# =========================================================================
# Widget Type Hashes (28 types, verified)
# =========================================================================

TYPE_HASH: dict[int, str] = {
    # --- Containers ---
    0xB490D6D6: "HorizontalContainer",
    0xDE8925BA: "VerticalContainer",
    0x8706BEAF: "StackContainer",
    0xCE026A8F: "GridContainer",
    0x47B597C6: "PageContainer",
    0xC6D609D8: "ScrollContainer",
    0xE7D7F713: "ThreeCellContainer",
    0xA855F996: "MarginContainer",
    0xD5B3083A: "CoverFlowContainer",
    0x915854F8: "AspectRatioContainer",
    0x4A745A36: "TransformContainer",
    0x02737331: "FixedSizeContainer",

    # --- Display ---
    0x34EA05F7: "Label",
    0x57CCBBC1: "TextArea",
    0x3FD29A03: "TextStyle",
    0x6E739C13: "Movie",

    # --- Interactive ---
    0x7D332216: "Button",
    0x2829EE60: "CompoundButton",
    0xFE3354C4: "ThreeCellButton",
    0xB76EA225: "Slider",
    0x6E077718: "CircularSlider",
    0xBFEB3F90: "Switch",

    # --- Progress ---
    0x33EF85C7: "Progress",
    0xB737FB69: "MultiProgress",
    0x98811796: "CircularProgress",

    # --- Springs ---
    0x64BAC2F5: "HorizontalSpring",
    0xB8F333D9: "VerticalSpring",

    # --- Other ---
    0x93EF34CD: "Module",
    0x3BA2E9E2: "Sprite",
    0xBE17FA7A: "SpriteMovie",
    0xEB9A8C92: "MovieModule",
}

# =========================================================================
# Property Hashes (200+, computed via MurmurHash2)
# =========================================================================

PROPERTY_HASH: dict[int, str] = {
    # --- Layout (read by LoadWidgetParam @ 0x011939a4) ---
    0x28C8DE16: "Size",
    0x69F9BB03: "MinSize",
    0x71B64C87: "MaxSize",
    0x56D1D428: "StretchFactor",
    0x28089FC6: "RenderLayer",
    0x5E69021F: "Enabled",
    0x497D3FA3: "Visible",
    0xA21C7CC3: "Margins",
    0xB38EDC56: "Spacing",
    0xA15CC0EF: "ClipChildrenEvents",
    0x1B458D3E: "ClipRender",
    0x24379B83: "Position",
    0x356D775C: "Anchor",
    0x14944A14: "Rectangle",
    0xAA0101F9: "Pivot",
    0xD64D735F: "PivotArea",

    # --- Label/Text (read by LoadLabelParam @ 0x01193f70) ---
    0xFA70D79B: "Text",
    0x48B93E13: "TestString",
    0x9345E1C1: "TextPolicy",
    0x755FF117: "VerticalTextPolicy",
    0x97054849: "InvertAlignmentRTL",
    0xD9F96716: "Alignment",
    0x3FD29A03: "TextStyle",

    # --- TextStyle properties ---
    0x1FD21457: "FontName",
    0x07F01349: "FontHeight",
    0x7C92DC4B: "FontHeightFactor",
    0x7146BD82: "Style",
    0x8BAF2909: "Color",
    0xEE755020: "ColorMode",
    0x01B71579: "PrimaryColor",
    0x2181CA2D: "SecondaryColor",
    0xF314786A: "ShadowColor",
    0x75338D2E: "OutlineColor",
    0xA5C982F4: "ShadowThickness",
    0xEFE58F26: "OutlineThickness",
    0x377E5D61: "Normal",
    0x230F396F: "Shadow",
    0x330FF606: "Outline",
    0x6CF73E26: "GradientLeftRight",
    0xCCEFB3D4: "GradientRightLeft",
    0xCFD706BB: "GradientTopBottom",
    0x91C1E969: "GradientBottomTop",

    # --- Localized Fonts ---
    0x0800256F: "FontNameJA",
    0xCEB2CDEB: "FontNameKO",
    0xD2EB1E4B: "FontNameZH",
    0x59FF27C5: "FontNameZH_HANT",
    0xF50F5A7D: "FontNameRU",
    0x1A039F9A: "FontNameTR",
    0xD866B0A1: "FontNameAR",
    0xF2769BD4: "FontNameTH",
    0x4AA4A98A: "FontNameID",
    0x6D2EDCBB: "FontScalingJA",
    0x2F3248B5: "FontScalingKO",
    0xBD5B4CE7: "FontScalingZH",
    0xF8EC377D: "FontScalingZH_HANT",
    0x03258DB0: "FontScalingRU",
    0x50875677: "FontScalingTR",
    0xE9C89269: "FontScalingAR",
    0x9865685F: "FontScalingTH",
    0xFB98E4A0: "FontScalingID",

    # --- Button-specific (LoadButtonParam @ 0x01194358) ---
    0x16479B71: "Toggleable",
    0x4212066E: "ButtonEventPolicy",
    0x2461418B: "Autopress",
    0x1E7EF1A7: "TouchAreaGrowFactors",
    0x0C1A2475: "NormalBackground",
    0xFADE64F6: "PressedBackground",
    0x4745801F: "ToggledBackground",
    0xC96A7EFF: "ToggledPressedBackground",
    0xEAA6ECBE: "DisabledBackground",
    0xF35FC603: "DisabledToggledBackground",
    0x843AD391: "PressedTextStyle",
    0xD572435C: "ToggledTextStyle",
    0x59C9FE86: "EnabledTextStyle",
    0x209F6E2D: "DisabledTextStyle",

    # --- ThreeCell-specific ---
    0x1264C27C: "LeftBackground",
    0x56ED6CEC: "RightBackground",
    0x573E1F01: "PressedLeftBackground",
    0xF1E5BED1: "PressedRightBackground",
    0xB6D35F7F: "ToggledLeftBackground",
    0x55D3E150: "ToggledRightBackground",
    0xDC9247E5: "DisabledLeftBackground",
    0x437F37C8: "DisabledRightBackground",
    0x0CADD459: "LeftOverlap",
    0x3B3C1AF6: "RightOverlap",
    0x6DCBFF5A: "LeftAspectRatio",
    0x5DFAF903: "RightAspectRatio",

    # --- Grid ---
    0x8D07E209: "ColumnCount",
    0xDAC2CAF7: "ItemAspectRatio",
    0xAE82FE9D: "ItemAspectRatioMode",
    0x1C67692E: "ItemMainScale",
    0x1DDEB012: "ItemHeightAspectRatio",

    # --- Scroll ---
    0xE64A5723: "Direction",
    0x20F5452D: "Horizontal",
    0xBC50EBF6: "ScrollSpeed",
    0xB87FB6AC: "ScrollDelay",
    0x861B07AF: "SnapAtChildren",
    0x8D8AF181: "SnapAtEdges",

    # --- CoverFlow ---
    0x2D0033DF: "SpacingFactor",
    0xC8176D90: "MarginFactors",

    # --- AspectRatio ---
    0x06B3591C: "KeepAspectRatio",
    0x2D6C132B: "AspectRatio",
    0x94DE0460: "EnableAspectRatio",

    # --- Layout policies ---
    0xAE889DFF: "EmptySpaceFillPolicy",
    0x8BE54749: "ArrangeTopOrLeft",
    0x10918127: "ArrangeCenter",
    0xD08EC072: "ArrangeBottomOrRight",
    0x45F21DEA: "EnableRightToLeftLayout",
    0x21FE7FBF: "HeightFactor",
    0xAF2B436B: "Factor",
    0x69B35744: "ScreenHeightFactor",
    0x97737B05: "ScreenWidthFactor",
    0xDDC5DDB2: "SpacingPolicy",

    # --- Slider (LoadSliderParam @ 0x01193cc0) ---
    0xD391F1F0: "BarBackground",
    0xD25223DB: "BarKnob",
    0x82CAFEC9: "BarVisibility",
    0x2AF223CE: "BarSizePolicy",
    0xB1A10CB1: "BarSize",
    0x17ED4067: "NormalKnob",
    0x80B55219: "PressedKnob",
    0x945A0B61: "KnobBackground",
    0xFD6E2B63: "KnobFactor",
    0xCA6366D9: "KnobAspectRatio",

    # --- Progress ---
    0x2C4AC018: "FillBackground",
    0x7B42B702: "FillBackground0",
    0x62DF9900: "FillBackground1",
    0x28DF8FA9: "FillBackground2",

    # --- Movie / Sprite ---
    0xAD78FB39: "Source",
    0x3BA2E9E2: "Sprite",
    0xBE17FA7A: "SpriteMovie",
    0xEB9A8C92: "MovieModule",
    0x023A24D7: "BakePosition",
    0xDE30783E: "HStretch",
    0x4CC68EF5: "VStretch",
    0x0E9D5058: "NinePatchMode",
    0x62DBA26E: "NinePatchDef",
    0x4C81ABC1: "NinePatchDefFH",
    0xCAD45D98: "EnableRectangle",

    # --- Fixed Size ---
    0x7C507826: "EnableFixedWidth",
    0x5F1631E7: "EnableFixedHeight",
    0x7766BD8A: "FixedWidthFactor",
    0xB6490172: "FixedHeightFactor",

    # --- Animation / Transition ---
    0x50AB1E90: "Delay",
    0xF2AA349D: "Duration",
    0xAA454DBC: "TransitionType",
    0xBB5F167D: "InterpolationMode",
    0x88306415: "step",
    0x01EE0980: "linear",
    0x94B6BAF9: "smooth",
    0x3686B541: "smoother",
    0xC19C5629: "quadratic_i",
    0x11B9A4B1: "quadratic_o",
    0xEBDB5063: "quadratic_io",
    0xBB8A7B4D: "quartic_i",
    0x2AE3C16E: "quartic_o",
    0xB0895AB9: "quartic_io",
    0x3872B637: "octic_i",
    0xD707E0CE: "octic_o",
    0xA3D8EBE7: "octic_io",

    # --- Alignment values ---
    0x09A2DC9E: "Center",
    0xFD84BCB3: "TopLeft",
    0x20A39C74: "TopRight",
    0x9ABBE9E9: "Top",
    0x97D22CA8: "Left",
    0x42EBD880: "Right",
    0x05402AFA: "BottomLeft",
    0xA7322BE0: "Bottom",
    0x605E5F53: "BottomRight",
    0xFC80BE86: "TopLeftCorner",
    0x18D37AE0: "TopRightCorner",
    0xE7917506: "BottomLeftCorner",
    0x41DE1C2A: "BottomRightCorner",
    0xB51B830B: "TopLeftPoint",
    0x02BD06A6: "TopRightPoint",
    0xCC8D1B23: "BottomLeftPoint",
    0xBA9725E1: "BottomRightPoint",
    0xC3F23314: "TopLeftArea",
    0x1A1D85FD: "TopArea",
    0x71CD3E2B: "TopRightArea",
    0x6372A329: "LeftArea",
    0x80030DC6: "CenterArea",
    0xBB26667C: "RightArea",
    0xA98A87C5: "BottomLeftArea",
    0x89FD182E: "BottomArea",
    0x6175BE67: "BottomRightArea",

    # --- Values / Policies ---
    0x416068BC: "Tile",
    0x22A88669: "Classic",
    0x747C57A5: "FixedHorizontalAspectRatio",
    0xD9A71C64: "Scroll",
    0x837DD305: "ScrollWrap",
    0xB754CC55: "Fit",
    0x59CE0DA9: "Fill",
    0x66EDA332: "Default",
    0xE45E2D39: "Always",
    0x6ED86289: "Hidden",
    0x0C530FCF: "AutoHide",
    0x72688011: "Background",
    0xFF4AD5D0: "Fitting",
    0xEA399089: "TopOrLeft",
    0xEA6796D4: "BottomOrRight",
    0x1FCC9194: "EnabledMargin",
    0xC99B6E5A: "DisabledMargin",
}


def get_type_name(type_hash: int) -> str:
    """Get human-readable widget type name from hash."""
    return TYPE_HASH.get(type_hash, f"unknown_0x{type_hash:08X}")


def get_property_name(prop_hash: int) -> str:
    """Get human-readable property name from hash."""
    return PROPERTY_HASH.get(prop_hash, f"unknown_0x{prop_hash:08X}")


def get_type_hash(name: str) -> int | None:
    """Get type hash from name (reverse lookup)."""
    return jet_hash(name)


def get_property_hash(name: str) -> int | None:
    """Get property hash from name (reverse lookup)."""
    return jet_hash(name)


# Build reverse lookup tables
TYPE_NAME: dict[str, int] = {v: k for k, v in TYPE_HASH.items()}
PROPERTY_NAME: dict[str, int] = {v: k for k, v in PROPERTY_HASH.items()}
