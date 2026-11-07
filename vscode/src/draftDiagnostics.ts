import * as vscode from "vscode";
import { EMPTY_DRAFT_WARNING } from "./newDocument";

/** Report zero-byte files without decoding or rendering the workspace corpus. */
export class DraftDiagnostics implements vscode.Disposable {
  private collection = vscode.languages.createDiagnosticCollection("bgin-empty-drafts");
  private disposables: vscode.Disposable[] = [];
  private versions = new Map<string, number>();
  private disposed = false;
  constructor(private isOpen: (uri: vscode.Uri) => boolean) {
    const watch = vscode.workspace.createFileSystemWatcher("**/*.bgin");
    this.disposables.push(watch,
      watch.onDidCreate(uri => { void this.check(uri); }),
      watch.onDidChange(uri => { void this.check(uri); }),
      watch.onDidDelete(uri => { this.versions.delete(uri.toString()); this.collection.delete(uri); }),
      vscode.workspace.onDidOpenTextDocument(doc => this.checkJson(doc)),
      vscode.workspace.onDidChangeTextDocument(event => this.checkJson(event.document)),
      vscode.workspace.onDidCloseTextDocument(doc => this.collection.delete(doc.uri)),
      vscode.workspace.onDidChangeWorkspaceFolders(() => { void this.scan(); }),
    );
    void this.scan();
    for (const doc of vscode.workspace.textDocuments) this.checkJson(doc);
  }
  private warn(uri: vscode.Uri, empty: boolean) {
    const warning = new vscode.Diagnostic(new vscode.Range(0, 0, 0, 1), EMPTY_DRAFT_WARNING, vscode.DiagnosticSeverity.Warning);
    warning.source = "Binary GIN";
    this.collection.set(uri, empty ? [warning] : []);
  }
  async check(uri: vscode.Uri) {
    if (this.disposed) return;
    const key = uri.toString(), version = (this.versions.get(key) || 0) + 1;
    this.versions.set(key, version);
    try {
      const stat = await vscode.workspace.fs.stat(uri);
      if (this.versions.get(key) === version) this.warn(uri, !this.isOpen(uri) && stat.size === 0);
    } catch { if (this.versions.get(key) === version) this.collection.delete(uri); }
  }
  private checkJson(doc: vscode.TextDocument) {
    if (!doc.uri.path.toLowerCase().endsWith(".json")) return;
    if (doc.getText().length > 4096) { this.collection.delete(doc.uri); return; }
    try {
      const value = JSON.parse(doc.getText());
      this.warn(doc.uri, value && Array.isArray(value.screens) && value.screens.length === 0 && !Object.hasOwn(value, "name"));
    } catch { this.collection.delete(doc.uri); }
  }
  private async scan() {
    const files = await vscode.workspace.findFiles("**/*.bgin", "{**/.git/**,**/node_modules/**}");
    for (let i = 0; i < files.length && !this.disposed; i += 16) await Promise.all(files.slice(i, i + 16).map(uri => this.check(uri)));
  }
  dispose() {
    this.disposed = true;
    this.versions.clear();
    this.collection.dispose();
    for (const disposable of this.disposables) disposable.dispose();
  }
}
