import { dialog } from "./dialogs";

type Options = Record<string, any>;
type Field = {
  key: string;
  label: string;
  description?: string;
  type?: "number" | "color" | "select";
  range?: [number, number, number];
  choices?: string[];
};

const groups: { title: string; checks?: boolean; fields: Field[] }[] = [
  {
    title: "Canvas",
    fields: [
      { key: "width", label: "Width", range: [16, 8192, 1] },
      { key: "height", label: "Height", range: [16, 8192, 1] },
      { key: "pixelsPerMm", label: "Pixels per mm", range: [0.01, 100, 0.1] },
      { key: "background", label: "Background", type: "color" },
      { key: "gridSize", label: "Grid size", range: [1, 1024, 1] },
      { key: "opacity", label: "Opacity", range: [0, 1, 0.05] },
    ],
  },
  {
    title: "Simulated state",
    fields: [
      { key: "frame", label: "Movie frame", range: [0, 1000000, 1] },
      {
        key: "state",
        label: "State",
        type: "select",
        choices: ["normal", "pressed", "toggled", "disabled"],
      },
      { key: "progress", label: "Progress", range: [0, 1, 0.05] },
      { key: "page", label: "Page", range: [0, 10000, 1] },
      { key: "scrollX", label: "Scroll X", range: [-100000, 100000, 10] },
      { key: "scrollY", label: "Scroll Y", range: [-100000, 100000, 10] },
      { key: "fontScale", label: "Text scale", range: [0.1, 10, 0.1] },
      {
        key: "language",
        label: "Font language",
        type: "select",
        choices: [
          "",
          "RU",
          "AR",
          "ID",
          "JA",
          "KO",
          "TH",
          "TR",
          "ZH",
          "ZH_HANT",
        ],
      },
    ],
  },
  {
    title: "Content and layout",
    checks: true,
    fields: [
      {
        key: "selectionOnly",
        label: "Show only the selected branch",
        description:
          "Keep the parent layout and hide other branches. Clearing selection shows the whole screen. Updates immediately.",
      },
      {
        key: "sprites",
        label: "Show widget sprites and Movie",
        description:
          "Draw sprite references used by interface objects. The sprite atlas document preview is separate.",
      },
      {
        key: "text",
        label: "Show text",
        description:
          "Draw approximate text for supported interface objects. Text still contributes to layout when hidden.",
      },
      {
        key: "interpolate",
        label: "Interpolate Movie keyframes",
        description:
          "Interpolate supported animation tracks between their keyframes at the chosen Movie frame.",
      },
      {
        key: "alpha",
        label: "Use external alpha masks",
        description:
          "Apply a companion __alpha texture when present. Embedded texture transparency is kept.",
      },
      {
        key: "smooth",
        label: "Smooth texture scaling",
        description:
          "Use browser image smoothing. Turn off to show pixelated texture scaling.",
      },
      {
        key: "clipping",
        label: "Apply container clipping",
        description:
          "Clip children only where the container has ClipRender enabled.",
      },
      {
        key: "rtl",
        label: "Use right-to-left layout",
        description:
          "Use RTL rules on objects that enable them. This does not flip the entire image or its textures.",
      },
      {
        key: "showHidden",
        label: "Show hidden objects",
        description:
          "Include objects marked invisible and draw them at reduced opacity.",
      },
    ],
  },
  {
    title: "Layout guides",
    checks: true,
    fields: [
      {
        key: "bounds",
        label: "Show object bounds",
        description: "Outline the calculated rectangle of each object.",
      },
      {
        key: "names",
        label: "Show object names",
        description: "Draw the object name beside its calculated rectangle.",
      },
      {
        key: "sizes",
        label: "Show object sizes",
        description: "Draw the calculated width and height in pixels.",
      },
      {
        key: "margins",
        label: "Show margins",
        description: "Outline the inner rectangle for objects with Margins.",
      },
      {
        key: "grid",
        label: "Show grid",
        description: "Draw a screen grid using the configured Grid size.",
      },
      {
        key: "checkerboard",
        label: "Show checkerboard background",
        description: "Draw a checker pattern over the chosen background color.",
      },
      {
        key: "debugFill",
        label: "Fill object bounds",
        description:
          "Tint calculated object rectangles to make their occupied areas visible.",
      },
    ],
  },
];

/** One control owns its label and description; no neighboring checkbox ambiguity. */
export class PreviewSettings {
  private modal?: ReturnType<typeof dialog>;
  private status?: HTMLElement;

  constructor(
    private options: () => Options,
    private changed: (keys: string[]) => boolean | void,
    private reset: () => void,
  ) {}

  open() {
    if (this.modal?.element.open) return;
    this.modal = dialog("Preview settings");
    this.modal.element.id = "settings";
    this.modal.element.setAttribute("aria-label", "Preview settings");
    this.modal.element.addEventListener("close", () => {
      this.modal = undefined;
    });
    this.refresh();
    this.modal.open();
  }

  refresh() {
    if (!this.modal) return;
    const body = this.modal.body;
    body.replaceChildren();
    const note = document.createElement("p");
    note.className = "settings-note";
    note.textContent =
      "Changes are saved immediately. Close this window and click Refresh to update the preview. Selection filtering updates immediately.";
    const fields = document.createElement("div");
    fields.id = "settingsFields";
    body.append(note, fields);
    for (const group of groups) {
      const section = document.createElement("fieldset");
      section.className = group.checks ? "settings-checks" : "settings-values";
      const legend = document.createElement("legend");
      legend.textContent = group.title;
      section.append(legend);
      if (group.title === "Canvas") this.resolution(section);
      if (group.title === "Canvas") {
        const explanation = document.createElement("p");
        explanation.className = "settings-note";
        explanation.textContent = "Resolution is the full virtual screen. HeightFactor uses this height. Select a branch to inspect it without changing the screen size.";
        section.append(explanation);
      }
      for (const field of group.fields)
        this.field(section, field, !!group.checks);
      fields.append(section);
    }
    this.syncResolution();
    const footer = document.createElement("footer");
    footer.className = "settings-footer";
    this.status = document.createElement("span");
    this.status.id = "settingsStatus";
    this.status.setAttribute("role", "status");
    const done = document.createElement("button");
    done.id = "closeSettings";
    done.textContent = "Done";
    done.className = "primary";
    done.onclick = () => this.modal?.element.close();
    const reset = document.createElement("button");
    reset.id = "resetSettings";
    reset.textContent = "Reset to defaults";
    reset.onclick = () => {
      this.reset();
      this.refresh();
      this.status!.textContent =
        "Defaults restored. Click Refresh to update the preview.";
    };
    const actions = document.createElement("div");
    actions.className = "settings-actions";
    actions.append(reset, done);
    footer.append(this.status, actions);
    body.append(footer);
  }

  private resolution(parent: HTMLElement) {
    const preset = document.createElement("select");
    preset.id = "resolutionPreset";
    for (const [label, width, height] of [
      ["Custom resolution", 0, 0],
      ["1280 × 720", 1280, 720],
      ["1920 × 1080", 1920, 1080],
      ["2560 × 1080", 2560, 1080],
      ["1024 × 768", 1024, 768],
      ["720 × 1280", 720, 1280],
    ] as const) {
      const option = new Option(label, JSON.stringify([width, height]));
      option.selected =
        this.options().width === width && this.options().height === height;
      preset.add(option);
    }
    preset.onchange = () => {
      const [width, height] = JSON.parse(preset.value);
      if (!width) return;
      Object.assign(this.options(), { width, height });
      this.changed(["width", "height"]);
      this.refresh();
    };
    this.valueLabel(parent, "Resolution", preset);
    const aspect = document.createElement("select");
    aspect.id = "aspectPreset";
    for (const ratio of ["Free", "16:9", "4:3", "21:9", "9:16"])
      aspect.add(new Option(ratio, ratio));
    aspect.onchange = () => {
      if (!aspect.value.includes(":")) return;
      const [x, y] = aspect.value.split(":").map(Number);
      this.options().height = Math.round((this.options().width * y) / x);
      this.changed(["height"]);
      this.refresh();
    };
    this.valueLabel(parent, "Aspect ratio", aspect);
  }

  private syncResolution() {
    if (!this.modal) return;
    const preset =
      this.modal.element.querySelector<HTMLSelectElement>("#resolutionPreset");
    const aspect =
      this.modal.element.querySelector<HTMLSelectElement>("#aspectPreset");
    if (preset) {
      const value = JSON.stringify([
        this.options().width,
        this.options().height,
      ]);
      preset.value = Array.from(preset.options).some(
        (option) => option.value === value,
      )
        ? value
        : "[0,0]";
    }
    if (aspect) {
      aspect.value = "Free";
      for (const option of Array.from(aspect.options)) {
        if (!option.value.includes(":")) continue;
        const [x, y] = option.value.split(":").map(Number);
        if (
          Math.round((this.options().width * y) / x) === this.options().height
        ) {
          aspect.value = option.value;
          break;
        }
      }
    }
  }

  private valueLabel(parent: HTMLElement, title: string, input: HTMLElement) {
    const label = document.createElement("label");
    label.className = "setting-value";
    label.htmlFor = input.id;
    const name = document.createElement("span");
    name.textContent = title;
    label.append(name, input);
    parent.append(label);
  }

  private field(parent: HTMLElement, field: Field, checkbox: boolean) {
    const type = checkbox ? "checkbox" : field.type || "number";
    let input: HTMLInputElement | HTMLSelectElement;
    if (type === "select") {
      input = document.createElement("select");
      for (const choice of field.choices!)
        input.add(new Option(choice || "Default", choice));
      input.value = String(this.options()[field.key] ?? "");
    } else {
      input = document.createElement("input");
      input.type = type;
      if (checkbox) input.checked = !!this.options()[field.key];
      else input.value = String(this.options()[field.key]);
      if (field.range)
        [input.min, input.max, input.step] = field.range.map(String);
    }
    input.id = "option-" + field.key;
    input.name = field.key;
    if (checkbox) {
      const label = document.createElement("label");
      label.htmlFor = input.id;
      label.className = "setting-check";
      const caption = document.createElement("span");
      const title = document.createElement("span");
      title.className = "setting-title";
      title.id = input.id + "-label";
      title.textContent = field.label;
      const description = document.createElement("small");
      description.id = input.id + "-help";
      description.textContent = field.description!;
      input.setAttribute("aria-labelledby", title.id);
      input.setAttribute("aria-describedby", description.id);
      caption.append(title, description);
      label.append(input, caption);
      parent.append(label);
    } else this.valueLabel(parent, field.label, input);
    input.onchange = () => {
      const next = checkbox
        ? (input as HTMLInputElement).checked
        : type === "number"
          ? Number(input.value)
          : input.value;
      if (
        type === "number" &&
        (!input.value.trim() ||
          !Number.isFinite(next) ||
          Number(next) < field.range![0] ||
          Number(next) > field.range![1])
      ) {
        input.setAttribute("aria-invalid", "true");
        this.status!.textContent = "Enter a value within the allowed range.";
        return;
      }
      input.removeAttribute("aria-invalid");
      this.options()[field.key] = next;
      if (field.key === "width" || field.key === "height")
        this.syncResolution();
      const applied = this.changed([field.key]);
      this.status!.textContent =
        field.key === "selectionOnly" && applied
          ? "Selection filter updated."
          : "Saved. Click Refresh to update the preview.";
    };
  }
}
