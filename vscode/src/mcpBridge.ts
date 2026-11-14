import { createHash, randomBytes, randomUUID, timingSafeEqual } from "node:crypto";
import { promises as fs } from "node:fs";
import * as http from "node:http";
import * as path from "node:path";

/** The extension owns this text, including temporarily invalid, unsaved JSON. */
export interface BridgeDocument {
  documentId: string;
  path: string;
  text: string;
  revision: number;
}

export interface BridgeRender {
  sessionId: string;
  clientName: string;
  operationId: string;
  documentId: string;
  revision: number;
  stale: boolean;
  images: { data: string; mimeType: string }[];
  metadata: unknown;
}

export interface BridgeHost {
  listDocuments(): BridgeDocument[];
  openDocument(path: string): Promise<BridgeDocument>;
  getDocument(documentId: string): BridgeDocument | undefined;
  applyEdit(documentId: string, text: string, baseRevision: number, label: string, signal: AbortSignal): Promise<BridgeDocument>;
  saveDocument(documentId: string, baseRevision: number, signal: AbortSignal): Promise<BridgeDocument>;
  getSettings(documentId?: string): Record<string, unknown>;
  showRender(event: BridgeRender): Promise<void> | void;
}

export interface BridgeOperationState {
  id: string;
  name: string;
  documentId?: string;
  status: "running" | "completed" | "failed" | "cancelled";
  startedAt: string;
}

export interface BridgeSessionState {
  id: string;
  name: string;
  paused: boolean;
  connected: boolean;
  operation?: BridgeOperationState;
}

export interface BridgeState {
  running: boolean;
  discoveryFile: string;
  endpoint: string;
  windowId: string;
  sessions: BridgeSessionState[];
}

interface Session {
  state: BridgeSessionState;
  operations: Map<string, { state: BridgeOperationState; controller: AbortController }>;
  results: Map<string, { fingerprint: string; inputKey?: string; result: unknown }>;
}

class BridgeError extends Error {
  constructor(readonly code: string, message: string, readonly details?: unknown) {
    super(message);
  }
}

function nonempty(value: unknown, label: string): string {
  if (typeof value !== "string" || !value || value.length > 32768) throw new BridgeError("invalid_request", `${label} must be a nonempty string`);
  return value;
}

function revision(value: unknown): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) throw new BridgeError("invalid_request", "baseRevision must be a nonnegative integer");
  return value as number;
}

/** Loopback transport only: every MCP session shares the extension's document owner. */
export class McpBridge {
  private readonly token = randomBytes(32).toString("hex");
  private readonly sessions = new Map<string, Session>();
  private readonly listeners = new Set<(state: BridgeState) => void>();
  private readonly changes: { sequence: number; documentId: string; revision: number; origin: string; path: string }[] = [];
  private sequence = 0;
  private server?: http.Server;
  private endpoint = "";
  readonly windowId: string;

  constructor(private readonly host: BridgeHost, private readonly options: { discoveryFile: string; windowId?: string }) {
    this.windowId = options.windowId || randomUUID();
  }

  async start(): Promise<void> {
    if (this.server) return;
    const server = http.createServer((request, response) => void this.receive(request, response));
    await new Promise<void>((resolve, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", () => {
        server.off("error", reject);
        resolve();
      });
    });
    this.server = server;
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("Bridge did not receive a TCP address");
    this.endpoint = `http://127.0.0.1:${address.port}/rpc`;
    const descriptor = { version: 1, endpoint: this.endpoint, token: this.token, windowId: this.windowId, pid: process.pid };
    try {
      await fs.mkdir(path.dirname(this.options.discoveryFile), { recursive: true });
      const temporary = this.options.discoveryFile + "." + randomUUID() + ".tmp";
      await fs.writeFile(temporary, JSON.stringify(descriptor), { mode: 0o600 });
      await fs.rename(temporary, this.options.discoveryFile);
    } catch (error) {
      await new Promise<void>(resolve => server.close(() => resolve()));
      this.server = undefined;
      throw error;
    }
    this.emit();
  }

  onDidChange(listener: (state: BridgeState) => void): { dispose(): void } {
    this.listeners.add(listener);
    return { dispose: () => this.listeners.delete(listener) };
  }

  state(): BridgeState {
    return {
      running: !!this.server,
      discoveryFile: this.options.discoveryFile,
      endpoint: this.endpoint,
      windowId: this.windowId,
      sessions: [...this.sessions.values()].map(session => structuredClone(session.state)),
    };
  }

  documentChanged(document: BridgeDocument, origin = "user"): void {
    this.changes.push({ sequence: ++this.sequence, documentId: document.documentId, revision: document.revision, origin, path: document.path });
    if (this.changes.length > 1000) this.changes.shift();
    this.emit();
  }

  pauseSession(id: string, paused: boolean): void {
    this.session(id).state.paused = paused;
    if (paused) this.cancelOperation(id);
    this.emit();
  }

  disconnectSession(id: string): void {
    const session = this.session(id, true);
    for (const operation of session.operations.values()) operation.controller.abort();
    session.state.connected = false;
    if (session.state.operation?.status === "running") session.state.operation.status = "cancelled";
    this.emit();
  }

  cancelOperation(id: string, operationId?: string): void {
    const session = this.session(id);
    for (const [key, operation] of session.operations) {
      if ((!operationId || key === operationId) && operation.state.status === "running") {
        operation.controller.abort();
        operation.state.status = "cancelled";
      }
    }
    this.emit();
  }

  async dispose(): Promise<void> {
    for (const session of this.sessions.values()) for (const operation of session.operations.values()) operation.controller.abort();
    const server = this.server;
    this.server = undefined;
    if (server) await new Promise<void>(resolve => server.close(() => resolve()));
    try {
      const descriptor = JSON.parse(await fs.readFile(this.options.discoveryFile, "utf8"));
      if (descriptor.token === this.token) await fs.unlink(this.options.discoveryFile);
    } catch {}
    this.emit();
    this.listeners.clear();
  }

  private emit(): void {
    const state = this.state();
    for (const listener of this.listeners) listener(state);
  }

  private session(id: string, disconnected = false): Session {
    const session = this.sessions.get(id);
    if (!session || (!disconnected && !session.state.connected)) throw new BridgeError("disconnected", "The editor session was disconnected; reconnect explicitly");
    return session;
  }

  private document(id: unknown): BridgeDocument {
    const document = this.host.getDocument(nonempty(id, "documentId"));
    if (!document) throw new BridgeError("document_closed", "The live document was closed; open it again");
    return document;
  }

  private checkRevision(document: BridgeDocument, expected: unknown): void {
    if (document.revision !== revision(expected)) throw new BridgeError("revision_conflict", "The document changed; read the live text before retrying", { document });
  }

  private operation(session: Session, id: unknown, writing = false) {
    if (writing && session.state.paused) throw new BridgeError("paused", "The user paused this client's edits");
    const operation = session.operations.get(nonempty(id, "operationId"));
    if (!operation) throw new BridgeError("invalid_operation", "Begin an operation before applying or publishing its result");
    if (operation.controller.signal.aborted) throw new BridgeError("cancelled", "The user cancelled this operation");
    return operation;
  }

  private async dispatch(method: string, params: any, sessionId?: string): Promise<unknown> {
    if (method === "connect") {
      if (this.sessions.size >= 64) {
        for (const [id, candidate] of this.sessions) if (!candidate.state.connected) this.sessions.delete(id);
        if (this.sessions.size >= 64) throw new BridgeError("session_limit", "Too many editor sessions");
      }
      const id = randomUUID();
      const name = nonempty(params.name, "name").slice(0, 160);
      this.sessions.set(id, { state: { id, name, paused: false, connected: true }, operations: new Map(), results: new Map() });
      this.emit();
      return { sessionId: id, windowId: this.windowId, mode: "connected", capabilities: { liveDocuments: true, revisionChecks: true, changeFeed: true, renderGallery: true } };
    }
    const session = this.session(nonempty(sessionId, "sessionId"));
    switch (method) {
      case "documents/list": return { documents: this.host.listDocuments().map(document => ({ documentId: document.documentId, path: document.path, revision: document.revision })) };
      case "documents/open": return this.host.openDocument(nonempty(params.path, "path"));
      case "documents/read": return this.document(params.documentId);
      case "documents/changes": return { documents: this.host.listDocuments().map(document => ({ documentId: document.documentId, path: document.path, revision: document.revision })) };
      case "settings/read": return this.host.getSettings(params.documentId);
      case "documents/result": {
        const previous = session.results.get(nonempty(params.operationId, "operationId"));
        if (!previous) return null;
        if (previous.inputKey !== params.inputKey) throw new BridgeError("operation_reused", "An operationId cannot be reused with another patch");
        return previous.result;
      }
      case "sessions/disconnect": this.disconnectSession(session.state.id); return { disconnected: true };
      case "operations/begin": {
        const id = nonempty(params.operationId, "operationId");
        const existing = session.operations.get(id);
        if (existing) return existing.state;
        if (session.operations.size >= 256) {
          for (const [key, operation] of session.operations) if (operation.state.status !== "running") session.operations.delete(key);
          if (session.operations.size >= 256) throw new BridgeError("operation_limit", "Too many running operations");
        }
        const state: BridgeOperationState = { id, name: nonempty(params.name, "name").slice(0, 160), documentId: params.documentId, status: "running", startedAt: new Date().toISOString() };
        session.operations.set(id, { state, controller: new AbortController() });
        session.state.operation = state;
        this.emit();
        return state;
      }
      case "operations/check": return this.operation(session, params.operationId).state;
      case "operations/finish": {
        const operation = session.operations.get(nonempty(params.operationId, "operationId"));
        if (!operation) throw new BridgeError("invalid_operation", "Unknown operation");
        if (operation.state.status === "running") operation.state.status = params.failed ? "failed" : "completed";
        this.emit();
        return operation.state;
      }
      case "documents/edit":
      case "documents/save": {
        const id = nonempty(params.operationId, "operationId");
        const fingerprint = createHash("sha256").update(JSON.stringify({ method, documentId: params.documentId, text: params.text, baseRevision: params.baseRevision })).digest("hex");
        const old = session.results.get(id);
        if (old) {
          if (old.fingerprint !== fingerprint) throw new BridgeError("operation_reused", "An operationId cannot be reused for another edit or save");
          return old.result;
        }
        const operation = this.operation(session, id, true);
        const document = this.document(params.documentId);
        this.checkRevision(document, params.baseRevision);
        if (method === "documents/edit" && typeof params.text !== "string") throw new BridgeError("invalid_request", "text must be a string");
        const result = method === "documents/edit"
          ? await this.host.applyEdit(document.documentId, params.text, document.revision, `MCP: ${session.state.name}`, operation.controller.signal)
          : await this.host.saveDocument(document.documentId, document.revision, operation.controller.signal);
        session.results.set(id, { fingerprint, inputKey: params.inputKey, result });
        // Keep the idempotency horizon bounded without retaining entire old documents.
        if (session.results.size > 256) session.results.delete(session.results.keys().next().value!);
        operation.state.status = "completed";
        this.emit();
        return result;
      }
      case "renders/publish": {
        const operation = this.operation(session, params.operationId);
        const document = this.document(params.documentId);
        if (!Array.isArray(params.images) || params.images.length > 4 || params.images.some((image: any) => image?.mimeType !== "image/png" || typeof image.data !== "string")) throw new BridgeError("invalid_request", "Supply at most four PNG sheets");
        const event: BridgeRender = { sessionId: session.state.id, clientName: session.state.name, operationId: params.operationId, documentId: document.documentId, revision: revision(params.revision), stale: document.revision !== params.revision, images: params.images, metadata: params.metadata };
        if (operation.controller.signal.aborted) throw new BridgeError("cancelled", "The render was cancelled");
        await this.host.showRender(event);
        return { visible: true, stale: event.stale, revision: document.revision };
      }
      default: throw new BridgeError("unknown_method", `Unknown editor bridge method: ${method}`);
    }
  }

  private async receive(request: http.IncomingMessage, response: http.ServerResponse): Promise<void> {
    response.setHeader("Content-Type", "application/json; charset=utf-8");
    response.setHeader("Cache-Control", "no-store");
    // Browser origins never participate in this local stdio-to-editor protocol.
    const auth = request.headers.authorization || "";
    const expected = "Bearer " + this.token;
    if (request.url !== "/rpc" || request.method !== "POST" || request.headers.origin || Buffer.byteLength(auth) !== Buffer.byteLength(expected) || !timingSafeEqual(Buffer.from(auth), Buffer.from(expected))) {
      response.statusCode = 403;
      response.end(JSON.stringify({ error: { code: "forbidden", message: "Editor bridge authentication failed" } }));
      return;
    }
    let input: any;
    try {
      let size = 0;
      const chunks: Buffer[] = [];
      for await (const chunk of request) {
        const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
        size += buffer.length;
        if (size > 96 * 1024 * 1024) throw new BridgeError("request_limit", "Request exceeds 96 MiB");
        chunks.push(buffer);
      }
      input = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      if (!input || typeof input.method !== "string" || !input.params || typeof input.params !== "object" || Array.isArray(input.params)) throw new BridgeError("invalid_request", "Supply method and params");
      const result = await this.dispatch(input.method, input.params, input.sessionId);
      response.end(JSON.stringify({ result, ...this.changeEnvelope(input.cursor) }));
    } catch (error: any) {
      response.end(JSON.stringify({ error: { code: error.code || "editor_error", message: error.message || String(error), details: error.details }, ...this.changeEnvelope(input?.cursor) }));
    }
  }

  private changeEnvelope(cursor: unknown) {
    const since = Number.isSafeInteger(cursor) && (cursor as number) >= 0 ? cursor as number : this.sequence;
    return { cursor: this.sequence, changes: this.changes.filter(change => change.sequence > since), changesTruncated: this.changes.length > 0 && since < this.changes[0].sequence - 1 };
  }
}
