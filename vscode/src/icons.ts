/** Local vector glyphs share a grid and theme-aware category colors. */
const shapes: Record<string, string> = {
  HorizontalContainer:
    '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M9 5v14m6-14v14"/>',
  VerticalContainer:
    '<rect x="5" y="3" width="14" height="18" rx="3"/><path d="M5 9h14M5 15h14"/>',
  StackContainer:
    '<path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5"/>',
  GridContainer:
    '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M9 3v18m6-18v18M3 9h18M3 15h18"/>',
  PageContainer:
    '<rect x="5" y="3" width="14" height="15" rx="2"/><path d="M9 21h6m-6-7h6"/>',
  ScrollContainer:
    '<rect x="3" y="3" width="14" height="18" rx="2"/><path d="m20 7 2-3m-2 13 2 3M7 8h6M7 12h6M7 16h4"/>',
  ThreeCellContainer:
    '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M7 5v14M17 5v14"/>',
  MarginContainer:
    '<rect x="3" y="3" width="18" height="18" rx="3"/><rect x="8" y="8" width="8" height="8" rx="1" stroke-dasharray="2 2"/>',
  CoverFlowContainer:
    '<rect x="8" y="4" width="8" height="16" rx="2"/><path d="m5 7-3 2v6l3 2m14-10 3 2v6l-3 2"/>',
  AspectRatioContainer:
    '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 10V9h3m7 5v1h-3M7 15l10-6"/>',
  TransformContainer:
    '<path d="M4 8V4h4m8 0h4v4m0 8v4h-4M8 20H4v-4"/><path d="m12 7 5 5-5 5-5-5 5-5Z"/>',
  FixedSizeContainer:
    '<rect x="5" y="5" width="14" height="14" rx="2"/><path d="M5 2h14M2 5v14m3 3h14m3-17v14"/>',
  HorizontalSpring: '<path d="M3 6v12M21 6v12M3 12h3l2-5 4 10 4-10 2 5h3"/>',
  VerticalSpring: '<path d="M6 3h12M6 21h12M12 3v3l5 2-10 4 10 4-5 2v3"/>',
  Label: '<path d="M4 5h16M12 5v14m-4 0h8M4 8V5m16 3V5"/>',
  TextArea: '<path d="M4 5h16M4 10h16M4 15h10M4 20h13"/>',
  TextStyle: '<path d="m3 19 6-14 6 14M5 15h8m3 4 5-7m-2 6 2 1"/>',
  Button:
    '<rect x="3" y="6" width="18" height="12" rx="5"/><path d="M8 12h8"/>',
  CompoundButton:
    '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m7 12 3 3 7-7"/>',
  ThreeCellButton:
    '<rect x="2" y="6" width="20" height="12" rx="4"/><path d="M7 6v12m10-12v12m-7-6h4"/>',
  Slider:
    '<path d="M3 12h7m4 0h7"/><rect x="10" y="6" width="4" height="12" rx="2"/>',
  CircularSlider:
    '<path d="M5 18a9 9 0 1 1 14 0"/><circle cx="18" cy="5" r="2.5"/>',
  Progress:
    '<rect x="3" y="7" width="18" height="10" rx="3"/><path d="M7 10v4m4-4v4m4-4v4"/>',
  MultiProgress:
    '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M7 9h10M7 12h7m-7 3h4"/>',
  CircularProgress:
    '<circle cx="12" cy="12" r="8" opacity=".4"/><path d="M12 4a8 8 0 0 1 8 8" stroke-width="3"/>',
  Switch:
    '<rect x="2" y="6" width="20" height="12" rx="6"/><circle cx="15" cy="12" r="3"/>',
  Movie:
    '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m10 8 6 4-6 4V8ZM3 8h3m12 0h3M3 16h3m12 0h3"/>',
  Sprite:
    '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m4 17 5-5 3 3 4-6 5 8"/>',
  Module: '<path d="m12 3 9 5v9l-9 4-9-4V8l9-5Zm-9 5 9 5 9-5m-9 5v8"/>',
  SpriteMovie: '<path d="M4 5h16v14H4zM4 9h16m-9 3 5 2-5 2v-4Z"/>',
  MovieModule: '<path d="M4 5h16v14H4zM4 9h16"/><path d="m8 15 2-2 3 3 3-4"/>',
};

export function nodeIcon(kind: string): SVGSVGElement {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const group =
    kind.endsWith("Container") || kind.endsWith("Spring")
      ? "container"
      : ["Label", "TextArea", "TextStyle"].includes(kind)
        ? "text"
        : ["Sprite", "Module", "Movie", "SpriteMovie", "MovieModule"].includes(
              kind,
            )
          ? "graphic"
          : "control";
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.65");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("node-icon", "icon-" + group);
  svg.innerHTML = shapes[kind] || shapes.Module;
  return svg;
}
