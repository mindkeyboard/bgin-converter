import * as vscode from "vscode";
import * as path from "node:path";
import { randomBytes } from "node:crypto";
import { Backend } from "./backend";
import { explorerSupported } from "./explorerNew";
import { McpBridge, BridgeState } from "./mcpBridge";
import { formatProfiles } from "./formatProfiles";

const ru: Record<string, string> = {
  "Empty BGIN draft has no document name. Set a name before editing and create the first screen before compiling.": "У пустого черновика BGIN нет названия. Перед редактированием задайте название, а перед сборкой создайте первый экран.",
  "Convert files": "Конвертация файлов", "Direction": "Направление",
  "Source file": "Исходный файл", "Output file": "Выходной файл",
  "Choose…": "Выбрать…", "Save as…": "Сохранить как…", "Convert": "Конвертировать",
  "Converting…": "Конвертация…", "Open result": "Открыть результат",
  "Create empty BGIN": "Создать пустой BGIN", "Windows Explorer": "Проводник Windows",
  "Add BGIN to the New menu": "Добавить BGIN в меню «Создать»",
  "Remove BGIN from the New menu": "Убрать BGIN из меню «Создать»",
  "Converts saved files. Save changes in the editor first.": "Конвертируются сохранённые файлы. Сначала сохраните правки в редакторе.",
  "Choose a source and an output file.": "Выберите исходный и выходной файлы.",
  "Source has unsaved changes. Save it before converting.": "В исходном файле есть несохранённые изменения. Сохраните его перед конвертацией.",
  "Output is open with unsaved changes. Save or close it first.": "Выходной файл открыт с несохранёнными изменениями. Сохраните или закройте его.",
  "Replace": "Заменить", "Cancel": "Отмена",
  "Replace the output file? Its previous contents will be kept in a .bak file.": "Заменить выходной файл? Его прежнее содержимое будет сохранено в файле .bak.",
  "Conversion complete": "Конвертация завершена", "Backup": "Резервная копия",
  "Explorer menu updated. Right-click a folder background → New → Binary GIN.": "Меню Проводника обновлено. Нажмите правой кнопкой в папке → Создать → Binary GIN.",
  "Explorer menu entry removed.": "Пункт меню Проводника удалён.",
  "MCP connections": "Подключения MCP", "No clients connected": "Нет подключённых клиентов",
  "Local bridge is starting…": "Локальный мост запускается…", "Copy connection path": "Копировать путь подключения",
  "Pause edits": "Приостановить правки", "Resume edits": "Разрешить правки", "Disconnect": "Отключить",
  "Stop operation": "Остановить операцию", "Open document": "Открыть документ", "Paused": "Правки приостановлены",
  "Connected": "Подключён", "Disconnected": "Отключён", "Target BGIN format": "Целевой формат BGIN",
  "running": "выполняется", "completed": "завершено", "failed": "ошибка", "cancelled": "отменено", "Recent actions": "Последние действия",
  "Copy client command": "Копировать команду клиента",
  "Copy MCP configuration": "Копировать настройки MCP",
  "Keep source format": "Сохранить формат исходника",
  "The selected mode changes BGIN encoding. Texture compression is checked separately; textures are not converted.": "Выбранный режим меняет запись BGIN. Сжатие текстур проверяется отдельно; текстуры не преобразуются.",
};

function escape(value: string) {
  return value.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]!);
}

export class ConverterView implements vscode.WebviewViewProvider {
  private view?: vscode.WebviewView;
  private source?: vscode.Uri;
  private destination?: vscode.Uri;
  private to: "json" | "bgin" | "bgin-to-bgin" = "json";
  private targetFormat = "";
  private bridge?: McpBridge;
  private bridgeState?: BridgeState;
  private openDocument?: (id: string) => unknown;
  private settings?: () => Record<string, unknown>;
  private activity: { key: string; text: string }[] = [];
  private busy = false;
  private result?: vscode.Uri;
  private status = "";
  private error = false;
  constructor(private context: vscode.ExtensionContext, private backend: Backend) {
    context.subscriptions.push(vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration("bgin.language") && this.view) this.render();
    }));
  }
  attachBridge(bridge: McpBridge, openDocument: (id: string) => unknown, settings: () => Record<string, unknown>) {
    this.bridge = bridge;
    this.bridgeState = bridge.state();
    this.openDocument = openDocument;
    this.settings = settings;
    this.context.subscriptions.push(bridge.onDidChange(state => {
      this.bridgeState = state;
      for (const session of state.sessions) if (session.operation) {
        const operation = session.operation, key = `${session.id}/${operation.id}/${operation.status}`;
        if (!this.activity.some(item => item.key === key)) this.activity.unshift({ key, text: `${session.name} · ${operation.name} · ${this.t(operation.status)}` });
      }
      this.activity = this.activity.slice(0, 12);
      this.render();
    }));
  }
  private t(text: string) {
    return vscode.workspace.getConfiguration("bgin").get<string>("language", "en") === "ru" ? ru[text] || text : text;
  }
  resolveWebviewView(view: vscode.WebviewView) {
    this.view = view;
    view.webview.options = { enableScripts: true, localResourceRoots: [] };
    view.onDidDispose(() => { this.view = undefined; }, null, this.context.subscriptions);
    view.webview.onDidReceiveMessage((message) => this.receive(message), null, this.context.subscriptions);
    this.render();
  }
  private async receive(message: { type: string; to?: string; format?: string; sessionId?: string; operationId?: string; documentId?: string }) {
    if (message.type === "copyConnection" && this.bridgeState) { await vscode.env.clipboard.writeText(this.bridgeState.discoveryFile); return; }
    if (message.type === "copyClientConfig" && this.bridgeState) {
      const command = path.join(this.context.extensionPath, "backend", process.platform === "win32" ? "bgin_backend.exe" : "bgin_backend");
      const args = ["--mcp", "--mode", "connected", "--editor-bridge", this.bridgeState.discoveryFile, "--client-name", "My assistant"];
      await vscode.env.clipboard.writeText(JSON.stringify({ mcpServers: { bgin: { command, args } } }, null, 2));
      return;
    }
    if (message.type === "copyClientCommand" && this.bridgeState) {
      const executable = path.join(this.context.extensionPath, "backend", process.platform === "win32" ? "bgin_backend.exe" : "bgin_backend");
      const args = ["--mcp", "--mode", "connected", "--editor-bridge", this.bridgeState.discoveryFile, "--client-name", "My assistant"];
      const command = process.platform === "win32"
        ? "& " + [executable, ...args].map(value => "'" + value.replace(/'/g, "''") + "'").join(" ")
        : [executable, ...args].map(value => "'" + value.replace(/'/g, "'\\''") + "'").join(" ");
      await vscode.env.clipboard.writeText(command);
      return;
    }
    if (message.type === "mcpOpen" && message.documentId) { await this.openDocument?.(message.documentId); return; }
    if (message.sessionId && this.bridge) {
      if (message.type === "mcpPause") this.bridge.pauseSession(message.sessionId, true);
      if (message.type === "mcpResume") this.bridge.pauseSession(message.sessionId, false);
      if (message.type === "mcpDisconnect") this.bridge.disconnectSession(message.sessionId);
      if (message.type === "mcpStop") this.bridge.cancelOperation(message.sessionId, message.operationId);
      this.render();
      return;
    }
    if (this.busy) return;
    try {
      if (message.type === "format" && (message.format === "" || formatProfiles.some(profile => profile.id === message.format))) {
        this.targetFormat = message.format || "";
      } else if (message.type === "direction" && (message.to === "json" || message.to === "bgin" || message.to === "bgin-to-bgin")) {
        this.to = message.to;
        this.source = this.destination = this.result = undefined;
        this.status = "";
        this.render();
      } else if (message.type === "source") {
        const chosen = await vscode.window.showOpenDialog({ canSelectMany: false, canSelectFolders: false, filters: this.to !== "bgin" ? { "Binary GIN": ["bgin"] } : { JSON: ["json"] } });
        if (chosen?.[0]) {
          this.source = chosen[0];
          this.destination = undefined;
          this.result = undefined;
          this.status = "";
          this.render();
        }
      } else if (message.type === "destination") {
        const suggested = this.source?.with({ path: this.source.path.replace(/\.[^/.]+$/, "") + (this.to === "bgin-to-bgin" ? ".converted.bgin" : "." + this.to) });
        const chosen = await vscode.window.showSaveDialog({ defaultUri: this.destination || suggested, filters: this.to === "json" ? { JSON: ["json"] } : { "Binary GIN": ["bgin"] } });
        if (chosen) { this.destination = chosen; this.status = ""; this.result = undefined; this.render(); }
      } else if (message.type === "convert") {
        if (!this.source || !this.destination) throw Error(this.t("Choose a source and an output file."));
        this.busy = true;
        this.error = false;
        this.status = this.t("Converting…");
        this.result = undefined;
        this.render();
        const saved = await this.convert(this.source, this.destination, this.to === "json" ? "json" : "bgin", this.targetFormat || undefined);
        if (saved) {
          this.result = vscode.Uri.file(saved.path);
          this.status = `${this.t("Conversion complete")}: ${saved.path}` + (saved.backup ? `\n${this.t("Backup")}: ${saved.backup}` : "");
          if (saved.warnings?.length) this.status += "\n" + saved.warnings.map((warning: { message: string }) => this.t(warning.message)).join("\n");
        } else this.status = "";
      } else if (message.type === "open" && this.result) {
        await vscode.commands.executeCommand(this.to !== "json" ? "vscode.openWith" : "vscode.open", this.result, ...(this.to !== "json" ? ["bgin.editor"] : []));
      } else if (message.type === "new") {
        await vscode.commands.executeCommand("bgin.newFile");
      } else if (message.type === "enable" || message.type === "disable") {
        await vscode.commands.executeCommand(message.type === "enable" ? "bgin.enableExplorerNewFile" : "bgin.disableExplorerNewFile");
      }
    } catch (error: any) {
      this.status = error.message;
      this.error = true;
      this.backend.output.appendLine(`Conversion: ${error.stack || error}`);
    } finally {
      this.busy = false;
      this.render();
    }
  }
  async convert(source: vscode.Uri, destination: vscode.Uri, to: "json" | "bgin", targetFormat?: string) {
    if (source.scheme !== "file" || destination.scheme !== "file") throw Error("Conversion requires local files.");
    const normalized = (uri: vscode.Uri) => process.platform === "win32" ? path.resolve(uri.fsPath).toLowerCase() : path.resolve(uri.fsPath);
    if (normalized(source) === normalized(destination)) throw Error("Source and destination must be different files.");
    if (vscode.workspace.textDocuments.some((doc) => doc.isDirty && doc.uri.toString() === source.toString()) || this.isCustomDirty(source)) throw Error(this.t("Source has unsaved changes. Save it before converting."));
    if (vscode.workspace.textDocuments.some((doc) => doc.isDirty && doc.uri.toString() === destination.toString()) || this.isCustomDirty(destination)) throw Error(this.t("Output is open with unsaved changes. Save or close it first."));
    let expected: Uint8Array | undefined;
    try {
      if ((await vscode.workspace.fs.stat(destination)).size > 64 * 1024 * 1024) throw Error("Destination exceeds the 64 MiB conversion limit. Choose a new file.");
      expected = await vscode.workspace.fs.readFile(destination);
    }
    catch (error: any) { if (error.code !== "FileNotFound" && error.code !== "ENOENT") throw error; }
    if (expected !== undefined) {
      const replace = this.t("Replace");
      if (await vscode.window.showWarningMessage(this.t("Replace the output file? Its previous contents will be kept in a .bak file."), { modal: true }, replace) !== replace) return;
    }
    return vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "BGIN → " + to.toUpperCase() }, () => this.backend.call("convert", {
      source: source.fsPath, destination: destination.fsPath, to, overwrite: expected !== undefined,
      expected: expected !== undefined ? Buffer.from(expected).toString("base64") : undefined,
      target_format: targetFormat,
      resources: this.settings?.().resources || {},
    }));
  }
  private isCustomDirty(uri: vscode.Uri) {
    return vscode.window.tabGroups.all.some((group) => group.tabs.some((tab) => tab.isDirty && tab.input instanceof vscode.TabInputCustom && tab.input.uri.toString() === uri.toString()));
  }
  private render() {
    if (!this.view) return;
    this.view.title = "Binary GIN";
    const nonce = randomBytes(16).toString("hex");
    const t = (s: string) => escape(this.t(s));
    this.view.webview.html = `<!DOCTYPE html><html lang="${vscode.workspace.getConfiguration("bgin").get("language", "en")}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}'"><style nonce="${nonce}">
body{padding:12px 16px;font:var(--vscode-font-size)/1.5 var(--vscode-font-family);color:var(--vscode-foreground)}h2{font-size:13px;margin:0 0 12px}p{color:var(--vscode-descriptionForeground)}label{display:block;margin:12px 0 4px}input,select,button{box-sizing:border-box;width:100%;font:inherit;border-radius:2px;padding:6px 8px}input,select{border:1px solid var(--vscode-input-border,transparent);background:var(--vscode-input-background);color:var(--vscode-input-foreground);min-width:0}button{cursor:pointer;margin-top:6px;border:1px solid transparent;color:var(--vscode-button-foreground);background:var(--vscode-button-background)}button:hover{background:var(--vscode-button-hoverBackground)}button.secondary{background:var(--vscode-button-secondaryBackground);color:var(--vscode-button-secondaryForeground)}button:disabled{opacity:.5;cursor:default}:focus-visible{outline:1px solid var(--vscode-focusBorder);outline-offset:2px}hr{border:0;border-top:1px solid var(--vscode-panel-border);margin:20px 0}#status{white-space:pre-wrap;overflow-wrap:anywhere;color:${this.error ? "var(--vscode-errorForeground)" : "var(--vscode-foreground)"}}
</style></head><body>${this.connections()}<hr><h2>${t("Convert files")}</h2><p>${t("Converts saved files. Save changes in the editor first.")}</p>
<label for="direction">${t("Direction")}</label><select id="direction" ${this.busy ? "disabled" : ""}><option value="json" ${this.to === "json" ? "selected" : ""}>BGIN → JSON</option><option value="bgin" ${this.to === "bgin" ? "selected" : ""}>JSON → BGIN</option><option value="bgin-to-bgin" ${this.to === "bgin-to-bgin" ? "selected" : ""}>BGIN → BGIN</option></select>
${this.to !== "json" ? `<label for="format">${t("Target BGIN format")}</label><select id="format"><option value="">${t("Keep source format")}</option>${formatProfiles.map(profile => `<option value="${profile.id}" ${this.targetFormat === profile.id ? "selected" : ""}>${profile.label}</option>`).join("")}</select><p>${t("The selected mode changes BGIN encoding. Texture compression is checked separately; textures are not converted.")}</p>` : ""}
<label for="source">${t("Source file")}</label><input id="source" readonly value="${escape(this.source?.fsPath || "")}" title="${escape(this.source?.fsPath || "")}"><button class="secondary" data-action="source">${t("Choose…")}</button>
<label for="destination">${t("Output file")}</label><input id="destination" readonly value="${escape(this.destination?.fsPath || "")}" title="${escape(this.destination?.fsPath || "")}"><button class="secondary" data-action="destination">${t("Save as…")}</button>
<button data-action="convert" ${this.busy || !this.source || !this.destination ? "disabled" : ""}>${t(this.busy ? "Converting…" : "Convert")}</button><p id="status" role="status" aria-live="polite">${escape(this.status)}</p>${this.result ? `<button class="secondary" data-action="open">${t("Open result")}</button>` : ""}
<hr><button class="secondary" data-action="new">${t("Create empty BGIN")}</button>${explorerSupported() ? `<hr><h2>${t("Windows Explorer")}</h2><button class="secondary" data-action="enable">${t("Add BGIN to the New menu")}</button><button class="secondary" data-action="disable">${t("Remove BGIN from the New menu")}</button>` : ""}
<script nonce="${nonce}">const api=acquireVsCodeApi();document.querySelectorAll('[data-action]').forEach(button=>{if(!button.dataset.action.startsWith('mcp')&&!button.dataset.action.startsWith('copy'))button.disabled ||= ${this.busy};button.addEventListener('click',()=>api.postMessage({type:button.dataset.action,sessionId:button.dataset.session,operationId:button.dataset.operation,documentId:button.dataset.document}));});document.getElementById('direction').addEventListener('change',event=>api.postMessage({type:'direction',to:event.target.value}));document.getElementById('format')?.addEventListener('change',event=>api.postMessage({type:'format',format:event.target.value}));</script></body></html>`;
  }
  private connections() {
    const t = (text: string) => escape(this.t(text));
    const state = this.bridgeState;
    return `<section><h2>${t("MCP connections")}</h2><p style="overflow-wrap:anywhere">${state?.running ? escape(state.endpoint) : t("Local bridge is starting…")}</p>${state?.running ? `<button class="secondary" data-action="copyConnection">${t("Copy connection path")}</button><button class="secondary" data-action="copyClientCommand">${t("Copy client command")}</button><button class="secondary" data-action="copyClientConfig">${t("Copy MCP configuration")}</button><p style="overflow-wrap:anywhere"><small>${escape(state.discoveryFile)}</small></p>` : ""}${state?.sessions.length ? state.sessions.map(session => `<article style="border-top:1px solid var(--vscode-panel-border);margin-top:12px;padding-top:8px;overflow-wrap:anywhere"><strong>${escape(session.name)}</strong><p>${t(session.connected ? session.paused ? "Paused" : "Connected" : "Disconnected")}${session.operation ? ` · ${escape(session.operation.name)} · ${t(session.operation.status)}` : ""}</p>${session.operation?.documentId ? `<button class="secondary" data-action="mcpOpen" data-document="${escape(session.operation.documentId)}">${t("Open document")}</button>` : ""}${session.connected ? `<button class="secondary" data-action="${session.paused ? "mcpResume" : "mcpPause"}" data-session="${escape(session.id)}">${t(session.paused ? "Resume edits" : "Pause edits")}</button>${session.operation?.status === "running" ? `<button class="secondary" data-action="mcpStop" data-session="${escape(session.id)}" data-operation="${escape(session.operation.id)}">${t("Stop operation")}</button>` : ""}<button class="secondary" data-action="mcpDisconnect" data-session="${escape(session.id)}">${t("Disconnect")}</button>` : ""}</article>`).join("") : `<p>${t("No clients connected")}</p>`}${this.activity.length ? `<details><summary>${t("Recent actions")}</summary>${this.activity.map(item => `<p style="overflow-wrap:anywhere"><small>${escape(item.text)}</small></p>`).join("")}</details>` : ""}</section>`;
  }
}
