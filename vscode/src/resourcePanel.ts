import { t } from "./i18n";
/** Resource browsing does not start the BGIN worker. */
export class ResourcePanel {
  private dirty = false;
  private serial = 0;
  private pickers = new Map<number, HTMLInputElement>();
  private current: any = {};
  private form: HTMLFieldSetElement;
  private status: HTMLElement;
  private fields: Record<string, HTMLInputElement> = {};
  constructor(
    private element: HTMLElement,
    private send: (m: any) => void,
  ) {
    element.innerHTML = `<div class="toolbar"><strong>Resources</strong><span class="spacer"></span><button id="closeResources" aria-label="Close resources">×</button></div><div class="dialog-body"><p class="resource-hint">Choose external resource folders. BGIN references use each file's internal namespace; files are loaded when needed.</p><fieldset id="resourceForm"><div id="resourceFolders"></div><div class="resource-discovery"><strong>Auto-fill from an extracted archive</strong><div class="path-picker"><input id="discoveryRoot" aria-label="Extracted archive folder" placeholder="Extracted archive folder"><button id="browseDiscoveryRoot" type="button">Browse…</button><button id="discoverResources" type="button">Auto-fill</button></div><p class="resource-hint">Finds gui, textures_android and texter_fonts folders. Review the paths before saving.</p></div><div class="toolbar resource-actions"><span id="resourceStatus" role="status"></span><span class="spacer"></span><button id="saveResources" type="button" class="primary">Save folders</button></div></fieldset></div>`;
    const find = <T extends HTMLElement>(id: string) =>
      element.querySelector("#" + id) as T;
    this.form = find("resourceForm");
    this.status = find("resourceStatus");
    for (const [key, label] of [
      ["assetRoot", "Resource root"],
      ["bginRoot", "BGIN folder"],
      ["textureRoot", "Textures folder"],
      ["fontRoot", "Fonts folder"],
    ]) {
      const holder = document.createElement("label");
      holder.className = "asset-root";
      holder.textContent = label;
      const line = document.createElement("div"),
        input = document.createElement("input"),
        browse = document.createElement("button");
      input.id = key;
      input.setAttribute("aria-label", label);
      input.placeholder = t("Optional path");
      input.oninput = () => {
        this.dirty = true;
      };
      browse.type = "button";
      browse.textContent = "Browse…";
      browse.onclick = () => this.pick(input);
      line.append(input, browse);
      holder.append(line);
      find("resourceFolders").append(holder);
      this.fields[key] = input;
    }
    find("closeResources").onclick = () => this.close();
    find("saveResources").onclick = () => this.save();
    find("browseDiscoveryRoot").onclick = () =>
      this.pick(find("discoveryRoot"));
    find("discoverResources").onclick = () => {
      const root = find<HTMLInputElement>("discoveryRoot").value.trim();
      if (!root) {
        this.status.textContent = t("Choose an extracted archive folder");
        return;
      }
      this.form.disabled = true;
      this.status.textContent = t("Discovering resources…");
      this.send({ type: "resourcesDiscover", root });
    };
    element.addEventListener("click", (e) => {
      if (e.target === element) this.close();
    });
  }
  open() {
    const modal = this.element as HTMLDialogElement;
    if (!modal.open) modal.showModal();
  }
  close() {
    (this.element as HTMLDialogElement).close();
  }
  toggle() {
    if ((this.element as HTMLDialogElement).open) this.close();
    else this.open();
  }
  update(settings: any) {
    this.current = settings || {};
    if (!this.dirty && !this.form.disabled) this.populate();
  }
  private populate() {
    for (const [key, input] of Object.entries(this.fields))
      input.value = this.current[key] || "";
    (this.element.querySelector("#discoveryRoot") as HTMLInputElement).value =
      this.current.assetRoot || "";
  }
  private pick(input: HTMLInputElement) {
    const requestId = ++this.serial;
    this.pickers.set(requestId, input);
    this.send({ type: "resourceBrowse", target: "root", requestId });
  }
  private save() {
    this.form.disabled = true;
    this.status.textContent = t("Saving…");
    this.send({
      type: "resourcesApply",
      ...Object.fromEntries(
        Object.entries(this.fields).map(([key, input]) => [
          key,
          input.value.trim(),
        ]),
      ),
    });
  }
  message(m: any) {
    if (m.type === "resourcePicked") {
      const input = this.pickers.get(m.requestId);
      this.pickers.delete(m.requestId);
      if (input?.isConnected && m.path) {
        input.value = m.path;
        this.dirty = true;
      }
    }
    if (m.type === "resourcesDiscovered") {
      this.form.disabled = false;
      if (m.error) {
        this.status.textContent = m.error;
        return;
      }
      this.current = { ...m.resourceSettings };
      this.populate();
      this.dirty = true;
      this.status.textContent =
        (m.notes || []).join("\n") || t("Paths found · review and save");
    }
    if (m.type === "resourcesSaved") {
      this.form.disabled = false;
      if (m.error) {
        this.status.textContent = m.error;
        return;
      }
      this.dirty = false;
      this.update(m.resourceSettings);
      this.status.textContent =
        [m.notice, ...(m.errors || [])]
          .filter(Boolean)
          .map((s) => t(s))
          .join("\n") || t("Folders saved");
    }
    if (m.type === "openResources") this.open();
  }
}
