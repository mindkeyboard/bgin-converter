import { language, t } from "./i18n";

export type ParameterOption = { value: string; label: string; hint: string; token: any };
export type ParameterSpec = {
  type: "bool" | "integer" | "float" | "vector" | "color" | "enum" | "font" | "style" | "sprite" | "text";
  group: string;
  unit?: string;
  min?: number;
  label?: string;
  fields?: string[];
  options?: ParameterOption[];
  help?: { en: string; ru: string };
  noEffect?: boolean;
  readAfter?: string;
};
export type ControlContext = {
  name: string;
  change: (value: unknown) => void;
  suggest: () => string[];
};

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

/** A stored value of another shape stays editable as JSON and is never converted silently. */
export function fits(spec: ParameterSpec, value: any) {
  if (value === undefined) return true;
  if (["bool", "integer", "float"].includes(spec.type)) return finite(value);
  if (spec.type === "vector") return Array.isArray(value) && value.length === spec.fields!.length && value.every(finite);
  if (spec.type === "color") return Array.isArray(value) && value.length === 4 && value.every(finite);
  if (spec.type === "enum" || spec.type === "font")
    return !!value && typeof value === "object" && typeof value.enum === "string" &&
      Object.keys(value).every(key => ["enum", "value", "text"].includes(key));
  return typeof value === "string";
}

export function parameterHelp(spec: ParameterSpec | undefined) {
  if (!spec) return "";
  const described = spec.help?.[language() === "ru" ? "ru" : "en"].replaceAll("`", "");
  const kinds: Record<string, string> = {
    bool: "On or off", integer: "Whole number", float: "Number", vector: "Numbers", color: "Colour",
    enum: "Choice", font: "Font file", style: "Text style name", sprite: "Sprite path", text: "Text",
  };
  const type = [t(kinds[spec.type]), spec.min === undefined ? "" : `≥ ${spec.min}`, spec.unit ? unitText(spec.unit) : ""]
    .filter(Boolean).join(", ");
  return [spec.label && t(spec.label), described, spec.noEffect && t("The game reads this value but does not use it"), t("Type") + ": " + type]
    .filter(Boolean).join("\n\n");
}

const unitText = (unit: string) => unit === "mm" ? t("mm") : unit === "ms" ? t("ms") : unit;
function unitLabel(unit: string | undefined) {
  const element = document.createElement("span");
  element.className = "field-unit";
  element.textContent = unit ? unitText(unit) : "";
  return element;
}

function invalid(control: HTMLElement) {
  control.classList.add("invalid");
  control.title = t("Enter a valid value");
}
function numberInput(spec: ParameterSpec, label: string, value: number | undefined) {
  const input = document.createElement("input");
  input.type = "number";
  input.step = spec.type === "integer" ? "1" : "any";
  if (spec.min !== undefined) input.min = String(spec.min);
  input.value = value === undefined ? "" : String(value);
  input.spellcheck = false;
  input.setAttribute("aria-label", label);
  return input;
}
function accepted(spec: ParameterSpec, text: string) {
  const value = Number(text);
  if (!text.trim() || !Number.isFinite(value)) return false;
  if (spec.min !== undefined && value < spec.min) return false;
  return spec.type !== "integer" || Number.isInteger(value);
}

function choice(items: [string, string][], current: string, label: string, change: (key: string) => void) {
  const select = document.createElement("select");
  select.setAttribute("aria-label", label);
  for (const [key, text] of items) select.add(new Option(text, key));
  select.value = current;
  select.onchange = () => change(select.value);
  return select;
}
function boolControl(value: number | undefined, context: ControlContext) {
  const state = value === undefined ? "" : 0.5 < value ? "1" : "0";
  return choice(
    [["", t("Not set · engine default")], ["1", t("On")], ["0", t("Off")]],
    state,
    context.name,
    key => context.change(key ? Number(key) : undefined),
  );
}
function enumControl(spec: ParameterSpec, value: any, context: ControlContext) {
  const items: [string, string][] = [["", t("Not set · engine default")]];
  const options = spec.options!;
  for (const option of options)
    items.push([option.value, option.hint ? `${option.label} · ${t(option.hint)}` : spec.type === "font" ? t(option.label) : option.label]);
  const known = !value || options.some(option => option.value === value.enum);
  if (!known) items.push([value.enum, value.text || value.enum]);
  return choice(items, value?.enum || "", context.name, key =>
    key === value?.enum ? undefined : context.change(key ? options.find(option => option.value === key)!.token : undefined));
}
function numberControl(spec: ParameterSpec, value: number | undefined, context: ControlContext) {
  const wrapper = document.createElement("div");
  wrapper.className = "field-row";
  const input = numberInput(spec, context.name, value);
  input.placeholder = t("Not set");
  input.onchange = () => {
    if (!input.value.trim()) return context.change(undefined);
    if (accepted(spec, input.value)) context.change(Number(input.value));
    else invalid(input);
  };
  wrapper.append(input);
  if (spec.unit) wrapper.append(unitLabel(spec.unit));
  return wrapper;
}

const SHORT_CAPTIONS: Record<string, string> = { Width: "W", Height: "H", Left: "L", Right: "R" };
function vectorControl(spec: ParameterSpec, value: number[] | undefined, context: ControlContext) {
  const fields = spec.fields!, wide = fields.length > 2;
  const wrapper = document.createElement("div");
  wrapper.className = wide ? "vector-field wide" : "vector-field";
  wrapper.style.setProperty("--fields", String(fields.length));
  const inputs = fields.map((field, i) => {
    const caption = document.createElement("label");
    const name = document.createElement("span");
    name.textContent = t(wide ? field : SHORT_CAPTIONS[field] || field);
    name.title = t(field);
    const input = numberInput(spec, `${context.name}: ${t(field)}`, value?.[i]);
    caption.append(name, input);
    wrapper.append(caption);
    return input;
  });
  const apply = () => {
    if (inputs.every(input => !input.value.trim())) return context.change(undefined);
    const empty = inputs.filter(input => !input.value.trim());
    // A new value is committed once every component has been entered.
    if (empty.length && !value) return;
    if (inputs.every(input => accepted(spec, input.value))) context.change(inputs.map(input => Number(input.value)));
    else inputs.filter(input => !accepted(spec, input.value)).forEach(invalid);
  };
  for (const input of inputs) input.onchange = apply;
  if (spec.unit && !wide) wrapper.append(unitLabel(spec.unit));
  return wrapper;
}

const channel = (value: number) => Math.round(Math.min(1, Math.max(0, value)) * 255).toString(16).padStart(2, "0");
const toHex = (color: number[]) => "#" + color.slice(0, 3).map(channel).join("");
function colorControl(value: number[] | undefined, context: ControlContext) {
  const wrapper = document.createElement("div");
  wrapper.className = "color-field";
  const swatch = document.createElement("input"), hex = document.createElement("input"), alpha = document.createElement("input");
  swatch.type = "color";
  swatch.value = value ? toHex(value) : "#ffffff";
  swatch.classList.toggle("unset", !value);
  swatch.setAttribute("aria-label", `${context.name}: ${t("Colour")}`);
  hex.value = value ? toHex(value) : "";
  hex.placeholder = t("Not set");
  hex.spellcheck = false;
  hex.setAttribute("aria-label", `${context.name}: HEX`);
  alpha.type = "number";
  alpha.min = "0";
  alpha.max = "100";
  alpha.step = "1";
  alpha.value = value ? String(Math.round(value[3] * 100)) : "";
  alpha.title = t("Opacity");
  alpha.setAttribute("aria-label", `${context.name}: ${t("Opacity")}`);
  const fromHex = (text: string) => [1, 3, 5].map(at => Math.round(parseInt(text.slice(at, at + 2), 16) / 255 * 10000) / 10000);
  const opacity = () => alpha.value.trim() ? Number(alpha.value) / 100 : value?.[3] ?? 1;
  swatch.onchange = () => context.change([...fromHex(swatch.value), opacity()]);
  hex.onchange = () => {
    const text = hex.value.trim();
    if (!text) return context.change(undefined);
    if (/^#?[0-9a-f]{6}$/i.test(text)) context.change([...fromHex(text.startsWith("#") ? text : "#" + text), opacity()]);
    else invalid(hex);
  };
  alpha.onchange = () => {
    if (!accepted({ type: "float", group: "", min: 0 }, alpha.value) || Number(alpha.value) > 100) return invalid(alpha);
    context.change([...(value?.slice(0, 3) || [1, 1, 1]), opacity()]);
  };
  wrapper.append(swatch, hex, alpha, unitLabel("%"));
  return wrapper;
}

function textControl(value: string | undefined, context: ControlContext) {
  const input = document.createElement("input");
  input.value = value ?? "";
  input.placeholder = t("Not set · engine default");
  input.spellcheck = false;
  input.setAttribute("aria-label", context.name);
  input.setAttribute("list", "parameterSuggestions");
  input.onfocus = () => {
    document.getElementById("parameterSuggestions")?.replaceChildren(
      ...context.suggest().filter(item => item !== input.value).map(item => new Option(item, item)),
    );
  };
  input.onchange = () => context.change(input.value ? input.value : undefined);
  return input;
}

export function parameterControl(spec: ParameterSpec, value: any, context: ControlContext): HTMLElement {
  if (spec.type === "bool") return boolControl(value, context);
  if (spec.type === "integer" || spec.type === "float") return numberControl(spec, value, context);
  if (spec.type === "vector") return vectorControl(spec, value, context);
  if (spec.type === "color") return colorControl(value, context);
  if (spec.type === "enum" || spec.type === "font") return enumControl(spec, value, context);
  return textControl(value, context);
}

export function jsonControl(value: any, name: string, readOnly: boolean, change: (value: unknown) => void) {
  const input = document.createElement("input");
  input.value = value === undefined ? "" : JSON.stringify(value);
  input.placeholder = t("Not set · engine default");
  input.readOnly = readOnly;
  input.spellcheck = false;
  input.setAttribute("aria-label", name);
  input.onchange = () => {
    if (!input.value.trim()) return change(undefined);
    try {
      change(JSON.parse(input.value));
    } catch {
      invalid(input);
    }
  };
  return input;
}
