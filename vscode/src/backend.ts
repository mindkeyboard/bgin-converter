import * as vscode from "vscode";
import { spawn, ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";
import * as path from "node:path";

export class RpcError extends Error {
  constructor(
    public detail: {
      message: string;
      path?: string;
      line?: number;
      column?: number;
    },
  ) {
    super(detail.message);
  }
}

export class Backend implements vscode.Disposable {
  private process?: ChildProcessWithoutNullStreams;
  private next = 0;
  private pending = new Map<
    number,
    {
      resolve: (r: any) => void;
      reject: (e: Error) => void;
      timer: NodeJS.Timeout;
    }
  >();
  readonly output: vscode.OutputChannel;
  constructor(
    private context: vscode.ExtensionContext,
    channel = "Binary GIN",
  ) {
    this.output = vscode.window.createOutputChannel(channel);
  }
  private start() {
    if (!vscode.workspace.isTrusted)
      throw new Error("The BGIN worker requires a trusted workspace.");
    if (this.process) return;
    const executable = path.join(
      this.context.extensionPath,
      "backend",
      process.platform === "win32" ? "bgin_backend.exe" : "bgin_backend",
    );
    const proc = spawn(executable, [], {
      windowsHide: true,
      stdio: "pipe",
    });
    this.process = proc;
    createInterface({ input: proc.stdout }).on("line", (line) => {
      try {
        const message = JSON.parse(line),
          waiter = this.pending.get(message.id);
        if (!waiter) return;
        clearTimeout(waiter.timer);
        this.pending.delete(message.id);
        if (message.error) waiter.reject(new RpcError(message.error));
        else waiter.resolve(message.result);
      } catch (e) {
        this.output.appendLine(String(e));
      }
    });
    proc.stderr.on("data", (data) => this.output.append(data.toString()));
    const failed = (message: string) => {
      if (this.process !== proc) return;
      this.process = undefined;
      this.output.appendLine(message);
      for (const w of this.pending.values()) {
        clearTimeout(w.timer);
        w.reject(new Error(message));
      }
      this.pending.clear();
    };
    proc.on("error", (e) => failed(`Unable to start the BGIN worker. Reinstall Binary GIN Editor. ${e.message}`));
    proc.stdin.on("error", (e) => failed(`Unable to write to the BGIN worker. ${e.message}`));
    proc.on("close", (code, signal) =>
      failed(`BGIN worker exited (${code ?? signal}).`),
    );
  }
  call(method: string, params: any = {}): Promise<any> {
    this.start();
    return new Promise((resolve, reject) => {
      const id = ++this.next;
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error("BGIN request timed out."));
      }, 60000);
      this.pending.set(id, { resolve, reject, timer });
      this.process!.stdin.write(
        JSON.stringify({ id, method, params }) + "\n",
        (error) => {
          if (error) {
            clearTimeout(timer);
            this.pending.delete(id);
            reject(error);
          }
        },
      );
    });
  }
  restart() {
    const p = this.process;
    this.process = undefined;
    p?.kill();
    for (const w of this.pending.values()) {
      clearTimeout(w.timer);
      w.reject(new Error("BGIN worker restarted."));
    }
    this.pending.clear();
  }
  dispose() {
    this.restart();
    this.output.dispose();
  }
}
