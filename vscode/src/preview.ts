import * as vscode from "vscode";
import { Backend } from "./backend";
import { BginDocument } from "./document";

/** A cancellable preview worker cannot occupy the document/save worker. No queue. */
export class PreviewSession implements vscode.Disposable {
  private worker: Backend;
  private generation = 0;
  private requestId?: number;
  constructor(
    context: vscode.ExtensionContext,
    private panel: vscode.WebviewPanel,
  ) {
    this.worker = new Backend(context, "Binary GIN Preview");
  }
  async render(
    doc: BginDocument,
    requestId: number,
    options: any,
    resources: any,
    diagnostics: (result: any) => void,
  ) {
    if (this.requestId !== undefined) return;
    this.requestId = requestId;
    const generation = ++this.generation,
      revision = doc.revision;
    try {
      const result = await this.worker.call("render", {
        text: doc.text,
        options,
        resources,
        source: doc.uri.fsPath,
      });
      if (generation === this.generation && revision === doc.revision) {
        this.panel.webview.postMessage({
          type: "rendered",
          requestId,
          ...result,
        });
        diagnostics(result);
      }
    } catch (e) {
      if (generation === this.generation) {
        this.worker.restart();
        this.panel.webview.postMessage({
          type: "renderError",
          requestId,
          message: String(e),
        });
      }
    } finally {
      if (generation === this.generation) this.requestId = undefined;
    }
  }
  cancel(message = "Rendering stopped") {
    if (this.requestId === undefined) return;
    const requestId = this.requestId;
    this.requestId = undefined;
    ++this.generation;
    this.worker.restart();
    this.panel.webview.postMessage({
      type: "renderCancelled",
      requestId,
      message,
    });
  }
  dispose() {
    this.cancel();
    this.worker.dispose();
  }
}
