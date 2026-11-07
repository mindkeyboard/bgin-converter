import { nodeIcon } from "./icons";
import { t } from "./i18n";

/** Type choices expose the same glyphs as the object tree, including keyboard navigation. */
export class TypePicker {
  readonly element = document.createElement("div");
  private filter = document.createElement("input");
  private list = document.createElement("div");
  private selected = "";
  private types: string[] = [];
  constructor(types: string[], value: string, title: string, private openDocs?: (type: string) => void) {
    this.element.className = "type-picker";
    this.filter.type = "search";
    this.filter.placeholder = t("Filter object types");
    this.filter.setAttribute("aria-label", t("Filter object types"));
    this.list.className = "type-choices";
    this.list.setAttribute("role", "listbox");
    this.list.setAttribute("aria-label", title);
    this.element.append(this.filter, this.list);
    this.filter.oninput = () => this.draw();
    this.filter.onkeydown = (e) => {
      if (e.key === "Enter") {
        const choice = this.list.querySelector<HTMLButtonElement>('button[aria-selected="true"]') ||
          this.list.querySelector<HTMLButtonElement>('[role="option"]');
        if (choice) choice.click(); else e.preventDefault();
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        this.list.querySelector<HTMLButtonElement>('[role="option"]')?.focus();
      }
    };
    this.setTypes(types, value);
  }
  get value() { return this.selected; }
  setTypes(types: string[], preferred = this.selected) {
    this.types = types;
    this.selected = types.includes(preferred) ? preferred : types[0] || "";
    this.element.dataset.value = this.selected;
    this.filter.value = "";
    this.draw();
  }
  focus() { this.filter.focus(); }
  private draw() {
    this.list.replaceChildren();
    const query = this.filter.value.trim().toLowerCase();
    const matches = this.types.filter(type => type.toLowerCase().includes(query));
    for (const type of matches) {
      const card = document.createElement("div");
      card.className = "type-card";
      card.setAttribute("role", "presentation");
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", String(type === this.selected));
      button.dataset.type = type;
      button.tabIndex = type === this.selected ? 0 : -1;
      const name = document.createElement("span");
      name.textContent = type;
      button.append(nodeIcon(type), name);
      button.onclick = () => {
        this.selected = type;
        this.element.dataset.value = type;
        for (const item of this.list.querySelectorAll<HTMLButtonElement>('[role="option"]')) {
          item.setAttribute("aria-selected", String(item === button));
          item.tabIndex = item === button ? 0 : -1;
        }
      };
      button.onkeydown = (e) => {
        const keys = ["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Home", "End"];
        if (!keys.includes(e.key)) return;
        e.preventDefault();
        const buttons = [...this.list.querySelectorAll<HTMLButtonElement>('[role="option"]')];
        const at = buttons.indexOf(button);
        const columns = Math.max(1, Math.round(this.list.clientWidth / button.offsetWidth));
        const step = e.key === "ArrowDown" ? columns : e.key === "ArrowUp" ? -columns : e.key === "ArrowRight" ? 1 : -1;
        const next = e.key === "Home" ? 0 : e.key === "End" ? buttons.length - 1 :
          Math.max(0, Math.min(buttons.length - 1, at + step));
        buttons[next]?.click();
        buttons[next]?.focus();
      };
      card.append(button);
      if (this.openDocs) {
        const docs = document.createElement("button");
        docs.type = "button";
        docs.className = "type-docs documentation-button";
        docs.dataset.docsType = type;
        docs.title = docs.ariaLabel = t("Open documentation for") + " " + type;
        docs.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M5 3h10l4 4v14H5zM14 3v5h5M8 12h8M8 16h6"/></svg>';
        docs.onclick = (event) => { event.stopPropagation(); this.openDocs?.(type); };
        card.append(docs);
      }
      this.list.append(card);
    }
    if (!matches.length) {
      const empty = document.createElement("p");
      empty.textContent = t("No matching types");
      this.list.append(empty);
    }
  }
}
