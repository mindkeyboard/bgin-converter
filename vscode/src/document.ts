import * as vscode from "vscode";
import { randomUUID } from "node:crypto";
import { Backend } from "./backend";
import { readDocumentText, requireFirstScreen, isUnnamedEmptyDraft } from "./newDocument";

export class BginDocument implements vscode.CustomDocument {
  readonly panels = new Set<vscode.WebviewPanel>();
  revision = 0;
  private disposed = new vscode.EventEmitter<void>();
  readonly onDispose = this.disposed.event;
  constructor(
    readonly uri: vscode.Uri,
    public text: string,
    readonly backend: Backend,
  ) {}
  set(text: string, origin?: vscode.WebviewPanel) {
    this.text = text;
    this.revision++;
    for (const panel of this.panels)
      if (panel !== origin)
        panel.webview.postMessage({
          type: "document",
          text,
          revision: this.revision,
        });
  }
  async save(uri = this.uri) {
    const snapshot = this.text;
    requireFirstScreen(snapshot);
    const draft = isUnnamedEmptyDraft(snapshot);
    if (draft && Object.keys(JSON.parse(snapshot)).some(key => !["screens", "dialect"].includes(key))) throw Error("Unknown fields in an empty draft");
    if (draft && ![undefined, "ui"].includes(JSON.parse(snapshot).dialect)) throw Error("An unnamed empty draft must use the ui dialect");
    if (draft) {
      try {
        // Saving an untouched zero-byte file must not replace its inode and
        // trigger an unnecessary custom-editor reload.
        if ((await vscode.workspace.fs.stat(uri)).size === 0) return;
      } catch (error: any) {
        if (error.code !== "FileNotFound" && error.code !== "ENOENT") throw error;
      }
    }
    const encoded = draft ? { data: "" } : await this.backend.call("encode", { text: snapshot });
    const temp = uri.with({ path: uri.path + "." + randomUUID() + ".tmp" });
    try {
      await vscode.workspace.fs.writeFile(
        temp,
        Buffer.from(encoded.data, "base64"),
      );
      await vscode.workspace.fs.rename(temp, uri, { overwrite: true });
    } finally {
      try {
        await vscode.workspace.fs.delete(temp);
      } catch {}
    }
  }
  async revert() {
    this.set(await readDocumentText(this.uri, this.backend));
  }
  dispose() {
    this.disposed.fire();
    this.disposed.dispose();
  }
}
