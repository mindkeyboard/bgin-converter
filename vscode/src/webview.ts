import { EditorState } from "@codemirror/state";
import {
  EditorView,
  keymap,
  lineNumbers,
  highlightActiveLine,
  drawSelection,
} from "@codemirror/view";
import { defaultKeymap, indentWithTab } from "@codemirror/commands";
import {
  syntaxHighlighting,
  defaultHighlightStyle,
  foldGutter,
  indentOnInput,
  bracketMatching,
} from "@codemirror/language";
import { json } from "@codemirror/lang-json";
import { parseTree, findNodeAtOffset } from "jsonc-parser";
import { nodeIcon } from "./icons";
import { showTerms, TERMS_VERSION } from "./terms";
import { TypePicker } from "./typePicker";
import { ResourcePanel } from "./resourcePanel";
import { ObjectTree, TreeRow } from "./tree";
import { dialog, ask, contextMenu, typeActions } from "./dialogs";
import { setLanguage, t } from "./i18n";
import { fits, jsonControl, parameterControl, parameterHelp, ParameterSpec } from "./propertyControls";
import { PreviewSettings } from "./previewControls";
import { parseClipboardObject } from "./clipboard";

declare function acquireVsCodeApi(): {
  postMessage: (m: any) => void;
  getState: () => any;
  setState: (s: any) => void;
};
const vscode = acquireVsCodeApi(),
  saved = vscode.getState() || {};
const $ = <T extends HTMLElement = HTMLElement>(id: string) =>
  document.getElementById(id) as T;
let text = "",
  doc: any,
  catalog: any,
  options: any = {},
  selected = saved.selected || "",
  mode = saved.mode || "tree";
let hide = !!saved.hide,
  expandedPreview = !!saved.expandedPreview,
  split = saved.split || 52,
  inspectorSplit = saved.inspectorSplit || 54,
  zoom = saved.zoom || 1,
  fit = saved.fit !== false;
let changing = false,
  editor: EditorView,
  inspected = "",
  editTimer: number;
let renderBusy = false,
  renderRequest = 0,
  previewScreen = -1,
  previewText = "",
  previewWidth = 0,
  previewHeight = 0,
  previewResourceSelection = "",
  previewDirty = true;
let pendingPreview:
  | {
      text: string;
      screen: number;
      resourceSelection: string;
      isResource: boolean;
    }
  | undefined;
let previewIsResource = false,
  jsonAstText = "",
  jsonAst: ReturnType<typeof parseTree>;
let openNodes = new Set<string>(saved.openNodes || []),
  resources: any = {},
  ready = false;
const app = $("app");
app.innerHTML = `
<header class="toolbar">
  <strong>Binary GIN</strong><button id="treeMode">Hierarchy</button><button id="jsonMode">JSON</button>
  <span class="spacer"></span><button id="editorDocs" class="documentation-button" title="Open the editor guide">Editor guide</button><button id="openDocs" class="documentation-button">GIN documentation</button><button id="editorSettings">Editor settings</button><button id="resourceButton">Resources</button><button id="togglePreview" title="Toggle preview">Preview</button><button id="expandPreview" title="Expand preview">⛶</button>
</header>
<div id="banner" role="alert" hidden></div>
<dialog id="resourcePanel" class="editor-dialog" aria-label="Resources"></dialog>
<main id="workspace">
 <section id="editing">
  <div id="hierarchy">
   <div class="toolbar"><select id="screen" aria-label="Screen"></select><button id="newScreen" title="Create a new screen" disabled>New screen…</button><button id="search">Find object…</button><button id="moveUp" title="Move up" aria-label="Move up">↑</button><button id="moveDown" title="Move down" aria-label="Move down">↓</button><span class="spacer"></span><button id="clearSelection">Clear selection</button></div>
   <p id="emptyDocument" hidden>No screens yet. Click New screen to start creating this BGIN file.</p><button id="pasteScreenEmpty" hidden>Paste as screen</button>
   <div id="tree" role="tree" aria-label="Object hierarchy"></div>
   <div id="inspectorDivider" role="separator" tabindex="0" aria-label="Tree and properties size" aria-orientation="horizontal"></div>
   <section id="inspector"><div class="toolbar"><strong id="objectTitle">Properties</strong><span class="spacer"></span><button id="revealObject" title="Expand ancestors and select this object in the tree">Reveal in tree</button><button id="objectDocs" class="documentation-button" title="Open the reference for this object">Documentation</button></div>
    <div class="fields"><label>Name<input id="nodeName"></label><label>Type<select id="nodeType"></select></label></div>
    <div id="propertyRows"></div>
    <datalist id="parameterSuggestions"></datalist>
   </section>
  </div>
  <div id="jsonEditor"></div>
 </section>
 <div id="divider" role="separator" tabindex="0" aria-label="Preview width"></div>
 <section id="preview">
  <div class="toolbar"><strong>Preview</strong><button id="refreshPreview" class="primary" title="Render preview">Refresh</button><button id="cancelPreview" hidden>Stop</button><button id="settingsToggle" title="Preview settings" disabled>Settings</button><button id="fit">Fit</button><button id="zoomOut">−</button><input id="zoom" type="number" min="5" max="800" step="5" aria-label="Zoom"><span>%</span><button id="zoomIn">+</button><button id="prevFrame" title="Previous Movie frame">‹</button><button id="nextFrame" title="Next Movie frame">›</button></div>
  <div id="stage"><div id="scene"></div><div id="empty">Click Refresh to render the preview</div></div>
  <div id="stats"></div><details id="warnings"><summary id="warningCount">Render notes</summary><ul id="warningList"></ul></details>
 </section>
</main>`;

const PARAMETER_GROUPS = ["Layout", "Images", "Text", "Behaviour"];
$("editorDocs").onclick = () => vscode.postMessage({ type: "openEditorGuide" });
$("openDocs").onclick = () => vscode.postMessage({ type: "openDocs" });
$("objectDocs").onclick = () => openObjectDocs(at(selected).type);
$("revealObject").onclick = () => {
  if (!selected || !at(selected)) return;
  mode = "tree";
  expandedPreview = false;
  layout();
  reveal(selected);
};
const resourcePanel = new ResourcePanel($("resourcePanel"), (m) =>
  vscode.postMessage(m),
);
function showNameRequired() {
  if (document.getElementById("documentNameDialog")) return;
  $("workspace").inert = true;
  const modal = dialog(t("Name this BGIN document"));
  modal.element.id = "documentNameDialog";
  modal.element.querySelector("header button")?.remove();
  modal.element.addEventListener("cancel", event => event.preventDefault());
  modal.element.addEventListener("close", () => {
    if ($("workspace").inert) queueMicrotask(showNameRequired);
  });
  const description = document.createElement("p");
  description.textContent = t("This empty draft has no document name. Enter a name to start editing.");
  const form = document.createElement("form"), label = document.createElement("label"), input = document.createElement("input"), submit = document.createElement("button");
  label.textContent = t("Document name");
  input.id = "documentName";
  input.required = true;
  input.autocomplete = "off";
  label.htmlFor = input.id;
  submit.type = "submit";
  submit.className = "primary";
  submit.textContent = t("Start editing");
  submit.disabled = true;
  input.oninput = () => { submit.disabled = !input.value.trim() || new TextEncoder().encode(input.value.trim()).length > 65535; };
  form.onsubmit = event => {
    event.preventDefault();
    if (!submit.disabled) vscode.postMessage({ type: "setDocumentName", name: input.value.trim() });
  };
  form.append(label, input, submit);
  modal.body.append(description, form);
  modal.open();
  input.focus();
}
// Keep screen navigation across document undo/redo without retaining copies of large JSON texts.
const screenViews = new Map<
  string,
  { selected: string; screen: number; opened: string[] }
>();
function screenViewKey() {
  return (
    doc &&
    JSON.stringify([
      doc.name,
      doc.dialect,
      doc.screens?.map((screen: any) => [screen.name, screen.type]),
    ])
  );
}

function persist() {
  const key = screenViewKey();
  if (key) {
    screenViews.delete(key);
    screenViews.set(key, {
      selected,
      screen: options.screen,
      opened: [...openNodes],
    });
    if (screenViews.size > 16)
      screenViews.delete(screenViews.keys().next().value!);
  }
  vscode.setState({
    selected,
    mode,
    hide,
    expandedPreview,
    split,
    inspectorSplit,
    zoom,
    fit,
    options,
    openNodes: [...openNodes],
  });
}
function report(message: string) {
  const banner = $("banner");
  banner.hidden = !message;
  banner.replaceChildren();
  if (message) {
    const span = document.createElement("span");
    span.textContent = message;
    banner.append(span);
    const close = document.createElement("button");
    close.textContent = "×";
    close.onclick = () => (banner.hidden = true);
    banner.append(close);
  }
}
function layout() {
  $("hierarchy").hidden = mode !== "tree";
  $("jsonEditor").hidden = mode !== "json";
  $("treeMode").classList.toggle("active", mode === "tree");
  $("jsonMode").classList.toggle("active", mode === "json");
  $("preview").hidden = hide;
  $("divider").hidden = hide || expandedPreview;
  $("editing").hidden = expandedPreview && !hide;
  $("editing").style.flexBasis = split + "%";
  $("preview").style.flexBasis = 100 - split + "%";
  $("tree").style.flexBasis = inspectorSplit + "%";
  $("inspector").style.flexBasis = 100 - inspectorSplit + "%";
  persist();
  requestAnimationFrame(resizeScene);
}
function extensions(onChange: (v: EditorView) => void) {
  return [
    lineNumbers(),
    drawSelection(),
    highlightActiveLine(),
    foldGutter(),
    indentOnInput(),
    bracketMatching(),
    json(),
    syntaxHighlighting(defaultHighlightStyle),
    keymap.of([
      {
        key: "Mod-z",
        run: () => {
          vscode.postMessage({ type: "undo" });
          return true;
        },
      },
      {
        key: "Mod-Shift-z",
        run: () => {
          vscode.postMessage({ type: "redo" });
          return true;
        },
      },
      {
        key: "Mod-y",
        run: () => {
          vscode.postMessage({ type: "redo" });
          return true;
        },
      },
      indentWithTab,
      ...defaultKeymap,
    ]),
    EditorView.lineWrapping,
    EditorView.theme({
      "&": {
        height: "100%",
        backgroundColor: "var(--vscode-editor-background)",
        color: "var(--vscode-editor-foreground)",
      },
      ".cm-content": {
        fontFamily: "var(--vscode-editor-font-family, monospace)",
        fontSize: "var(--vscode-editor-font-size, 13px)",
      },
      ".cm-gutters": {
        backgroundColor: "var(--vscode-editor-background)",
        color: "var(--vscode-editorLineNumber-foreground)",
        border: "none",
      },
      ".cm-cursor": {
        borderLeftColor: "var(--vscode-editorCursor-foreground)",
      },
      "&.cm-focused .cm-selectionBackground, .cm-selectionBackground": {
        backgroundColor: "var(--vscode-editor-selectionBackground)",
      },
    }),
    EditorView.updateListener.of((u) => {
      if (!changing && (u.docChanged || u.selectionSet)) onChange(u.view);
    }),
  ];
}
editor = new EditorView({
  parent: $("jsonEditor"),
  state: EditorState.create({
    doc: "",
    extensions: extensions((view) => {
      const next = view.state.doc.toString();
      const changed = next !== text;
      if (changed) {
        text = next;
        vscode.postMessage({ type: "edit", text });
        clearTimeout(editTimer);
        editTimer = window.setTimeout(() => {
          parse();
          invalidatePreview();
        }, 180);
      }
      if (!changed && mode === "json" && doc) {
        if (jsonAstText !== text) {
          jsonAst = parseTree(text);
          jsonAstText = text;
        }
        const tree = jsonAst,
          found =
            tree &&
            findNodeAtOffset(tree, view.state.selection.main.head, true);
        let node = found;
        while (node) {
          if (
            node.type === "object" &&
            node.children?.some((c) => c.children?.[0]?.value === "type") &&
            node.children?.some((c) => c.children?.[0]?.value === "name")
          )
            break;
          node = node.parent;
        }
        if (node) {
          const p: string[] = [];
          let n = node;
          while (n.parent) {
            const parent = n.parent;
            if (parent.type === "property") {
              p.unshift(String(parent.children?.[0].value));
              n = parent.parent!;
            } else if (parent.type === "array") {
              p.unshift(String(parent.children!.indexOf(n)));
              n = parent;
            } else n = parent;
          }
          select("/" + p.join("/"), false);
        }
      }
    }),
  }),
});
function syncEditor() {
  if (mode !== "json") return;
  if (editor.state.doc.toString() !== text) {
    changing = true;
    editor.dispatch({
      changes: { from: 0, to: editor.state.doc.length, insert: text },
    });
    changing = false;
  }
}
function parse() {
  try {
    const next = JSON.parse(text);
    if (doc && next.name !== doc.name) {
      openNodes = new Set(
        (next.screens || []).map((_: any, i: number) => `/screens/${i}`),
      );
      selected = "";
      inspected = "";
      options.selected = "";
    }
    doc = next;
    if (!doc || !Array.isArray(doc.screens))
      throw Error("screens must be an array");
    if (typeof doc.name !== "string" || !doc.name.trim()) showNameRequired();
    else {
      $("workspace").inert = false;
      document.querySelector<HTMLDialogElement>("#documentNameDialog")?.close();
    }
    const view = screenViews.get(screenViewKey());
    if (view) {
      selected = view.selected;
      options.screen = view.screen;
      options.selected = selected;
      openNodes = new Set(view.opened);
    }
    if (selected && !at(selected)) {
      selected = "";
      inspected = "";
      options.selected = "";
    }
    populateScreens();
    drawTree();
    if (selected) inspect();
    return true;
  } catch {
    doc = undefined;
    $<HTMLButtonElement>("newScreen").disabled = true;
    $("emptyDocument").hidden = true;
    $("inspector").hidden = true;
    $("tree").textContent = "Fix JSON to continue editing the hierarchy.";
    return false;
  }
}
function commit(next: any) {
  clearTimeout(editTimer);
  text = JSON.stringify(next, null, 2) + "\n";
  syncEditor();
  vscode.postMessage({ type: "edit", text });
  populateScreens();
  drawTree();
  if (selected) inspect();
  persist();
  invalidatePreview();
}
function at(path: string): any {
  return path
    .split("/")
    .slice(1)
    .reduce((v, k) => v?.[k], doc);
}
function reveal(path: string) {
  const screen = Number(path.split("/")[2]);
  if (Number.isInteger(screen)) {
    options.screen = screen;
    $<HTMLSelectElement>("screen").value = String(screen);
  }
  let prefix = path.slice(0, path.lastIndexOf("/"));
  while (prefix.includes("/")) {
    openNodes.add(prefix);
    prefix = prefix.slice(0, prefix.lastIndexOf("/"));
  }
  drawTree();
  select(path);
  objectTree.reveal(path);
}
function select(path: string, updateInspector = true) {
  if (selected === path && (!updateInspector || inspected === path)) return;
  selected = path;
  options.selected = selected;
  if (path) {
    const screen = Number(path.split("/")[2]);
    if (Number.isInteger(screen) && screen !== options.screen) {
      options.screen = screen;
      $<HTMLSelectElement>("screen").value = String(screen);
      drawTree();
    }
  }
  if (mode === "tree") {
    objectTree.select(path);
    if (updateInspector) inspect();
  }
  updateMoveButtons();
  persist();
  applyPreviewSelection();
}
const objectTree = new ObjectTree(
  $("tree"),
  (path) => select(path),
  (path) => {
    if (openNodes.has(path)) openNodes.delete(path);
    else openNodes.add(path);
    drawTree();
    persist();
  },
  showObjectMenu,
);
function isContainer(node: any) {
  return !!node && catalog?.containers?.includes(node.type);
}
function rowsFor(root: any, path: string, needle = "", all = false): TreeRow[] {
  const rows: TreeRow[] = [];
  const matches = new WeakMap<object, boolean>();
  const match = (node: any): boolean => {
    if (matches.has(node)) return matches.get(node)!;
    const yes =
      (node.name + " " + node.type).toLowerCase().includes(needle) ||
      ["children", "tracks"].some((g) => (node[g] || []).some(match));
    matches.set(node, yes);
    return yes;
  };
  const add = (node: any, path: string, depth: number) => {
    if (!node || (needle && !match(node))) return;
    const has = !!(node.children?.length || node.tracks?.length);
    const opened = !!needle || all || openNodes.has(path);
    rows.push({ node, path, depth, has, opened });
    if (opened)
      for (const group of ["children", "tracks"])
        for (const [i, c] of (node[group] || []).entries())
          add(c, `${path}/${group}/${i}`, depth + 1);
  };
  add(root, path, 0);
  return rows;
}

function populateScreens() {
  const select = $<HTMLSelectElement>("screen");
  select.replaceChildren();
  for (const [i, screen] of doc.screens.entries()) {
    const o = new Option(screen.name + " · " + screen.type, String(i));
    select.add(o);
  }
  options.screen = Math.max(
    0,
    Math.min(doc.screens.length - 1, Number(options.screen) || 0),
  );
  select.value = String(options.screen);
  select.disabled = !doc.screens.length;
  $("emptyDocument").hidden = !!doc.screens.length;
  $("pasteScreenEmpty").hidden = !!doc.screens.length;
  $<HTMLButtonElement>("newScreen").disabled = !catalog;
}
function updateMoveButtons() {
  const location = listLocation();
  $<HTMLButtonElement>("moveUp").disabled = !location.list || location.index <= 0;
  $<HTMLButtonElement>("moveDown").disabled = !location.list || location.index >= location.list.length - 1;
}
function drawTree() {
  if (!doc) return;
  const i = Number(options.screen) || 0;
  objectTree.set(rowsFor(doc.screens[i], `/screens/${i}`), selected);
  updateMoveButtons();
  $("inspector").hidden = !selected || !at(selected);
  $("inspectorDivider").hidden = $("inspector").hidden;
}
function searchObjects() {
  if (!doc) return;
  const modal = dialog(t("Find object")),
    input = document.createElement("input"),
    results = document.createElement("div");
  input.id = "searchQuery";
  input.placeholder = t("Name or type…");
  results.id = "searchResults";
  results.setAttribute("role", "tree");
  modal.body.append(input, results);
  const tree = new ObjectTree(
    results,
    (path) => {
      modal.element.close();
      reveal(path);
    },
    () => {},
  );
  modal.element.addEventListener("close", () => tree.dispose(), { once: true });
  const update = () => {
    const needle = input.value.trim().toLowerCase();
    tree.set(
      doc.screens.flatMap((root: any, i: number) =>
        rowsFor(root, `/screens/${i}`, needle, true),
      ),
      "",
    );
  };
  input.oninput = update;
  modal.open();
  update();
  input.focus();
}

function nodeProps(node: any): [string, any, string][] {
  const p = node.properties || {};
  return Array.isArray(p)
    ? p.flatMap((row: any, i: number) =>
        Object.entries(row).map(
          ([k, v]) => [k, v, `properties/${i}/${k}`] as [string, any, string],
        ),
      )
    : Object.entries(p).map(([k, v]) => [k, v, "properties/" + k]);
}
/** Values already used for a name; style and sprite names repeat across a document. */
function propertyValues(name: string) {
  const found = new Set<string>();
  const visit = (node: any) => {
    for (const [key, value] of nodeProps(node))
      if (key === name && typeof value === "string" && value) found.add(value);
    (node.children || []).forEach(visit);
  };
  (doc?.screens || []).forEach(visit);
  return [...found].sort().slice(0, 200);
}
function setProperty(name: string, relative: string, present: boolean, value: unknown) {
  const node = at(selected);
  node.properties ||= {};
  if (present) {
    let target = node;
    const parts = relative.split("/");
    for (const key of parts.slice(0, -1)) target = target[key];
    target[parts.at(-1)!] = value;
  } else {
    // The loader applies parameters in file order and ignores some before their mode.
    const parameters = catalog.parameters?.[node.type] || {};
    const rows = nodeProps(node);
    const found = rows.findIndex(([key]) => parameters[key]?.readAfter === name);
    const position = found < 0 ? rows.length : found;
    if (Array.isArray(node.properties)) node.properties.splice(position, 0, { [name]: value });
    else {
      const entries = Object.entries(node.properties);
      entries.splice(position, 0, [name, value]);
      node.properties = Object.fromEntries(entries);
    }
  }
  commit(doc);
}
function removeProperty(relative: string) {
  const node = at(selected);
  const parts = relative.split("/");
  if (parts.length === 3) node.properties.splice(Number(parts[1]), 1);
  else delete node.properties[parts[1]];
  commit(doc);
}
function inspect() {
  const node = at(selected);
  const same = inspected === selected,
    scroll = $("inspector").scrollTop;
  inspected = selected;
  $("inspector").hidden = !node;
  $("inspectorDivider").hidden = !node;
  if (!node) return;
  $("objectTitle").replaceChildren(
    nodeIcon(node.type),
    document.createTextNode(node.name),
  );
  $<HTMLInputElement>("nodeName").value = node.name;
  const typeField = $<HTMLSelectElement>("nodeType");
  for (const option of typeField.querySelectorAll('[data-preserved-type]')) option.remove();
  if (!catalog.types.includes(node.type)) {
    const option = new Option(node.type, node.type);
    option.dataset.preservedType = "true";
    typeField.add(option);
  }
  typeField.value = node.type;
  const rows = $("propertyRows");
  rows.replaceChildren();
  const existing = nodeProps(node);
  const allowed: string[] = catalog.schemas?.[node.type] || [];
  const slots: [string, any, string][] = allowed.flatMap((name) => {
    const found = existing.filter((row) => row[0] === name);
    return found.length
      ? found
      : [[name, undefined, "properties/" + name] as [string, any, string]];
  });
  const groupOf = (name: string) => PARAMETER_GROUPS.indexOf(catalog.parameters?.[node.type]?.[name]?.group);
  slots.sort((a, b) => groupOf(a[0]) - groupOf(b[0]));
  slots.push(...existing.filter((row) => !allowed.includes(row[0])));
  let heading = "";
  for (const [name, value, relative] of slots) {
    const spec: ParameterSpec | undefined = catalog.parameters?.[node.type]?.[name];
    const editable = allowed.includes(name);
    const change = (next: unknown) => {
      if (editable && next !== undefined) setProperty(name, relative, value !== undefined, next);
      else if (editable && value !== undefined) removeProperty(relative);
    };
    const control = spec && editable && fits(spec, value)
      ? parameterControl(spec, value, { name, change, suggest: () => propertyValues(name) })
      : jsonControl(value, name, !editable, change);
    const row = document.createElement("div");
    row.className = "property";
    row.classList.toggle("preserved-property", !editable);
    row.classList.toggle("stacked", control.classList.contains("wide"));
    row.classList.toggle("no-effect", !!spec?.noEffect);
    const title = document.createElement("span");
    title.textContent = name;
    title.title = parameterHelp(spec);
    if (control.classList.contains("wide") && spec?.unit) {
      const unit = document.createElement("small");
      unit.textContent = spec.unit === "mm" ? t("mm") : spec.unit;
      title.append(" ", unit);
    }
    row.append(title, control);
    const group = editable ? spec?.group || "Behaviour" : "Not read by the game";
    if (group !== heading) {
      heading = group;
      const label = document.createElement("h4");
      label.className = "property-group";
      label.textContent = t(group);
      rows.append(label);
    }
    rows.append(row);
  }
  layout();
  $("inspector").scrollTop = same ? scroll : 0;
}

function move(delta: number) {
  const parts = selected.split("/"),
    i = Number(parts.pop()),
    list = at(parts.join("/"));
  if (!Array.isArray(list) || i + delta < 0 || i + delta >= list.length) return;
  const parent = parts.join("/"),
    from = parent + "/" + i,
    to = parent + "/" + (i + delta);
  openNodes = new Set(
    [...openNodes].map((p) =>
      p === from || p.startsWith(from + "/")
        ? to + p.slice(from.length)
        : p === to || p.startsWith(to + "/")
          ? from + p.slice(to.length)
          : p,
    ),
  );
  [list[i], list[i + delta]] = [list[i + delta], list[i]];
  selected = parts.join("/") + "/" + (i + delta);
  options.selected = selected;
  if (parent === "/screens") options.screen = i + delta;
  commit(doc);
}
$("treeMode").onclick = () => {
  clearTimeout(editTimer);
  mode = "tree";
  parse();
  layout();
};
$("jsonMode").onclick = () => {
  mode = "json";
  syncEditor();
  layout();
  editor.focus();
};
$("screen").onchange = () => {
  options.screen = Number($<HTMLSelectElement>("screen").value);
  selected = "";
  options.selected = "";
  drawTree();
  persist();
  invalidatePreview();
};
$("search").onclick = searchObjects;
$("moveUp").onclick = () => move(-1);
$("moveDown").onclick = () => move(1);
$("clearSelection").onclick = () => {
  selected = "";
  inspected = "";
  options.selected = "";
  drawTree();
  persist();
  applyPreviewSelection();
};
$("nodeName").onchange = () => {
  if (at(selected)) {
    at(selected).name = $<HTMLInputElement>("nodeName").value;
    commit(doc);
  }
};
$("nodeType").onchange = () => {
  const node = at(selected),
    type = $<HTMLSelectElement>("nodeType").value;
  if (node && !(node.children?.length && !isContainer({ type }))) {
    node.type = type;
    commit(doc);
  } else if (node) {
    $<HTMLSelectElement>("nodeType").value = node.type;
    report(t("A container with children cannot become a leaf object"));
  }
};

function listLocation() {
  const parts = selected.split("/"),
    index = Number(parts.pop()),
    parent = parts.join("/");
  const list = at(parent);
  return { index, parent, list: Array.isArray(list) ? list : undefined };
}
function shiftPaths(parent: string, index: number, delta: number) {
  const prefix = parent + "/";
  const remap = (path: string) => {
    if (!path.startsWith(prefix)) return path;
    const tail = path.slice(prefix.length),
      slash = tail.indexOf("/"),
      number = Number(slash < 0 ? tail : tail.slice(0, slash));
    if (number < index) return path;
    if (delta < 0 && number === index) return "";
    return prefix + (number + delta) + (slash < 0 ? "" : tail.slice(slash));
  };
  openNodes = new Set([...openNodes].map(remap).filter(Boolean));
}
function uniqueName(list: any[], name: string) {
  if (!list.some((n) => n.name === name)) return name;
  let i = 2;
  while (list.some((n) => n.name === name + "_" + i)) i++;
  return name + "_" + i;
}
function documentDialect() {
  return (
    doc.dialect ||
    ({ sprites: "sprites", widgets: "templates" } as Record<string, string>)[
      String(doc.name || "").toLowerCase()
    ] ||
    "ui"
  );
}
async function newScreen() {
  if (!doc || !catalog) return;
  const source = doc;
  const modal = dialog(t("New screen")),
    form = document.createElement("form");
  modal.element.id = "newScreenDialog";
  form.method = "dialog";
  const name = document.createElement("input"),
    rootType = new TypePicker([], "", t("Root type"), openObjectDocs),
    kind = document.createElement("select"),
    note = document.createElement("p");
  const label = (title: string, field: HTMLElement) => {
    const wrapper = document.createElement("div");
    const caption = document.createElement("span");
    caption.textContent = t(title);
    wrapper.append(caption);
    field.setAttribute("aria-label", t(title));
    wrapper.append(field);
    return wrapper;
  };
  name.id = "newScreenName";
  name.required = true;
  name.value = uniqueName(doc.screens, "new_screen");
  rootType.element.id = "newScreenType";
  kind.id = "newDocumentKind";
  for (const [value, title] of [
    ["ui", "Interface screens"],
    ["sprites", "Sprite library"],
    ["templates", "Widget templates"],
  ])
    kind.add(new Option(t(title), value));
  kind.value = documentDialect();
  kind.disabled = !!doc.screens.length;
  const fillTypes = () => {
    const types: string[] =
      catalog.creation.screens[kind.value];
    const preferred = types.includes("StackContainer")
      ? "StackContainer"
      : types[0];
    rootType.setTypes(types, preferred);
  };
  kind.onchange = fillTypes;
  fillTypes();
  note.setAttribute("role", "alert");
  const create = document.createElement("button");
  create.type = "submit";
  create.className = "primary";
  create.textContent = t("Create");
  form.append(label("Screen name", name));
  if (!doc.screens.length) form.append(label("Document kind", kind));
  form.append(label("Root type", rootType.element), note, typeActions(create, () => openObjectDocs(rootType.value)));
  form.onsubmit = (event) => {
    event.preventDefault();
    if (doc !== source) {
      modal.element.close();
      return;
    }
    const value = name.value.trim();
    if (!value || doc.screens.some((screen: any) => screen.name === value)) {
      note.textContent = t("Enter a unique, nonempty screen name.");
      name.focus();
      return;
    }
    const node = {
      type: rootType.value,
      name: value,
      properties: {},
      ...(catalog.containers.includes(rootType.value) || rootType.value === "Sprite" ? { children: [] } : {}),
    };
    if (!doc.screens.length) doc.dialect = kind.value;
    doc.screens.push(node);
    options.screen = doc.screens.length - 1;
    selected = `/screens/${options.screen}`;
    options.selected = selected;
    openNodes.add(selected);
    modal.element.close();
    commit(doc);
    objectTree.reveal(selected);
  };
  modal.body.append(form);
  modal.open();
  name.focus();
  name.select();
}
async function renameObject() {
  const node = at(selected);
  if (!node) return;
  const name = await ask(t("Rename object"), node.name);
  if (name) {
    node.name = name;
    commit(doc);
  }
}
function removeObject() {
  const { index, parent, list } = listLocation();
  if (!list) return;
  shiftPaths(parent, index, -1);
  list.splice(index, 1);
  selected = list.length
    ? `${parent}/${Math.min(index, list.length - 1)}`
    : parent === "/screens" ? "" : parent.replace(/\/(children|tracks)$/, "");
  options.selected = selected;
  commit(doc);
}
function duplicateObject() {
  const { index, parent, list } = listLocation();
  if (!list) return;
  const copy = structuredClone(list[index]);
  copy.name = uniqueName(list, copy.name + "_copy");
  shiftPaths(parent, index + 1, 1);
  list.splice(index + 1, 0, copy);
  selected = `${parent}/${index + 1}`;
  if (parent === "/screens") options.screen = index + 1;
  options.selected = selected;
  commit(doc);
}
function openObjectDocs(type: string) {
  vscode.postMessage({ type: "openDocs", target: catalog.documentation?.[type] });
}
async function newObject() {
  const parent = at(selected);
  if (!isContainer(parent)) return;
  const type = await ask(
    t("New child object"),
    "StackContainer",
    catalog.creation.objects,
    openObjectDocs,
  );
  if (!type) return;
  parent.children ||= [];
  const node: any = {
    type,
    name: uniqueName(parent.children, "new_object"),
    properties: {},
  };
  if (isContainer(node)) node.children = [];
  const path = selected;
  parent.children.push(node);
  openNodes.add(path);
  selected = path + "/children/" + (parent.children.length - 1);
  options.selected = selected;
  commit(doc);
  objectTree.reveal(selected);
}
async function changeType() {
  const node = at(selected);
  if (!node) return;
  const type = await ask(
    t("Change object type"),
    node.type,
    catalog.types.filter((kind: string) => {
      if (
        ["Sprite", "Module", "SpriteMovie", "MovieModule"].includes(node.type)
      )
        return kind === node.type;
      return (
        ![
          "Sprite",
          "Module",
          "SpriteMovie",
          "MovieModule",
          "TextStyle",
        ].includes(kind) &&
        (!node.children?.length || isContainer({ type: kind }))
      );
    }),
    openObjectDocs,
  );
  if (type) {
    node.type = type;
    commit(doc);
  }
}
function copyObject(cut = false) {
  if (at(selected))
    vscode.postMessage({
      type: "clipboardWrite",
      text: JSON.stringify(at(selected), null, 2),
      cutPath: cut ? selected : undefined,
    });
}
function pasteScreen() {
  vscode.postMessage({ type: "clipboardRead", target: "/screens" });
}
function pasteObject() {
  if (isContainer(at(selected)))
    vscode.postMessage({ type: "clipboardRead", target: selected });
}
function acceptPaste(raw: string, path: string) {
  try {
    const node = parseClipboardObject(raw),
      parent = at(path);
    const asScreen = path === "/screens";
    if (!asScreen && !isContainer(parent))
      throw Error(t("Select a container to paste into"));
    let count = 0;
    const check = (n: any, depth = 0) => {
      if (
        ++count > 50000 ||
        depth > 100 ||
        !n ||
        (!catalog.types.includes(n.type) && !(doc.format === "legacy" && typeof n.type === "string" && n.type.length > 0)) ||
        typeof n.name !== "string" ||
        !n.name ||
        typeof (n.properties || {}) !== "object"
      )
        throw Error(t("Clipboard must contain a valid BGIN object JSON"));
      for (const group of ["children", "tracks"])
        if (n[group]) {
          if (!Array.isArray(n[group])) throw Error(t("Invalid child list"));
          for (const child of n[group]) check(child, depth + 1);
        }
      if (n.children?.length && !isContainer(n) && n.type !== "Sprite")
        throw Error(t("This object type cannot contain children"));
    };
    check(node);
    if (asScreen) {
      const valid = catalog.creation.screens[documentDialect()].includes(node.type);
      if (!valid) throw Error(t("Choose a compatible screen root type"));
      node.name = uniqueName(doc.screens, node.name);
      doc.screens.push(node);
      options.screen = doc.screens.length - 1;
      selected = `/screens/${options.screen}`;
      options.selected = selected;
      openNodes.add(selected);
      commit(doc);
      objectTree.reveal(selected);
      return;
    }
    parent.children ||= [];
    node.name = uniqueName(parent.children, node.name);
    parent.children.push(node);
    openNodes.add(path);
    selected = path + "/children/" + (parent.children.length - 1);
    options.selected = selected;
    commit(doc);
    objectTree.reveal(selected);
  } catch (e) {
    report(e instanceof Error ? t(e.message) : String(e));
  }
}
function expandTree(expand: boolean) {
  const i = Number(options.screen) || 0;
  const root = `/screens/${i}`;
  for (const row of rowsFor(doc.screens[i], root, "", true)) {
    if (expand && row.has) openNodes.add(row.path);
    else openNodes.delete(row.path);
  }
  drawTree();
  persist();
}
function showObjectMenu(path: string, x: number, y: number) {
  select(path);
  const container = isContainer(at(path));
  const location = listLocation();
  contextMenu(x, y, [
    { group: "create", label: t("New child object…"), run: newObject, disabled: !container },
    { group: "create", label: t("New screen…"), run: newScreen },
    { group: "edit", label: t("Rename…"), run: renameObject, shortcut: "F2" },
    { group: "edit", label: t("Change type…"), run: changeType },
    { group: "clipboard", label: t("Cut"), run: () => copyObject(true), shortcut: "Ctrl+X" },
    { group: "clipboard", label: t("Copy JSON"), run: () => copyObject(), shortcut: "Ctrl+C" },
    { group: "clipboard", label: t("Paste into container"), run: pasteObject, disabled: !container, shortcut: "Ctrl+V" },
    { group: "clipboard", label: t("Paste as screen"), run: pasteScreen },
    { group: "clipboard", label: t("Duplicate"), run: duplicateObject, shortcut: "Ctrl+D" },
    { group: "move", label: t("Move up"), run: () => move(-1), disabled: location.index <= 0 },
    { group: "move", label: t("Move down"), run: () => move(1), disabled: location.index >= (location.list?.length || 0) - 1 },
    { group: "tree", label: t("Expand all"), run: () => expandTree(true) },
    { group: "tree", label: t("Collapse all"), run: () => expandTree(false) },
    { group: "delete", label: t("Delete"), run: removeObject, shortcut: "Delete" },
  ]);
}
$("tree").addEventListener("keydown", (e) => {
  if (!selected) return;
  if (e.key === "F2") {
    e.preventDefault();
    void renameObject();
  }
  if (e.key === "Delete") {
    e.preventDefault();
    removeObject();
  }
  if (
    (e.ctrlKey || e.metaKey) &&
    ["c", "x", "v", "d"].includes(e.key.toLowerCase())
  ) {
    e.preventDefault();
    const key = e.key.toLowerCase();
    if (key === "c" || key === "x") copyObject(key === "x");
    if (key === "v") e.shiftKey ? pasteScreen() : pasteObject();
    if (key === "d") duplicateObject();
  }
});
$("inspectorDivider").onpointerdown = (e) => {
  e.preventDefault();
  const divider = $("inspectorDivider");
  const startY = e.clientY, startSplit = inspectorSplit;
  const available = $("tree").clientHeight + $("inspector").clientHeight;
  divider.setPointerCapture(e.pointerId);
  divider.onpointermove = (event) => {
    inspectorSplit = Math.max(
      15,
      Math.min(85, startSplit + (event.clientY - startY) / Math.max(1, available) * 100),
    );
    layout();
  };
  divider.onpointerup = () => {
    divider.onpointermove = null;
    if (divider.hasPointerCapture(e.pointerId)) divider.releasePointerCapture(e.pointerId);
    persist();
  };
  divider.onpointercancel = divider.onlostpointercapture = () => { divider.onpointermove = null; };
};
$("inspectorDivider").onkeydown = (e) => {
  if (["ArrowUp", "ArrowDown"].includes(e.key)) {
    e.preventDefault();
    inspectorSplit = Math.max(
      15,
      Math.min(85, inspectorSplit + (e.key === "ArrowUp" ? -3 : 3)),
    );
    layout();
  }
};
$("editorSettings").onclick = () => {
  const modal = dialog(t("Editor settings"));
  const label = document.createElement("label"), language = document.createElement("select");
  label.textContent = t("Interface language");
  language.id = "interfaceLanguage";
  language.add(new Option("English", "en"));
  language.add(new Option("Русский", "ru"));
  language.value = document.documentElement.lang;
  language.onchange = () => vscode.postMessage({ type: "setLanguage", language: language.value });
  label.append(language);
  const terms = document.createElement("button");
  terms.textContent = t("Terms of use");
  terms.onclick = () => showTerms();
  modal.body.append(label, terms);
  modal.open();
};
$("resourceButton").onclick = () => resourcePanel.toggle();
$("newScreen").onclick = newScreen;
$("pasteScreenEmpty").onclick = pasteScreen;
$("togglePreview").onclick = () => {
  hide = !hide;
  if (hide) cancelPreview();
  layout();
};
$("expandPreview").onclick = () => {
  hide = false;
  expandedPreview = !expandedPreview;
  layout();
};
$("divider").onpointerdown = (e) => {
  const d = $("divider");
  d.setPointerCapture(e.pointerId);
  d.onpointermove = (event) => {
    const box = $("workspace").getBoundingClientRect();
    split = Math.max(
      20,
      Math.min(80, ((event.clientX - box.left) / box.width) * 100),
    );
    layout();
  };
  d.onpointerup = () => {
    d.onpointermove = null;
    persist();
  };
};
$("divider").onkeydown = (e) => {
  if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
    split = Math.max(
      20,
      Math.min(80, split + (e.key === "ArrowLeft" ? -2 : 2)),
    );
    layout();
  }
};

const previewSettings = new PreviewSettings(
  () => options,
  (keys) => {
    persist();
    if (keys.length === 1 && keys[0] === "selectionOnly")
      return applyPreviewSelection();
    else invalidatePreview();
  },
  () => {
    options = { ...catalog.defaults, screen: options.screen, selected };
    invalidatePreview();
  },
);
$("settingsToggle").onclick = () => previewSettings.open();
function setRenderBusy(busy: boolean) {
  renderBusy = busy;
  $<HTMLButtonElement>("refreshPreview").disabled = busy || !ready;
  $("cancelPreview").hidden = !busy;
  $("refreshPreview").textContent = busy ? "Rendering…" : "Refresh";
}
function cancelPreview() {
  if (!renderBusy) return;
  ++renderRequest;
  pendingPreview = undefined;
  vscode.postMessage({ type: "cancelRender" });
  setRenderBusy(false);
}
function invalidatePreview() {
  previewDirty = true;
  cancelPreview();
  $("stats").textContent =
    previewScreen < 0
      ? "Rendering starts manually"
      : "Preview is out of date · click Refresh";
  persist();
}
function applyPreviewSelection() {
  if (
    renderBusy &&
    pendingPreview &&
    !pendingPreview.isResource &&
    pendingPreview.text === text &&
    pendingPreview.screen === options.screen
  )
    return false;
  if (
    previewText !== text ||
    previewScreen !== options.screen ||
    (previewIsResource && previewResourceSelection !== selected)
  ) {
    invalidatePreview();
    return false;
  }
  for (const group of Array.from(
    $("scene").querySelectorAll<SVGElement>("g[data-path]"),
  )) {
    const path = group.getAttribute("data-path") || "";
    group.style.display =
      options.selectionOnly &&
      selected &&
      path !== selected &&
      !path.startsWith(selected + "/")
        ? "none"
        : "";
  }
  if (!previewDirty)
    $("stats").textContent =
      `${previewWidth} × ${previewHeight} · ${selected && options.selectionOnly ? "selected branch" : "whole screen"} · without re-rendering`;
  return true;
}
function requestPreview() {
  if (!ready || renderBusy) return;
  if (!doc) {
    report("Fix JSON before refreshing the preview");
    return;
  }
  if (!doc.screens.length) {
    report(
      t("Create a screen with New screen before rendering this BGIN file."),
    );
    return;
  }
  hide = false;
  layout();
  options.selected = selected;
  const requestId = ++renderRequest;
  setRenderBusy(true);
  $("stats").textContent =
    "Rendering… You can keep editing or stop the calculation.";
  pendingPreview = {
    text,
    screen: options.screen,
    resourceSelection: selected,
    isResource: doc.screens[options.screen]?.type === "Sprite",
  };
  vscode.postMessage({
    type: "render",
    requestId,
    options: { ...options, selectionOnly: false },
  });
}
$("refreshPreview").onclick = requestPreview;
$("cancelPreview").onclick = () => {
  cancelPreview();
  invalidatePreview();
};
function resizeScene() {
  const scene = $("scene"),
    stage = $("stage");
  const width = previewWidth || options.width,
    height = previewHeight || options.height;
  if (!width || !height) return;
  const factor = fit
    ? Math.min(
        Math.max(1, stage.clientWidth - 32) / width,
        Math.max(1, stage.clientHeight - 32) / height,
      )
    : zoom;
  scene.style.width = width * factor + "px";
  scene.style.height = height * factor + "px";
  $<HTMLInputElement>("zoom").value = String(Math.round(factor * 100));
}
function changeZoom(next: number) {
  fit = false;
  zoom = Math.max(0.05, Math.min(8, next));
  resizeScene();
  persist();
}
$("fit").onclick = () => {
  fit = true;
  resizeScene();
  persist();
};
$("zoomOut").onclick = () => changeZoom(zoom / 1.2);
$("zoomIn").onclick = () => changeZoom(zoom * 1.2);
$("zoom").onchange = () =>
  changeZoom(Number($<HTMLInputElement>("zoom").value) / 100);
new ResizeObserver(resizeScene).observe($("stage"));
$("stage").addEventListener(
  "wheel",
  (e) => {
    if (e.ctrlKey) {
      e.preventDefault();
      changeZoom(zoom * (e.deltaY > 0 ? 0.9 : 1.1));
    }
  },
  { passive: false },
);
$("scene").onclick = (e) => {
  const node = (e.target as Element).closest("[data-path]");
  select(node?.getAttribute("data-path") || "");
};
for (const [id, step] of [
  ["prevFrame", -1],
  ["nextFrame", 1],
] as const)
  $(id).onclick = () => {
    options.frame = Math.max(
      0,
      Math.min(1000000, Number(options.frame) + step),
    );
    const field = $<HTMLInputElement>("option-frame");
    if (field) field.value = String(options.frame);
    invalidatePreview();
  };
window.addEventListener("message", (event) => {
  const m = event.data;
  resourcePanel.message(m);
  if (m.type === "termsRequired") {
    setLanguage(m.uiLanguage || "en");
    const accept = () => vscode.postMessage({ type: "acceptTerms", version: TERMS_VERSION });
    const dismissed = () => vscode.postMessage({ type: "firstTermsDismissed" });
    if (!document.getElementById("termsDialog")) showTerms(accept, dismissed);
    $("banner").hidden = false;
    $("banner").replaceChildren();
    const review = document.createElement("button");
    review.textContent = t("Review terms to open this file");
    review.onclick = () => showTerms(accept, dismissed);
    $("banner").append(review);
    return;
  }
  if (m.type === "termsAccepted") {
    report("");
    vscode.postMessage({ type: "ready" });
    return;
  }
  if (m.type === "nameRequired") {
    setLanguage(m.uiLanguage || "en");
    showNameRequired();
    return;
  }
  if (m.type === "nameAccepted") {
    $("workspace").inert = false;
    document.querySelector<HTMLDialogElement>("#documentNameDialog")?.close();
    if (!ready) vscode.postMessage({ type: "ready" });
    return;
  }
  if (m.type === "init") {
    $("workspace").inert = false;
    document.querySelector<HTMLDialogElement>("#documentNameDialog")?.close();
    text = m.text;
    catalog = m.catalog;
    resources = m.resources;
    resourcePanel.update(m.resourceSettings || m.resources);
    options = { ...catalog.defaults, ...m.defaults, ...saved.options };
    selected = saved.selected || "";
    options.selected = selected;
    const typeSelect = $<HTMLSelectElement>("nodeType");
    typeSelect.replaceChildren();
    for (const kind of catalog.types) typeSelect.add(new Option(kind, kind));
    if (!saved.openNodes) openNodes.add(`/screens/${options.screen || 0}`);
    setLanguage(m.uiLanguage || "en");
    syncEditor();
    parse();
    previewSettings.refresh();
    ready = true;
    $<HTMLButtonElement>("settingsToggle").disabled = false;
    layout();
    invalidatePreview();
  }
  if (m.type === "document") {
    if (!ready) { text = m.text; return; }
    if (m.text !== text) {
      clearTimeout(editTimer);
      text = m.text;
      syncEditor();
      parse();
      invalidatePreview();
    }
  }
  if (m.type === "clipboardRead") acceptPaste(m.text, m.target);
  if (
    m.type === "clipboardWritten" &&
    m.cutPath &&
    m.cutPath === selected &&
    m.text === JSON.stringify(at(selected), null, 2)
  )
    removeObject();
  if (m.type === "config") {
    setLanguage(m.uiLanguage || "en");
    resources = m.resources;
    resourcePanel.update(m.resourceSettings || m.resources);
    if (ready) {
      if (selected) inspect();
      previewSettings.refresh();
      invalidatePreview();
    }
  }
  if (m.type === "syntax") {
    if (m.errors.length) {
      report("JSON error: " + m.errors[0]);
      $("stats").textContent = "Preview of the last valid version";
    } else report("");
  }
  if (m.type === "rendered" && m.requestId === renderRequest) {
    setRenderBusy(false);
    previewText = pendingPreview?.text || "";
    previewScreen = pendingPreview?.screen ?? -1;
    previewResourceSelection = pendingPreview?.resourceSelection || "";
    previewIsResource = !!pendingPreview?.isResource;
    previewWidth = m.width;
    previewHeight = m.height;
    pendingPreview = undefined;
    previewDirty = false;
    const parsed = new DOMParser().parseFromString(m.svg, "image/svg+xml");
    const svg = parsed.documentElement;
    // Only the local renderer supplies markup. Reject executable/foreign content defensively.
    for (const el of Array.from(svg.querySelectorAll("script,foreignObject")))
      el.remove();
    for (const el of [svg, ...Array.from(svg.querySelectorAll("*"))])
      for (const a of Array.from(el.attributes))
        if (a.name.startsWith("on")) el.removeAttribute(a.name);
    $("scene").replaceChildren(document.importNode(svg, true));
    $("empty").hidden = true;
    resizeScene();
    $("stats").textContent =
      `${m.width} × ${m.height} · ${m.geometry.length} objects · ${selected && options.selectionOnly ? "selected branch" : "whole screen"}`;
    applyPreviewSelection();
    const messages = [
      ...(m.errors || []).map((e: any) => e.message),
      ...m.warnings,
    ];
    $("warningCount").textContent = `Render notes (${messages.length})`;
    $("warningList").replaceChildren();
    for (const message of messages) {
      const li = document.createElement("li");
      li.textContent = message;
      $("warningList").append(li);
    }
  }
  if (
    (m.type === "renderCancelled" || m.type === "renderError") &&
    m.requestId === renderRequest
  ) {
    setRenderBusy(false);
    pendingPreview = undefined;
    invalidatePreview();
    if (m.type === "renderError") report(m.message);
  }
  if (m.type === "error") {
    report(m.message);
    $("stats").textContent = "Preview was not updated";
  }
  if (m.type === "command") {
    if (m.command === "refreshPreview") requestPreview();
    if (m.command === "togglePreview") $("togglePreview").click();
    if (m.command === "expandPreview") $("expandPreview").click();
  }
});
vscode.postMessage({ type: "ready" });
