import { nodeIcon } from "./icons";

export type TreeRow = {
  node: any;
  path: string;
  depth: number;
  opened: boolean;
  has: boolean;
};
/** Only visible rows enter the DOM. Selection never changes expansion or scroll position. */
export class ObjectTree {
  private rows: TreeRow[] = [];
  private selected = "";
  private surface = document.createElement("div");
  private frame = 0;
  private observer: ResizeObserver;
  private listeners = new AbortController();
  readonly height = 32;
  constructor(
    private root: HTMLElement,
    private choose: (path: string) => void,
    private toggle: (path: string) => void,
    private menu?: (path: string, x: number, y: number) => void,
  ) {
    this.surface.className = "tree-surface";
    root.replaceChildren(this.surface);
    root.addEventListener("scroll", () => this.schedule(), {
      signal: this.listeners.signal,
    });
    this.observer = new ResizeObserver(() => this.schedule());
    this.observer.observe(root);
    root.addEventListener("contextmenu", (e) => {
      e.preventDefault();
    });
    root.addEventListener("keydown", (e) => {
      const row = (e.target as Element).closest<HTMLElement>(".tree-row");
      if (!row) return;
      const index = this.rows.findIndex((r) => r.path === row.dataset.path);
      const current = this.rows[index];
      if (!current) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const next =
          this.rows[
            Math.max(
              0,
              Math.min(
                this.rows.length - 1,
                index + (e.key === "ArrowDown" ? 1 : -1),
              ),
            )
          ];
        this.choose(next.path);
        this.reveal(next.path);
      } else if (
        ((e.key === "ArrowRight" && !current.opened) ||
          (e.key === "ArrowLeft" && current.opened)) &&
        current.has
      ) {
        e.preventDefault();
        this.toggle(current.path);
      } else if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        this.choose(current.path);
      } else if (
        (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) &&
        this.menu
      ) {
        e.preventDefault();
        const box = row.getBoundingClientRect();
        this.menu(current.path, box.x + 25, box.y + 20);
      }
    });
  }
  set(rows: TreeRow[], selected: string) {
    if (!this.surface.isConnected) this.root.replaceChildren(this.surface);
    const top = this.root.scrollTop,
      left = this.root.scrollLeft;
    const unchanged =
      rows.length === this.rows.length &&
      rows.every((row, i) => {
        const old = this.rows[i];
        return (
          row.path === old.path &&
          row.opened === old.opened &&
          row.has === old.has &&
          row.node.type === old.node.type
        );
      });
    this.rows = rows;
    this.selected = selected;
    this.surface.style.height = rows.length * this.height + "px";
    if (unchanged) {
      const byPath = new Map(rows.map((row) => [row.path, row]));
      for (const element of this.surface.querySelectorAll<HTMLElement>(
        ".tree-row",
      )) {
        const row = byPath.get(element.dataset.path!);
        if (!row) continue;
        element.querySelector("span")!.textContent = row.node.name;
        element.querySelector("small")!.textContent = row.node.type;
        if (element.dataset.kind !== row.node.type) {
          element
            .querySelector(".node-icon")
            ?.replaceWith(nodeIcon(row.node.type));
          element.dataset.kind = row.node.type;
        }
        element.title = row.node.name + " · " + row.node.type;
      }
      this.select(selected);
    } else this.render();
    this.root.scrollTop = top;
    this.root.scrollLeft = left;
  }
  dispose() {
    cancelAnimationFrame(this.frame);
    this.observer.disconnect();
    this.listeners.abort();
  }
  select(path: string) {
    this.selected = path;
    for (const row of this.surface.querySelectorAll<HTMLElement>(".tree-row")) {
      const selected = row.dataset.path === path;
      row.classList.toggle("selected", selected);
      row.setAttribute("aria-selected", String(selected));
    }
  }
  reveal(path: string) {
    const i = this.rows.findIndex((r) => r.path === path);
    if (i < 0) return;
    const y = i * this.height;
    if (y < this.root.scrollTop) this.root.scrollTop = y;
    else if (y + this.height > this.root.scrollTop + this.root.clientHeight)
      this.root.scrollTop = y + this.height - this.root.clientHeight;
    this.render();
    this.surface
      .querySelector<HTMLElement>(`[data-path="${CSS.escape(path)}"]`)
      ?.focus({ preventScroll: true });
  }
  private schedule() {
    cancelAnimationFrame(this.frame);
    this.frame = requestAnimationFrame(() => this.render());
  }
  private render() {
    const focused = this.root.contains(document.activeElement)
      ? (document.activeElement as HTMLElement)?.closest<HTMLElement>(
          ".tree-row",
        )?.dataset.path
      : undefined;
    const start = Math.max(
      0,
      Math.floor(this.root.scrollTop / this.height) - 8,
    );
    const end = Math.min(
      this.rows.length,
      start + Math.ceil(this.root.clientHeight / this.height) + 18,
    );
    const fragment = document.createDocumentFragment();
    for (let i = start; i < end; i++) {
      const item = this.rows[i],
        row = document.createElement("div");
      row.className =
        "tree-row" + (item.path === this.selected ? " selected" : "");
      row.dataset.path = item.path;
      row.dataset.kind = item.node.type;
      row.setAttribute("role", "treeitem");
      row.setAttribute("aria-level", String(item.depth + 1));
      row.setAttribute("aria-selected", String(item.path === this.selected));
      if (item.has) row.setAttribute("aria-expanded", String(item.opened));
      row.tabIndex = 0;
      row.style.top = i * this.height + "px";
      row.style.paddingLeft = item.depth * 18 + 6 + "px";
      const expander = document.createElement("button");
      expander.className = "expander";
      expander.tabIndex = -1;
      expander.setAttribute("aria-label", item.opened ? "Collapse" : "Expand");
      if (item.has) {
        expander.innerHTML =
          '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="' +
          (item.opened ? "m4 6 4 4 4-4" : "m6 4 4 4-4 4") +
          '"/></svg>';
        expander.onclick = (e) => {
          e.stopPropagation();
          this.toggle(item.path);
        };
      } else {
        expander.classList.add("leaf-marker");
        expander.disabled = true;
      }
      const name = document.createElement("span"),
        type = document.createElement("small");
      name.textContent = item.node.name;
      type.textContent = item.node.type;
      row.title = item.node.name + " · " + item.node.type;
      row.append(expander, nodeIcon(item.node.type), name, type);
      row.onclick = () => this.choose(item.path);
      if (this.menu)
        row.oncontextmenu = (e) => {
          e.preventDefault();
          e.stopPropagation();
          this.menu!(item.path, e.clientX, e.clientY);
        };
      fragment.append(row);
    }
    this.surface.replaceChildren(fragment);
    if (focused)
      this.surface
        .querySelector<HTMLElement>(`[data-path="${CSS.escape(focused)}"]`)
        ?.focus({ preventScroll: true });
  }
}
