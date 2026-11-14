import * as vscode from "vscode";
import { rename } from "node:fs/promises";
import { createHash, randomUUID } from "node:crypto";
import { Backend } from "./backend";
import { readDocumentText, requireFirstScreen, isUnnamedEmptyDraft } from "./newDocument";
import { documentFormat } from "./formatProfiles";

export class BginDocument implements vscode.CustomDocument {
  readonly panels = new Set<vscode.WebviewPanel>();
  revision = 0;
  private disposed = new vscode.EventEmitter<void>();
  readonly onDispose = this.disposed.event;
  private changed = new vscode.EventEmitter<void>();
  readonly onDidChange = this.changed.event;
  private diskFingerprint?: string | null;
  private sourceFormat?: string;
  private createdFromEmpty: boolean;
  saveRequest?: { revision: number; signal?: AbortSignal };
  constructor(
    readonly uri: vscode.Uri,
    public text: string,
    readonly backend: Backend,
  ) { this.sourceFormat = documentFormat(text); this.createdFromEmpty = isUnnamedEmptyDraftSafely(text); }
  set(text: string, origin?: vscode.WebviewPanel) {
    this.text = text;
    this.revision++;
    if (!this.sourceFormat || this.createdFromEmpty) this.sourceFormat = documentFormat(text);
    for (const panel of this.panels)
      if (panel !== origin)
        panel.webview.postMessage({
          type: "document",
          text,
          revision: this.revision,
        });
    this.changed.fire();
  }
  private async fingerprint(uri: vscode.Uri): Promise<string | null> {
    if (uri.scheme === "untitled") return null;
    try { return createHash("sha256").update(await vscode.workspace.fs.readFile(uri)).digest("hex"); }
    catch (error: any) {
      if (error.code === "FileNotFound" || error.code === "ENOENT") return null;
      throw error;
    }
  }
  async rememberDisk(bytes?: Uint8Array) { this.diskFingerprint = bytes ? createHash("sha256").update(bytes).digest("hex") : await this.fingerprint(this.uri); }
  async save(uri = this.uri, signal?: AbortSignal) {
    const snapshot = this.text, revision = this.revision;
    const current = () => {
      if (signal?.aborted || this.saveRequest?.signal?.aborted) throw Error("Saving was cancelled.");
      if (revision !== this.revision) throw Error("Document changed while saving. Save the current revision again.");
      if (this.saveRequest && this.saveRequest.revision !== this.revision) throw Error("Document revision conflict while saving.");
    };
    current();
    requireFirstScreen(snapshot);
    const draft = isUnnamedEmptyDraft(snapshot);
    if (draft && Object.keys(JSON.parse(snapshot)).some(key => !["screens", "dialect"].includes(key))) throw Error("Unknown fields in an empty draft");
    if (draft && ![undefined, "ui"].includes(JSON.parse(snapshot).dialect)) throw Error("An unnamed empty draft must use the ui dialect");
    if (!draft && documentFormat(snapshot) !== this.sourceFormat)
      throw Error("Saving keeps the source BGIN format. Use the converter to select another format.");
    const sameFile = uri.toString() === this.uri.toString();
    const expected = sameFile && this.diskFingerprint !== undefined ? this.diskFingerprint : await this.fingerprint(uri);
    if (await this.fingerprint(uri) !== expected) throw Error("The file changed outside the editor. Reopen it before saving.");
    if (draft) {
      try {
        // Saving an untouched zero-byte file must not replace its inode and
        // trigger an unnecessary custom-editor reload.
        if ((await vscode.workspace.fs.stat(uri)).size === 0) { current(); return; }
      } catch (error: any) {
        if (error.code !== "FileNotFound" && error.code !== "ENOENT") throw error;
      }
    }
    const encoded = draft ? { data: "" } : await this.backend.call("encode", { text: snapshot });
    current();
    if (uri.scheme !== "file") throw Error("Safe BGIN saving requires a local file destination.");
    const temp = uri.with({ path: uri.path + "." + randomUUID() + ".tmp" });
    try {
      await vscode.workspace.fs.writeFile(
        temp,
        Buffer.from(encoded.data, "base64"),
      );
      if (await this.fingerprint(uri) !== expected) throw Error("The file changed outside the editor while saving. Reopen it before saving.");
      if (expected !== null) {
        const backup = uri.with({ path: uri.path + "." + randomUUID() + ".bak" });
        await vscode.workspace.fs.copy(uri, backup, { overwrite: false });
        if (await this.fingerprint(backup) !== expected || await this.fingerprint(uri) !== expected)
          throw Error("The file changed while creating its backup. Reopen it before saving.");
      }
      current();
      // A workspace file move clears VS Code's undo stack for the destination.
      // Replace the local file directly so the verified save retains edit history.
      await rename(temp.fsPath, uri.fsPath);
      if (sameFile) this.diskFingerprint = createHash("sha256").update(Buffer.from(encoded.data, "base64")).digest("hex");
      if (!draft) this.createdFromEmpty = false;
      current();
    } finally {
      try {
        await vscode.workspace.fs.delete(temp);
      } catch {}
    }
  }
  async revert() {
    const bytes = await vscode.workspace.fs.readFile(this.uri);
    const text = await readDocumentText(this.uri, this.backend, bytes);
    this.sourceFormat = documentFormat(text);
    this.createdFromEmpty = isUnnamedEmptyDraftSafely(text);
    await this.rememberDisk(bytes);
    this.set(text);
  }
  dispose() {
    this.disposed.fire();
    this.disposed.dispose();
    this.changed.dispose();
  }
}

function isUnnamedEmptyDraftSafely(text: string) {
  try { return !!isUnnamedEmptyDraft(text); } catch { return false; }
}
