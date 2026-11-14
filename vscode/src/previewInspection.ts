import { t } from "./i18n";
export type Geometry = { path: string; name: string; type: string; x: number; y: number; width: number; height: number };
export type InspectionState = { mode: "normal" | "exploded" | "xray"; depth: number; cut: number };
type Painted = { element: SVGElement; path: string; transform: string | null; opacity: string | null };
const NS = "http://www.w3.org/2000/svg";
/** Scene transforms affect cached paint only. Engine layout and document data stay intact. */
export class PreviewInspection {
  private painted: Painted[];
  private geometries: Map<string, Geometry>;
  private decoration: SVGGElement;
  private arrangement = "";
  private size: { width: number; height: number };
  constructor(private svg: SVGSVGElement, geometry: Geometry[], private width: number, private height: number) {
    this.painted = Array.from(svg.querySelectorAll<SVGElement>("g[data-path]")).map(element => ({ element, path: element.dataset.path || "", transform: element.getAttribute("transform"), opacity: element.getAttribute("opacity") }));
    this.geometries = new Map(geometry.map(g => [g.path, g]));
    this.decoration = document.createElementNS(NS, "g"); this.decoration.setAttribute("pointer-events", "none"); this.decoration.dataset.inspectionLabels = "true"; svg.append(this.decoration);
    this.size = { width, height };
  }
  get layers() { return this.painted.length; }
  apply(state: InspectionState, selected: string, selectionOnly: boolean) {
    const key = `${state.mode}/${state.depth}`;
    if (this.arrangement !== key) {
      this.arrangement = key;
      this.decoration.replaceChildren();
      for (const p of this.painted) {
        if (p.transform === null) p.element.removeAttribute("transform"); else p.element.setAttribute("transform", p.transform);
        if (p.opacity === null) p.element.removeAttribute("opacity"); else p.element.setAttribute("opacity", p.opacity);
      }
      this.size = { width: this.width, height: this.height };
      if (state.mode === "exploded") this.spread(state.depth);
      if (state.mode === "xray") for (const p of this.painted) p.element.setAttribute("opacity", String(Number(p.opacity ?? 1) * 0.18));
      this.svg.setAttribute("viewBox", `0 0 ${this.size.width} ${this.size.height}`);
      this.svg.setAttribute("width", String(this.size.width)); this.svg.setAttribute("height", String(this.size.height));
    }
    const last = this.painted.length - Math.max(0, Math.min(state.cut, this.painted.length));
    this.painted.forEach((p, i) => {
      const outside = state.mode === "normal" && !state.cut && selectionOnly && selected && p.path !== selected && !p.path.startsWith(selected + "/");
      p.element.style.display = i >= last || outside ? "none" : "";
    });
    return this.size;
  }
  private spread(depth: number) {
    // Partition paint by branch depth; ancestors keep their own separate cells.
    const buckets = new Map<string, Painted[]>();
    for (const p of this.painted) {
      const key = p.path.split("/").slice(0, 3 + 2 * Math.max(1, depth)).join("/");
      if (!buckets.has(key)) buckets.set(key, []); buckets.get(key)!.push(p);
    }
    const cells = [...buckets].map(([path, paint]) => {
      const rects = paint.map(p => this.geometries.get(p.path)).filter((g): g is Geometry => !!g && [g.x, g.y, g.width, g.height].every(Number.isFinite));
      const x = rects.length ? Math.min(...rects.map(g => g.x)) : 0, y = rects.length ? Math.min(...rects.map(g => g.y)) : 0;
      const width = Math.max(1, rects.length ? Math.max(...rects.map(g => g.x + g.width)) - x : this.width);
      const height = Math.max(1, rects.length ? Math.max(...rects.map(g => g.y + g.height)) - y : this.height);
      return { path, paint, x, y, width, height };
    });
    if (!cells.length) return;
    const pad = 24, label = 34, cellWidth = Math.max(...cells.map(c => c.width)) + 2 * pad, cellHeight = Math.max(...cells.map(c => c.height)) + label + 2 * pad;
    const columns = Math.max(1, Math.ceil(Math.sqrt(cells.length * cellHeight / cellWidth)));
    this.size = { width: columns * cellWidth, height: Math.ceil(cells.length / columns) * cellHeight };
    cells.forEach((cell, i) => {
      const x = (i % columns) * cellWidth + pad, y = Math.floor(i / columns) * cellHeight + pad;
      const caption = document.createElementNS(NS, "text"); caption.setAttribute("x", String(x)); caption.setAttribute("y", String(y + 20)); caption.setAttribute("font-size", "18"); caption.setAttribute("fill", "#b9d8ff");
      const node = this.geometries.get(cell.path); caption.textContent = node ? `${node.name} · ${node.type}` : cell.path;
      this.decoration.append(caption);
      for (const p of cell.paint) p.element.setAttribute("transform", `translate(${x - cell.x} ${y + label - cell.y}) ${p.transform || ""}`.trim());
    });
  }
}

/** Explicit inspection controls never start another render or edit the BGIN document. */
export function inspectionControls(root: HTMLElement, state: InspectionState, change: () => void) {
  root.innerHTML = `<label>${t("View")} <select id="inspectionMode" aria-label="${t("Screen inspection")}"><option value="normal">${t("Normal")}</option><option value="exploded">${t("Spread branches")}</option><option value="xray">${t("X-ray")}</option></select></label><label>${t("Branch depth")} <input id="inspectionDepth" aria-label="${t("Branch depth")}" type="number" min="1" max="12" value="1"></label><label class="layer-cut">${t("Hide top layers")} <input id="layerCut" aria-label="${t("Hide top layers")}" type="range" min="0" max="0" value="0"><output id="layerCount">0 / 0</output></label><button id="resetInspection">${t("Reset view")}</button>`;
  const mode = root.querySelector<HTMLSelectElement>("#inspectionMode")!, depth = root.querySelector<HTMLInputElement>("#inspectionDepth")!, cut = root.querySelector<HTMLInputElement>("#layerCut")!, count = root.querySelector<HTMLOutputElement>("#layerCount")!;
  mode.value = state.mode; depth.value = String(state.depth);
  const update = () => { depth.disabled = state.mode !== "exploded"; count.value = `${state.cut} / ${cut.max}`; };
  mode.onchange = () => { state.mode = mode.value as InspectionState['mode']; update(); change(); };
  depth.onchange = () => { state.depth = Math.max(1, Math.min(12, Number(depth.value) || 1)); depth.value = String(state.depth); change(); };
  cut.oninput = () => { state.cut = Number(cut.value); update(); change(); };
  root.querySelector<HTMLButtonElement>("#resetInspection")!.onclick = () => { state.mode = "normal"; state.depth = 1; state.cut = 0; mode.value = "normal"; depth.value = "1"; cut.value = "0"; update(); change(); };
  update();
  return (layers: number, enabled: boolean) => { root.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLButtonElement>("input,select,button").forEach(e => e.disabled = !enabled); cut.max = String(layers); state.cut = Math.min(state.cut, layers); cut.value = String(state.cut); update(); if (!enabled) depth.disabled = true; };
}
