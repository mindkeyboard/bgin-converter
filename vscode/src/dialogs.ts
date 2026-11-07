/** Accessible local dialogs; no synchronous browser prompts in the VS Code webview. */
import { t } from "./i18n";
import { TypePicker } from "./typePicker";
export function dialog(title: string, closeLabel = "Close") {
  const element = document.createElement("dialog");
  element.className = "editor-dialog";
  const header = document.createElement("header");
  header.className = "toolbar";
  const heading = document.createElement("strong");
  heading.textContent = title;
  const close = document.createElement("button");
  close.textContent = "×";
  close.setAttribute("aria-label", closeLabel);
  close.onclick = () => element.close();
  header.append(heading, close);
  const body = document.createElement("div");
  body.className = "dialog-body";
  element.append(header, body);
  document.body.append(element);
  element.addEventListener("close", () => element.remove(), { once: true });
  element.addEventListener("click", (e) => {
    if (e.target === element) element.close();
  });
  return { element, body, open: () => element.showModal() };
}

/** Footer of a type choice: the reference of the selected type beside the confirming button. */
export function typeActions(submit: HTMLButtonElement, openDocs?: () => void) {
  const actions = document.createElement("div");
  actions.className = "dialog-actions";
  if (openDocs) {
    const docs = document.createElement("button");
    docs.type = "button";
    docs.id = "typeDocs";
    docs.className = "documentation-button";
    docs.textContent = t("Documentation");
    docs.title = t("Open the reference for the selected type");
    docs.onclick = openDocs;
    actions.append(docs);
  }
  actions.append(submit);
  return actions;
}

export function ask(
  title: string,
  value: string,
  choices?: string[],
  openDocs?: (choice: string) => void,
): Promise<string | undefined> {
  return new Promise((resolve) => {
    const modal = dialog(title),
      form = document.createElement("form");
    form.method = "dialog";
    const picker = choices ? new TypePicker(choices, value, title, openDocs) : undefined;
    if (picker) form.className = "type-picker-form";
    const field = picker?.element || document.createElement("input");
    field.setAttribute("aria-label", title);
    if (field instanceof HTMLInputElement) field.value = value;
    const submit = document.createElement("button");
    submit.textContent = "OK";
    submit.className = "primary";
    submit.type = "submit";
    let result: string | undefined;
    form.onsubmit = () => {
      result = (picker ? picker.value : (field as HTMLInputElement).value).trim();
    };
    modal.element.addEventListener("close", () => resolve(result), {
      once: true,
    });
    form.append(field, typeActions(submit, picker && openDocs && (() => openDocs(picker.value))));
    modal.body.append(form);
    modal.open();
    if (picker) picker.focus(); else field.focus();
    if (field instanceof HTMLInputElement) field.select();
  });
}

export type MenuAction = {
  label: string;
  run: () => void;
  disabled?: boolean;
  shortcut?: string;
  group?: string;
};
export function contextMenu(x: number, y: number, actions: MenuAction[]) {
  document
    .querySelector<HTMLElement>(".context-menu")
    ?.dispatchEvent(new Event("dismiss"));
  const menu = document.createElement("div");
  const listeners = new AbortController();
  const close = () => {
    listeners.abort();
    menu.remove();
  };
  menu.addEventListener("dismiss", close, { once: true });
  menu.className = "context-menu";
  menu.setAttribute("role", "menu");
  let group: string | undefined;
  for (const action of actions) {
    if (group && action.group !== group) {
      const separator = document.createElement("hr");
      separator.setAttribute("role", "separator");
      menu.append(separator);
    }
    group = action.group;
    const button = document.createElement("button");
    button.setAttribute("role", "menuitem");
    button.setAttribute("aria-label", action.label);
    button.disabled = !!action.disabled;
    const name = document.createElement("span"),
      shortcut = document.createElement("small");
    name.textContent = action.label;
    shortcut.textContent = action.shortcut || "";
    button.append(name, shortcut);
    button.onclick = () => {
      close();
      action.run();
    };
    menu.append(button);
  }
  document.body.append(menu);
  menu.style.left =
    Math.max(4, Math.min(x, innerWidth - menu.offsetWidth - 4)) + "px";
  menu.style.top =
    Math.max(4, Math.min(y, innerHeight - menu.offsetHeight - 4)) + "px";
  const dismiss = (e: Event) => {
    if (e instanceof KeyboardEvent && e.key !== "Escape") return;
    if (e instanceof PointerEvent && menu.contains(e.target as Node)) return;
    close();
  };
  document.addEventListener("pointerdown", dismiss, {
    capture: true,
    signal: listeners.signal,
  });
  document.addEventListener("keydown", dismiss, {
    capture: true,
    signal: listeners.signal,
  });
  menu.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
}
