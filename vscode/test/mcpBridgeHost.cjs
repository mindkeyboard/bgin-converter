// Real bridge fixture with a deliberately asynchronous document owner. No VS Code mock protocol.
const { buildSync } = require("esbuild");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");
const folder = fs.mkdtempSync(path.join(os.tmpdir(), "bgin-bridge-host-"));
const output = path.join(folder, "bridge.cjs");
buildSync({ entryPoints: [path.join(__dirname, "../src/mcpBridge.ts")], bundle: true, platform: "node", format: "cjs", outfile: output });
const { McpBridge } = require(output);
const documents = new Map([["doc-one", { documentId: "doc-one", path: path.join(folder, "test.bgin"), revision: 0, text: JSON.stringify({ name: "shared", screens: [{ type: "StackContainer", name: "main", children: [] }] }) }]]);
const renders = [];
let resourceRevision = 0;
const copy = document => structuredClone(document);
const host = {
  listDocuments: () => [...documents.values()].map(copy),
  openDocument: async name => {
    const document = [...documents.values()].find(document => document.path === name);
    if (!document) throw Error("Fixture path not found");
    return copy(document);
  },
  getDocument: id => documents.has(id) ? copy(documents.get(id)) : undefined,
  applyEdit: async (id, text, baseRevision, label, signal) => {
    await new Promise(resolve => setTimeout(resolve, 100));
    if (signal.aborted) throw Object.assign(Error("Cancelled before commit"), { code: "cancelled" });
    const doc = documents.get(id);
    if (doc.revision !== baseRevision) throw Object.assign(Error("Changed while validating"), { code: "revision_conflict" });
    JSON.parse(text);
    doc.text = text; doc.revision++;
    bridge.documentChanged(copy(doc), label);
    return copy(doc);
  },
  saveDocument: async (id, baseRevision, signal) => {
    if (signal.aborted) throw Error("cancelled");
    const doc = documents.get(id);
    if (doc.revision !== baseRevision) throw Object.assign(Error("stale save"), { code: "revision_conflict" });
    JSON.parse(doc.text);
    return copy(doc);
  },
  getSettings: () => ({ preview: {}, resources: {}, browserChannel: "", resourceRevision }),
  showRender: event => renders.push(event),
};
const bridge = new McpBridge(host, { discoveryFile: path.join(folder, "discovery.json") });
(async () => {
  await bridge.start();
  process.stdout.write(JSON.stringify({ discoveryFile: bridge.state().discoveryFile, document: host.listDocuments()[0] }) + "\n");
  const lines = readline.createInterface({ input: process.stdin });
  for await (const line of lines) {
    try {
      const request = JSON.parse(line);
      if (request.action === "user") {
        const doc = documents.get("doc-one");
        doc.text = request.text; doc.revision++;
        bridge.documentChanged(copy(doc));
      } else if (request.action === "pause") bridge.pauseSession(request.sessionId, request.paused);
      else if (request.action === "cancel") bridge.cancelOperation(request.sessionId, request.operationId);
      else if (request.action === "disconnect") bridge.disconnectSession(request.sessionId);
      else if (request.action === "resources") resourceRevision++;
      else if (request.action === "stop") break;
      process.stdout.write(JSON.stringify({ ok: true, state: bridge.state(), renders }) + "\n");
    } catch (error) { process.stdout.write(JSON.stringify({ error: error.message }) + "\n"); }
  }
  lines.close();
  process.stdin.destroy();
  await bridge.dispose();
  fs.rmSync(folder, { recursive: true, force: true });
})().catch(error => { process.stderr.write(error.stack + "\n"); process.exitCode = 1; });
