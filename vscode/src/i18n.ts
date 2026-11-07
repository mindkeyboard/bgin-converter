import { russian } from "./translations";
let current = "en";
export const language = () => current;
const reverse = Object.fromEntries(
  Object.entries(russian).map(([en, ru]) => [ru, en]),
);
export function t(text: string) {
  return current === "ru" ? russian[text] || text : reverse[text] || text;
}
const originals = new WeakMap<Node, { source: string; rendered: string }>();
const attributes = new WeakMap<
  Element,
  Map<string, { source: string; rendered: string }>
>();
function translated(text: string) {
  if (current !== "ru") return text;
  if (russian[text]) return russian[text];
  // Dynamic status messages consist of translated captions and untouched data.
  return text.replace(
    /Preview: |Bindings: |Render notes|selected branch|whole screen|without re-rendering|JSON error: /g,
    (word) =>
      russian[word.trim().replace(/:$/, "")]
        ? russian[word.trim().replace(/:$/, "")] +
          (word.endsWith(": ") ? ": " : "")
        : word,
  );
}
function update(root: Node) {
  if (
    root instanceof Element &&
    root.closest(
      ".cm-editor,.tree-surface,#scene,#propertyRows",
    )
  )
    return;
  if (root.nodeType === Node.TEXT_NODE) {
    const text = root.textContent || "",
      old = originals.get(root);
    const source = old?.rendered === text ? old.source : reverse[text] || text;
    const rendered = translated(source);
    if (rendered !== text) root.textContent = rendered;
    originals.set(root, { source, rendered });
  } else {
    if (root instanceof Element) {
      if (["SCRIPT", "STYLE"].includes(root.tagName)) return;
      const values = attributes.get(root) || new Map();
      attributes.set(root, values);
      for (const key of ["title", "placeholder", "aria-label"]) {
        const text = root.getAttribute(key);
        if (text === null) continue;
        const old = values.get(key),
          source = old?.rendered === text ? old.source : reverse[text] || text,
          rendered = translated(source);
        if (rendered !== text) root.setAttribute(key, rendered);
        values.set(key, { source, rendered });
      }
    }
    for (const child of Array.from(root.childNodes)) update(child);
  }
}
const observer = new MutationObserver((records) => {
  for (const record of records) {
    if (record.type === "characterData") update(record.target);
    else if (record.type === "attributes") update(record.target);
    else for (const node of Array.from(record.addedNodes)) update(node);
  }
});
observer.observe(document.body, {
  subtree: true,
  childList: true,
  characterData: true,
  attributes: true,
  attributeFilter: ["title", "placeholder", "aria-label"],
});
export function setLanguage(value: string) {
  current = value === "ru" ? "ru" : "en";
  document.documentElement.lang = current;
  update(document.body);
}
