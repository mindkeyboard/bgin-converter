import { dialog } from "./dialogs";
import { ObjectTree, TreeRow } from "./tree";
import { t } from "./i18n";

/** Prefixes are derived from names, never a list of engine screen categories. */
export function screenPrefix(name: string): string {
  if (!name || name.startsWith("#")) return "";
  return name.replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2").split(/[_\-\s.:/]+/)
    .find(Boolean)?.replace(/\d+$/, "").toLocaleLowerCase() || "";
}
export function pickScreen(screens: any[], current: number, choose: (index: number) => void) {
  const modal = dialog(t("Choose screen"));
  modal.element.id = "screenPicker";
  const query = document.createElement("input"), view = document.createElement("select"), prefix = document.createElement("select");
  query.id = "screenQuery"; query.placeholder = t("Name or type…"); query.setAttribute("aria-label", t("Search screens"));
  view.id = "screenView"; view.setAttribute("aria-label", t("Screen view"));
  view.add(new Option(t("All"), "all")); view.add(new Option(t("By prefix"), "prefix"));
  prefix.id = "screenPrefix"; prefix.setAttribute("aria-label", t("Prefix")); prefix.add(new Option(t("All prefixes"), ""));
  const groups = new Map<string, number>();
  screens.forEach(s => { const key = screenPrefix(s.name); groups.set(key, (groups.get(key) || 0) + 1); });
  for (const [key, count] of [...groups].sort(([a], [b]) => a.localeCompare(b)))
    prefix.add(new Option(`${key || t("Without prefix")} (${count})`, key || "__none"));
  const controls = document.createElement("div"); controls.className = "screen-picker-controls"; controls.append(query, view, prefix);
  const results = document.createElement("div"); results.id = "screenResults"; results.setAttribute("role", "tree"); results.setAttribute("aria-label", t("Screens"));
  const count = document.createElement("p"); count.setAttribute("role", "status");
  const open = document.createElement("button"); open.id = "openScreen"; open.className = "primary"; open.textContent = t("Open");
  let candidate = current, shown = new Set<number>();
  const commit = () => { if (shown.has(candidate)) { modal.element.close(); choose(candidate); } };
  const tree = new ObjectTree(results, path => {
    if (!path.startsWith("/screens/")) return;
    candidate = Number(path.split("/")[2]); tree.select(path); open.disabled = !shown.has(candidate);
  }, () => {});
  // Count the stored hierarchy once per opening, including the screen root.
  // References to other BGIN definitions and animation frames are not new objects.
  const entriesWithCounts = screens.map((node, i) => {
    let objects = 0;
    const pending = [node];
    while (pending.length) {
      const item = pending.pop();
      if (!item || typeof item !== "object") continue;
      objects++;
      for (const group of ["children", "tracks"])
        if (Array.isArray(item[group])) for (const child of item[group]) pending.push(child);
    }
    return { node, i, key: screenPrefix(node.name), objects };
  });
  const update = () => {
    const needle = query.value.trim().toLocaleLowerCase();
    const entries = entriesWithCounts.filter(e =>
      (!needle || `${e.node.name} ${e.node.type}`.toLocaleLowerCase().includes(needle)) &&
      (!prefix.value || e.key === (prefix.value === "__none" ? "" : prefix.value)));
    shown = new Set(entries.map(e => e.i));
    if (!shown.has(candidate) && entries.length) candidate = entries[0].i;
    const rows: TreeRow[] = [];
    const row = (e: typeof entries[number], depth: number) => rows.push({ node: e.node, detail: `${e.node.type} · ${t("Objects")}: ${e.objects.toLocaleString()}`, path: `/screens/${e.i}`, depth, has: false, opened: false });
    if (view.value === "all") entries.forEach(e => row(e, 0));
    else {
      const grouped = new Map<string, typeof entries>();
      entries.forEach(e => { if (!grouped.has(e.key)) grouped.set(e.key, []); grouped.get(e.key)!.push(e); });
      for (const [key, list] of [...grouped].sort(([a], [b]) => a.localeCompare(b))) {
        rows.push({ node: { name: `${key || t("Without prefix")} (${list.length})`, type: "" }, path: `/prefix/${encodeURIComponent(key)}`, depth: 0, has: false, opened: false });
        list.forEach(e => row(e, 1));
      }
    }
    tree.set(rows, `/screens/${candidate}`); results.scrollTop = 0;
    count.textContent = `${entries.length} / ${screens.length}`; open.disabled = !shown.has(candidate);
  };
  query.oninput = update; view.onchange = update; prefix.onchange = update; open.onclick = commit;
  results.ondblclick = commit;
  modal.element.addEventListener("keydown", e => { if (e.key === "Enter" && e.target !== view && e.target !== prefix) { e.preventDefault(); commit(); } });
  modal.element.addEventListener("close", () => tree.dispose(), { once: true });
  modal.body.append(controls, count, results, open); modal.open(); update(); query.focus();
}
