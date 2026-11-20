import * as vscode from "vscode";
import * as path from "node:path";
import { randomBytes, randomUUID } from "node:crypto";
import {
  parseTree,
  ParseError,
  printParseErrorCode,
  findNodeAtLocation,
  Node as JsonNode,
} from "jsonc-parser";
import { TERMS_VERSION } from "./termsVersion";
import { Backend, RpcError } from "./backend";
import { BginDocument } from "./document";
import { newBginFile, readDocumentText, requiresDocumentName, EMPTY_DRAFT_WARNING } from "./newDocument";
import { ConverterView } from "./converterView";
import { FirstRunChannel, CHANNEL_URL } from "./onboarding";
import { DraftDiagnostics } from "./draftDiagnostics";
import { registerExplorerNew, runExplorerRegistration } from "./explorerNew";
import { PreviewSession } from "./preview";
import { McpBridge, BridgeDocument, BridgeRender } from "./mcpBridge";
import { normalizeFormat } from "./formatProfiles";
import { discoverResources, scanBginFolder } from "./resourceDiscovery";
import { convertTexture } from "./textureConversion";
import {
  resourceFolderKeys,
  resourceFolders,
  saveResourceFolders,
} from "./resourceSettings";

export class Provider implements vscode.CustomEditorProvider<BginDocument> {
  readonly onboarding: FirstRunChannel;
  private changes = new vscode.EventEmitter<
    vscode.CustomDocumentEditEvent<BginDocument>
  >();
  readonly onDidChangeCustomDocument = this.changes.event;
  readonly documents = new Map<string, BginDocument>();
  private syntax = vscode.languages.createDiagnosticCollection("bgin");
  private resources =
    vscode.languages.createDiagnosticCollection("bgin-resources");
  private active?: vscode.WebviewPanel;
  private previews = new Map<vscode.WebviewPanel, PreviewSession>();
  private resourceFiles = vscode.languages.createDiagnosticCollection(
    "bgin-resource-files",
  );
  private resourceVersions = new Map<BginDocument, number>();
  private timers = new Map<BginDocument, NodeJS.Timeout>();
  private watchers = new Map<BginDocument, vscode.Disposable[]>();
  private drafts: DraftDiagnostics;
  bridge?: McpBridge;
  private renderGallery?: vscode.WebviewPanel;
  private renderHistory: BridgeRender[] = [];
  private sharedResourceRevision = 0;
  constructor(
    readonly context: vscode.ExtensionContext,
    readonly backend: Backend,
  ) {
    this.onboarding = new FirstRunChannel(context.globalState, () => vscode.env.openExternal(vscode.Uri.parse(CHANNEL_URL)));
    this.drafts = new DraftDiagnostics(uri => this.documents.has(uri.toString()));
    context.subscriptions.push(
      this.drafts,
      this.changes,
      this.syntax,
      this.resources,
      this.resourceFiles,
      vscode.workspace.onDidChangeConfiguration((e) => {
        if (e.affectsConfiguration("bgin")) {
          this.invalidateSharedResources();
          for (const session of this.previews.values())
            session.cancel("Settings changed; refresh the preview");
          for (const d of this.documents.values()) {
            this.watchResources(d);
            void this.checkResourceFiles(d);
            for (const p of d.panels) this.sendConfig(d, p);
          }
        }
      }),
    );
  }
  async openCustomDocument(
    uri: vscode.Uri,
    open: vscode.CustomDocumentOpenContext,
  ): Promise<BginDocument> {
    let text: string, bytes: Uint8Array | undefined;
    if (open.backupId)
      text = Buffer.from(
        await vscode.workspace.fs.readFile(vscode.Uri.parse(open.backupId)),
      ).toString("utf8");
    else {
      if (uri.scheme !== "untitled") bytes = await vscode.workspace.fs.readFile(uri);
      text = await readDocumentText(uri, this.backend, bytes);
    }
    const doc = new BginDocument(uri, text, this.backend);
    await doc.rememberDisk(bytes);
    this.documents.set(uri.toString(), doc);
    doc.onDidChange(() => { this.bridge?.documentChanged(this.snapshot(doc)); this.refreshRenderGallery(); });
    void this.drafts.check(uri);
    doc.onDispose(() => {
      this.documents.delete(uri.toString());
      this.syntax.delete(uri);
      this.resources.delete(uri);
      this.resourceFiles.delete(uri);
      this.resourceVersions.delete(doc);
      clearTimeout(this.timers.get(doc));
      for (const w of this.watchers.get(doc) || []) w.dispose();
      this.watchers.delete(doc);
      void this.drafts.check(uri);
    });
    this.watchResources(doc);
    void this.checkResourceFiles(doc);
    this.validate(doc);
    return doc;
  }
  edit(doc: BginDocument, text: string, origin?: vscode.WebviewPanel, naming = false, label = "Edit BGIN") {
    if (!naming && requiresDocumentName(doc.text)) throw Error("Set a document name before editing this BGIN file.");
    if (text === doc.text) return;
    const before = doc.text;
    for (const panel of doc.panels)
      this.previews.get(panel)?.cancel("Document changed; refresh the preview");
    doc.set(text, origin);
    this.validate(doc);
    this.changes.fire({
      document: doc,
      label,
      undo: async () => {
        doc.set(before);
        this.validate(doc);
      },
      redo: async () => {
        doc.set(text);
        this.validate(doc);
      },
    });
  }
  snapshot(doc: BginDocument): BridgeDocument {
    return { documentId: doc.uri.toString(), path: doc.uri.fsPath, text: doc.text, revision: doc.revision };
  }
  private sharedDocument(id: string) {
    const doc = this.documents.get(id);
    if (!doc) throw Error("The shared BGIN document is no longer open.");
    return doc;
  }
  private requireRevision(doc: BginDocument, revision: number, signal?: AbortSignal) {
    if (signal?.aborted) throw Object.assign(Error("Operation cancelled."), { code: "cancelled" });
    if (!Number.isInteger(revision) || revision !== doc.revision)
      throw Object.assign(Error(`Document revision conflict: expected ${revision}, current ${doc.revision}. Read the current document before editing.`), { code: "revision_conflict", details: this.snapshot(doc) });
  }
  async applySharedEdit(id: string, text: string, revision: number, label: string, signal?: AbortSignal) {
    const doc = this.sharedDocument(id);
    this.requireRevision(doc, revision, signal);
    // Validate the proposed snapshot, then check again after yielding to the worker.
    // Manual edits, including invalid JSON, always remain the authoritative text.
    await this.backend.call("validate", { text });
    this.requireRevision(doc, revision, signal);
    this.edit(doc, text, undefined, false, label);
    return this.snapshot(doc);
  }
  async saveSharedDocument(id: string, revision: number, signal?: AbortSignal) {
    const doc = this.sharedDocument(id);
    this.requireRevision(doc, revision, signal);
    await this.backend.call("validate", { text: doc.text });
    this.requireRevision(doc, revision, signal);
    // The VS Code save command owns the dirty flag and delegates to doc.save().
    if (doc.saveRequest) throw Error("Another client is already saving this document.");
    const request = { revision, signal };
    doc.saveRequest = request;
    try {
      const saved = await vscode.workspace.save(doc.uri);
      if (!saved) throw Error("VS Code did not save the document.");
      this.requireRevision(doc, revision, signal);
      return this.snapshot(doc);
    } finally { if (doc.saveRequest === request) doc.saveRequest = undefined; }
  }
  async openSharedDocument(file: string) {
    if (!path.isAbsolute(file)) throw Error("Opening a shared document requires an absolute local path.");
    const uri = vscode.Uri.file(file);
    await vscode.commands.executeCommand("vscode.openWith", uri, "bgin.editor", { preserveFocus: true, preview: false });
    const doc = this.documents.get(uri.toString());
    if (!doc) throw Error("VS Code did not open the BGIN document.");
    return this.snapshot(doc);
  }
  sharedSettings(id?: string) {
    const doc = id ? this.sharedDocument(id) : this.documents.values().next().value;
    if (!doc) return { preview: {}, resources: {}, resourceBase: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath, resourceRevision: this.sharedResourceRevision };
    const config = this.config(doc);
    return { preview: config.defaults, resources: config.resources, resourceBase: path.dirname(doc.uri.fsPath), resourceRevision: this.sharedResourceRevision };
  }
  showSharedRender(event: BridgeRender) {
    const metadata = event.metadata as any;
    if (event.stale || metadata?.stale || this.documents.get(event.documentId)?.revision !== event.revision ||
        (metadata?.resourceRevision !== undefined && metadata.resourceRevision !== this.sharedResourceRevision)) event = { ...event, stale: true };
    this.renderHistory.unshift(event);
    // Bound retained image data; the model already received the original result.
    this.renderHistory = this.renderHistory.slice(0, 8);
    if (!this.renderGallery) {
      this.renderGallery = vscode.window.createWebviewPanel("bgin.mcpPreviews", "BGIN · MCP previews", { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true }, { enableScripts: false, retainContextWhenHidden: true, localResourceRoots: [] });
      this.renderGallery.onDidDispose(() => { this.renderGallery = undefined; this.renderHistory = []; });
    }
    this.refreshRenderGallery();
  }
  private refreshRenderGallery() {
    if (!this.renderGallery) return;
    this.renderHistory = this.renderHistory.map(render => {
      const sources = (render.metadata as any)?.documents;
      const stale = render.stale || this.documents.get(render.documentId)?.revision !== render.revision ||
        Array.isArray(sources) && sources.some(source => this.documents.get(source.documentId)?.revision !== source.revision);
      return { ...render, stale };
    });
    const escape = (value: unknown) => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
    const ru = vscode.workspace.getConfiguration("bgin").get<string>("language", "en") === "ru";
    this.renderGallery.webview.html = `<!doctype html><html lang="${ru ? "ru" : "en"}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'"><style>body{font:var(--vscode-font-size)/1.5 var(--vscode-font-family);color:var(--vscode-foreground);padding:16px}section{border-bottom:1px solid var(--vscode-panel-border);margin-bottom:24px}img{display:block;max-width:100%;height:auto;margin:12px 0}small,p{overflow-wrap:anywhere}h2{font-size:14px}</style></head><body><h1>${ru ? "Предпросмотры MCP" : "MCP previews"}</h1><p>${ru ? "Снимки общих документов. Редактирование остаётся доступным в редакторе BGIN." : "Snapshots of shared documents. Editing remains available in the BGIN editor."}</p>${this.renderHistory.map(render => `<section><h2>${escape(render.clientName)} · ${ru ? "ревизия" : "revision"} ${render.revision}${render.stale ? ru ? " · устарел" : " · stale" : ""}</h2><small>${escape(render.documentId)}</small>${render.images.filter(image => image.mimeType === "image/png" && /^[A-Za-z0-9+/=\r\n]+$/.test(image.data)).map(image => `<img alt="MCP preview" src="data:image/png;base64,${image.data}">`).join("")}</section>`).join("")}</body></html>`;
  }
  private invalidateSharedResources() {
    this.sharedResourceRevision++;
    this.renderHistory = this.renderHistory.map(render => ({ ...render, stale: true }));
    this.refreshRenderGallery();
  }
  private location(text: string, offset: number): vscode.Position {
    const lines = text.slice(0, offset).split("\n");
    return new vscode.Position(lines.length - 1, lines.at(-1)!.length);
  }
  private diagnostic(text: string, error: any): vscode.Diagnostic {
    let offset = 0,
      length = 1;
    if (error.path) {
      const tree = parseTree(text);
      const node =
        tree &&
        findNodeAtLocation(
          tree,
          error.path
            .split("/")
            .slice(1)
            .map((s: string) =>
              /^\d+$/.test(s)
                ? Number(s)
                : s.replace(/~1/g, "/").replace(/~0/g, "~"),
            ),
        );
      if (node) {
        offset = node.offset;
        length = node.length;
      }
    }
    const start =
      error.line !== undefined
        ? new vscode.Position(error.line, error.column || 0)
        : this.location(text, offset);
    const end =
      error.line !== undefined
        ? start.translate(0, 1)
        : this.location(text, offset + length);
    const d = new vscode.Diagnostic(
      new vscode.Range(start, end),
      error.message,
      vscode.DiagnosticSeverity.Error,
    );
    d.source = "Binary GIN";
    return d;
  }
  validate(doc: BginDocument) {
    clearTimeout(this.timers.get(doc));
    this.timers.set(
      doc,
      setTimeout(() => this.checkSyntax(doc), 200),
    );
  }
  nameDocument(doc: BginDocument, name: string, format?: string) {
    if (!requiresDocumentName(doc.text)) return;
    if (typeof name !== "string" || !name.trim()) throw Error("Document name must not be blank.");
    name = name.trim();
    if (Buffer.byteLength(name, "utf8") > 65535) throw Error("Document name exceeds 65535 UTF-8 bytes.");
    const data = JSON.parse(doc.text);
    data.name = name;
    data.format = normalizeFormat(format ?? "a8-1.6.0");
    if (!data.format) throw Error("Choose one of the four BGIN formats.");
    this.edit(doc, JSON.stringify(data, null, 2) + "\n", undefined, true);
    for (const panel of doc.panels) panel.webview.postMessage({ type: "nameAccepted" });
  }
  private checkSyntax(doc: BginDocument) {
    const errors: ParseError[] = [];
    const tree = parseTree(doc.text, errors, {
      allowTrailingComma: false,
      disallowComments: true,
      allowEmptyContent: false,
    });
    const diagnostics = errors.map(
      (e) =>
        new vscode.Diagnostic(
          new vscode.Range(
            this.location(doc.text, e.offset),
            this.location(doc.text, e.offset + Math.max(1, e.length)),
          ),
          printParseErrorCode(e.error),
          vscode.DiagnosticSeverity.Error,
        ),
    );
    // JSON permits duplicate names syntactically; editing BGIN requires unambiguous keys.
    const duplicates = (n: JsonNode) => {
      if (n.type === "object") {
        const keys = new Set();
        for (const child of n.children || []) {
          const k = child.children?.[0];
          if (k) {
            if (keys.has(k.value))
              diagnostics.push(
                new vscode.Diagnostic(
                  new vscode.Range(
                    this.location(doc.text, k.offset),
                    this.location(doc.text, k.offset + k.length),
                  ),
                  "Duplicate name: " + k.value,
                  vscode.DiagnosticSeverity.Error,
                ),
              );
            keys.add(k.value);
          }
        }
      }
      for (const c of n.children || []) duplicates(c);
    };
    if (tree) duplicates(tree);
    const syntaxErrors = diagnostics.filter(d => d.severity === vscode.DiagnosticSeverity.Error);
    if (requiresDocumentName(doc.text)) {
      const diagnostic = new vscode.Diagnostic(new vscode.Range(0, 0, 0, 1), EMPTY_DRAFT_WARNING, vscode.DiagnosticSeverity.Warning);
      diagnostic.source = "Binary GIN";
      diagnostics.push(diagnostic);
    }
    this.syntax.set(doc.uri, diagnostics);
    for (const p of doc.panels)
      p.webview.postMessage({
        type: "syntax",
        errors: syntaxErrors.map((d) => d.message),
      });
    if (syntaxErrors.length) {
      this.resources.delete(doc.uri);
      return;
    }
  }
  private resourceStateKey(doc: BginDocument) {
    return (
      "bgin.resourceFolders:" +
      (vscode.workspace.getWorkspaceFolder(doc.uri)?.uri.toString() ||
        path.dirname(doc.uri.fsPath))
    );
  }
  private config(doc: BginDocument) {
    const cfg = vscode.workspace.getConfiguration("bgin", doc.uri),
      base =
        vscode.workspace.getWorkspaceFolder(doc.uri)?.uri.fsPath ||
        vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ||
        path.dirname(doc.uri.fsPath);
    const resolve = (p: string) =>
      path.isAbsolute(p) ? p : path.resolve(base, p);
    const configured = cfg.get<Record<string, string>>("resourceFolders", {});
    const pending = this.context.workspaceState.get<Record<string, string>>(
      this.resourceStateKey(doc),
    );
    const folders = resourceFolders(
      pending || {
        ...Object.fromEntries(
          resourceFolderKeys.map((key) => [key, cfg.get<string>(key, "")]),
        ),
        ...configured,
      },
    );
    // Explicit aliases remain readable for old projects until a BGIN folder is selected.
    const legacy =
      pending || Object.keys(configured).length || folders.bginRoot
        ? {}
        : cfg.get<Record<string, string>>("resourceBindings", {});
    return {
      uiLanguage: cfg.get<string>("language", "en"),
      resources: {
        bindings: Object.fromEntries(
          Object.entries(legacy).map(([k, v]) => [k, resolve(v)]),
        ),
        ...Object.fromEntries(
          Object.entries(folders)
            .filter(([, value]) => value)
            .map(([key, value]) => [key, resolve(value)]),
        ),
      },
      resourceSettings: folders,
      defaults: cfg.get("preview", {}),
    };
  }
  private async checkResourceFiles(doc: BginDocument): Promise<string[]> {
    const version = (this.resourceVersions.get(doc) || 0) + 1;
    this.resourceVersions.set(doc, version);
    const config = this.config(doc).resources as Record<string, any>;
    const errors = (
      await Promise.all([
        ...Object.entries(config.bindings as Record<string, string>).map(
          async ([alias, file]) => {
            try {
              const stat = await vscode.workspace.fs.stat(
                vscode.Uri.file(file),
              );
              if (!(stat.type & vscode.FileType.File))
                return `Resource ${alias}: path is not a file: ${file}`;
            } catch {
              return `Resource ${alias}: file not found: ${file}`;
            }
            return "";
          },
        ),
        ...resourceFolderKeys.map(async (key) => {
          const file = config[key];
          if (!file) return "";
          try {
            if (
              (await vscode.workspace.fs.stat(vscode.Uri.file(file))).type &
              vscode.FileType.Directory
            )
              return "";
          } catch {}
          return `${key}: directory not found: ${file}`;
        }),
      ])
    ).filter(Boolean);
    if (config.bginRoot) {
      try {
        errors.push(...(await scanBginFolder(config.bginRoot)).errors);
      } catch {
        /* Missing folders already have a diagnostic above. */
      }
    }
    if (this.resourceVersions.get(doc) === version)
      this.resourceFiles.set(
        doc.uri,
        errors.map((message) => {
          const d = new vscode.Diagnostic(
            new vscode.Range(0, 0, 0, 1),
            message,
            vscode.DiagnosticSeverity.Error,
          );
          d.source = "Binary GIN resources";
          return d;
        }),
      );
    return errors;
  }
  private async applyResources(
    doc: BginDocument,
    panel: vscode.WebviewPanel,
    message: any,
  ) {
    try {
      const folders = resourceFolders(message);
      const cfg = vscode.workspace.getConfiguration("bgin", doc.uri);
      const target = vscode.workspace.getWorkspaceFolder(doc.uri)
        ? vscode.ConfigurationTarget.WorkspaceFolder
        : vscode.ConfigurationTarget.Global;
      const notice = await saveResourceFolders(
        cfg,
        this.context.workspaceState,
        this.resourceStateKey(doc),
        folders,
        target,
      );
      const errors = await this.refreshResourceDocuments(doc);
      panel.webview.postMessage({
        type: "resourcesSaved",
        ...this.config(doc),
        errors,
        notice,
      });
    } catch (e) {
      panel.webview.postMessage({ type: "resourcesSaved", error: String(e) });
    }
  }
  private async refreshResourceDocuments(doc: BginDocument) {
    this.invalidateSharedResources();
    // Workspace-state fallback emits no configuration event. Synchronize every
    // open document sharing these folders, including its in-flight preview.
    const key = this.resourceStateKey(doc);
    const affected = [...new Set([doc, ...this.documents.values()])].filter(
      (current) => this.resourceStateKey(current) === key,
    );
    const checks = await Promise.all(
      affected.map(async (current) => {
        for (const other of current.panels)
          this.previews
            .get(other)
            ?.cancel("Resources changed; refresh the preview");
        this.watchResources(current);
        const errors = await this.checkResourceFiles(current);
        for (const other of current.panels) this.sendConfig(current, other);
        return { current, errors };
      }),
    );
    return checks.find((item) => item.current === doc)!.errors;
  }
  private sendConfig(doc: BginDocument, panel: vscode.WebviewPanel) {
    panel.webview.postMessage({ type: "config", ...this.config(doc) });
  }
  private watchResources(doc: BginDocument) {
    for (const w of this.watchers.get(doc) || []) w.dispose();
    const config = this.config(doc).resources as Record<string, any>,
      items: vscode.Disposable[] = [];
    const patterns = Object.values(
      config.bindings as Record<string, string>,
    ).map(
      (file) =>
        new vscode.RelativePattern(path.dirname(file), path.basename(file)),
    );
    if (config.assetRoot)
      patterns.push(new vscode.RelativePattern(config.assetRoot, "**/*"));
    for (const folder of [config.bginRoot, config.textureRoot, config.fontRoot])
      if (folder && folder !== config.assetRoot)
        patterns.push(new vscode.RelativePattern(folder, "**/*"));
    let timer: NodeJS.Timeout | undefined;
    const refresh = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        this.invalidateSharedResources();
        void this.checkResourceFiles(doc);
        for (const p of doc.panels)
          this.previews
            .get(p)
            ?.cancel("Resources changed; refresh the preview");
        for (const p of doc.panels) this.sendConfig(doc, p);
      }, 250);
    };
    items.push({ dispose: () => clearTimeout(timer) });
    for (const pattern of patterns) {
      const watcher = vscode.workspace.createFileSystemWatcher(pattern);
      items.push(
        watcher,
        watcher.onDidChange(refresh),
        watcher.onDidCreate(refresh),
        watcher.onDidDelete(refresh),
      );
    }
    this.watchers.set(doc, items);
  }
  async resolveCustomEditor(doc: BginDocument, panel: vscode.WebviewPanel) {
    let termsShown = false;
    doc.panels.add(panel);
    this.active = panel;
    panel.webview.options = {
      enableScripts: true,
      localResourceRoots: [
        vscode.Uri.joinPath(this.context.extensionUri, "media"),
      ],
    };
    const nonce = randomBytes(20).toString("hex"),
      uri = (file: string) =>
        panel.webview.asWebviewUri(
          vscode.Uri.joinPath(this.context.extensionUri, "media", file),
        );
    panel.webview.html = `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; font-src data:; style-src ${panel.webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';"><link rel="stylesheet" href="${uri("styles.css")}"></head><body><div id="app"></div><script nonce="${nonce}" src="${uri("app.js")}"></script></body></html>`;
    const preview = new PreviewSession(this.context, panel);
    this.previews.set(panel, preview);
    panel.onDidChangeViewState(() => {
      if (panel.active) this.active = panel;
      if (!panel.visible) preview.cancel();
    });
    panel.onDidDispose(() => {
      preview.dispose();
      this.previews.delete(panel);
      doc.panels.delete(panel);
      if (this.active === panel) this.active = undefined;
    });
    panel.webview.onDidReceiveMessage(async (message) => {
      try {
        const settings = vscode.workspace.getConfiguration("bgin");
        if (message.type === "firstTermsDismissed" && termsShown) {
          await this.onboarding.complete();
          return;
        }
        if (message.type === "acceptTerms" && message.version === TERMS_VERSION) {
          await settings.update("acceptedTermsVersion", TERMS_VERSION, vscode.ConfigurationTarget.Global);
          panel.webview.postMessage({ type: "termsAccepted" });
          if (termsShown) await this.onboarding.complete();
          return;
        }
        if (settings.inspect<string>("acceptedTermsVersion")?.globalValue !== TERMS_VERSION) {
          termsShown = true;
          panel.webview.postMessage({ type: "termsRequired", uiLanguage: this.config(doc).uiLanguage });
          return;
        }
        if (message.type === "setLanguage" && ["en", "ru"].includes(message.language)) {
          const cfg = vscode.workspace.getConfiguration("bgin", doc.uri);
          const existing = cfg.inspect("language");
          const target = existing?.workspaceFolderValue !== undefined ? vscode.ConfigurationTarget.WorkspaceFolder :
            existing?.workspaceValue !== undefined ? vscode.ConfigurationTarget.Workspace : vscode.ConfigurationTarget.Global;
          await cfg.update("language", message.language, target);
          this.sendConfig(doc, panel);
          return;
        }
        if (message.type === "setDocumentName") {
          this.nameDocument(doc, message.name, message.format);
          return;
        }
        if (message.type === "openEditorGuide") {
          await vscode.env.openExternal(vscode.Uri.parse(editorGuideUrl(this.config(doc).uiLanguage)));
          return;
        }
        if (message.type === "openDocs") {
          await vscode.env.openExternal(vscode.Uri.parse(documentationUrl(this.config(doc).uiLanguage, message.target)));
          return;
        }
        if (requiresDocumentName(doc.text)) {
          panel.webview.postMessage({ type: "nameRequired", uiLanguage: this.config(doc).uiLanguage });
          return;
        }
        if (message.type === "ready") {
          const catalog = await this.backend.call("catalog");
          this.sendConfig(doc, panel);
          panel.webview.postMessage({
            type: "init",
            text: doc.text,
            revision: doc.revision,
            catalog,
            ...this.config(doc),
          });
          this.validate(doc);
        }
        if (message.type === "edit" && typeof message.text === "string") {
          if (!Number.isInteger(message.baseRevision) || message.baseRevision !== doc.revision) {
            panel.webview.postMessage({ type: "editConflict", text: doc.text, revision: doc.revision, editId: message.editId });
          } else {
            this.edit(doc, message.text, panel);
            panel.webview.postMessage({ type: "editAccepted", revision: doc.revision, editId: message.editId });
          }
        }
        if (
          message.type === "clipboardWrite" &&
          typeof message.text === "string"
        ) {
          if (message.text.length > 16 * 1024 * 1024)
            throw Error("Clipboard object is too large");
          await vscode.env.clipboard.writeText(message.text);
          panel.webview.postMessage({
            type: "clipboardWritten",
            cutPath: message.cutPath,
            text: message.text,
          });
        }
        if (message.type === "clipboardRead")
          panel.webview.postMessage({
            type: "clipboardRead",
            text: await vscode.env.clipboard.readText(),
            target: message.target,
          });
        if (message.type === "resourcesDiscover") {
          try {
            if (typeof message.root !== "string" || !message.root.trim())
              throw Error("Choose a resource directory");
            panel.webview.postMessage({
              type: "resourcesDiscovered",
              ...(await discoverResources(
                path.resolve(
                  vscode.workspace.getWorkspaceFolder(doc.uri)?.uri.fsPath ||
                    path.dirname(doc.uri.fsPath),
                  message.root,
                ),
                message.layout || "archive",
              )),
            });
          } catch (e) {
            panel.webview.postMessage({
              type: "resourcesDiscovered",
              error: String(e),
            });
          }
        }
        if (message.type === "undo")
          await vscode.commands.executeCommand("undo", doc.uri);
        if (message.type === "redo")
          await vscode.commands.executeCommand("redo", doc.uri);
        if (message.type === "resources")
          panel.webview.postMessage({ type: "openResources" });
        if (message.type === "resourcesApply")
          await this.applyResources(doc, panel, message);
        if (message.type === "resourceBrowse") {
          const picked = await vscode.window.showOpenDialog({
            canSelectMany: false,
            canSelectFiles: false,
            canSelectFolders: true,
          });
          panel.webview.postMessage({
            type: "resourcePicked",
            requestId: message.requestId,
            path: picked?.[0]?.fsPath,
          });
        }
        if (message.type === "cancelRender") preview.cancel();
        if (message.type === "render") {
          await preview.render(
            doc,
            message.requestId,
            message.options || {},
            this.config(doc).resources,
            (result) => {
              this.resources.set(
                doc.uri,
                (result.errors || []).map((e: any) => {
                  const d = this.diagnostic(doc.text, e);
                  d.source = "Binary GIN resources";
                  return d;
                }),
              );
            },
          );
        }
      } catch (e) {
        panel.webview.postMessage({
          type: "error",
          message: String(e),
        });
      }
    });
  }
  async configureResources() {
    if (this.active) this.active.webview.postMessage({ type: "openResources" });
    else
      vscode.window.showInformationMessage(
        "Open a .bgin file to configure resources.",
      );
  }
  command(command: string) {
    this.active?.webview.postMessage({ type: "command", command });
  }
  async saveCustomDocument(doc: BginDocument) {
    try {
      await doc.save();
    } catch (e) {
      this.syntax.set(doc.uri, [
        this.diagnostic(
          doc.text,
          e instanceof RpcError ? e.detail : { message: String(e) },
        ),
      ]);
      throw e;
    }
  }
  async saveCustomDocumentAs(doc: BginDocument, destination: vscode.Uri) {
    try {
      await doc.save(destination);
    } catch (e) {
      this.syntax.set(doc.uri, [
        this.diagnostic(
          doc.text,
          e instanceof RpcError ? e.detail : { message: String(e) },
        ),
      ]);
      throw e;
    }
  }
  async revertCustomDocument(doc: BginDocument) {
    for (const p of doc.panels) this.previews.get(p)?.cancel();
    await doc.revert();
    this.validate(doc);
  }
  async backupCustomDocument(
    doc: BginDocument,
    context: vscode.CustomDocumentBackupContext,
  ) {
    await vscode.workspace.fs.writeFile(
      context.destination,
      Buffer.from(doc.text, "utf8"),
    );
    return {
      id: context.destination.toString(),
      delete: async () => {
        try {
          await vscode.workspace.fs.delete(context.destination);
        } catch {}
      },
    };
  }
}

export function editorGuideUrl(language: string) {
  return `https://octane-loader.ru/${language === "ru" ? "ru" : "en"}/guide/octane-devtools/bgin-editor/v0.6.3/`;
}

/** Reference page of one engine class, or of the gin namespace without one. */
export function documentationUrl(language: string, target: unknown) {
  const page = typeof target === "string" && /^gin(::\w+)+$/.test(target)
    ? `view=class&name=${target}`
    : "mode=namespaces&view=namespace&name=gin";
  return `https://octane-loader.ru/${language === "ru" ? "ru" : "en"}/reference/?${page}`;
}

export function activate(context: vscode.ExtensionContext) {
  const backend = new Backend(context),
    provider = new Provider(context, backend);
  const converter = new ConverterView(context, backend);
  const windowId = randomUUID();
  const bridge = new McpBridge({
    listDocuments: () => [...provider.documents.values()].map(doc => provider.snapshot(doc)),
    openDocument: file => provider.openSharedDocument(file),
    getDocument: id => { const doc = provider.documents.get(id); return doc && provider.snapshot(doc); },
    applyEdit: (id, text, revision, label, signal) => provider.applySharedEdit(id, text, revision, label, signal),
    saveDocument: (id, revision, signal) => provider.saveSharedDocument(id, revision, signal),
    getSettings: id => provider.sharedSettings(id),
    showRender: event => provider.showSharedRender(event),
  }, { discoveryFile: path.join(context.globalStorageUri.fsPath, "mcp", `bridge-${windowId}.json`), windowId });
  provider.bridge = bridge;
  converter.attachBridge(bridge, id => {
    const doc = provider.documents.get(id);
    if (doc) return vscode.commands.executeCommand("vscode.openWith", doc.uri, "bgin.editor", { preview: false });
  }, () => provider.sharedSettings());
  void bridge.start().catch(error => backend.output.appendLine(`MCP bridge: ${error}`));
  const syncExplorer = registerExplorerNew(context, backend.output);
  const setExplorer = async (enabled: boolean) => {
    await vscode.workspace.getConfiguration("bgin").update("windowsExplorerNewFile", enabled, vscode.ConfigurationTarget.Global);
    if (await syncExplorer()) {
      const ru = vscode.workspace.getConfiguration("bgin").get<string>("language", "en") === "ru";
      await vscode.window.showInformationMessage(enabled
        ? (ru ? "Проводник Windows: Создать → Binary GIN. Если пункт ещё не появился, откройте меню заново." : "Windows Explorer: New → Binary GIN. Reopen the menu if the entry has not appeared yet.")
        : (ru ? "Пункт создания BGIN в Проводнике отключён." : "Windows Explorer New BGIN entry disabled."));
    }
  };
  context.subscriptions.push(
    backend,
    { dispose: () => bridge.dispose() },
    vscode.window.registerWebviewViewProvider("bgin.converter", converter),
    vscode.commands.registerCommand("bgin.enableExplorerNewFile", () => setExplorer(true)),
    vscode.commands.registerCommand("bgin.disableExplorerNewFile", () => setExplorer(false)),
    vscode.window.registerCustomEditorProvider("bgin.editor", provider, {
      webviewOptions: { retainContextWhenHidden: true },
      supportsMultipleEditorsPerDocument: true,
    }),
    vscode.commands.registerCommand("bgin.refreshPreview", () =>
      provider.command("refreshPreview"),
    ),
    vscode.commands.registerCommand("bgin.togglePreview", () =>
      provider.command("togglePreview"),
    ),
    vscode.commands.registerCommand("bgin.expandPreview", () =>
      provider.command("expandPreview"),
    ),
    vscode.commands.registerCommand("bgin.resources", () =>
      provider.configureResources(),
    ),
    vscode.commands.registerCommand("bgin.newFile", newBginFile),
    vscode.commands.registerCommand("bgin.convertTexture", () => convertTexture(backend)),
  );
  return {
    provider,
    bridge,
    backend,
    discoverResources,
    scanBginFolder,
    saveResourceFolders,
    converter,
    documentationUrl,
    editorGuideUrl,
    runExplorerRegistration: (action: "install" | "remove" | "status", registryRoot?: string) => runExplorerRegistration(context, action, registryRoot),
  };
}
