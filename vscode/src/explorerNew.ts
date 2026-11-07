import * as vscode from "vscode";
import * as path from "node:path";
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";

export function explorerSupported() {
  return process.platform === "win32" && !vscode.env.remoteName;
}

export function runExplorerRegistration(
  context: vscode.ExtensionContext,
  action: "install" | "remove" | "status",
  registryRoot?: string,
): Promise<{ enabled: boolean; managed: boolean }> {
  if (!explorerSupported()) return Promise.reject(Error("Windows Explorer integration requires local VS Code on Windows."));
  // Extension hosts run Code.exe or the Electron helper inside resources/app.
  const codePath = [process.execPath, path.resolve(vscode.env.appRoot, "../..", "Code.exe"), path.resolve(vscode.env.appRoot, "../..", "Code - Insiders.exe")]
    .find((candidate) => existsSync(candidate) && !/node|helper/i.test(path.basename(candidate))) || process.execPath;
  const args = ["-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", context.asAbsolutePath("scripts/explorer-new.ps1"), "-Action", action, "-CodePath", codePath];
  if (registryRoot) args.push("-RegistryRoot", registryRoot);
  return new Promise((resolve, reject) => {
    execFile("powershell.exe", args, { windowsHide: true, timeout: 20000, encoding: "utf8" }, (error, stdout, stderr) => {
      if (error) reject(Error(stderr.trim() || error.message));
      else {
        try { resolve(JSON.parse(stdout.trim().replace(/^\uFEFF/, ""))); }
        catch { reject(Error("Windows Explorer registration returned an invalid response.")); }
      }
    });
  });
}

export function registerExplorerNew(context: vscode.ExtensionContext, output: vscode.OutputChannel) {
  let queue = Promise.resolve(true);
  const sync = () => {
    queue = queue.then(async () => {
      if (!explorerSupported()) throw Error("Windows Explorer integration requires local VS Code on Windows.");
      const enabled = vscode.workspace.getConfiguration("bgin").get<boolean>("windowsExplorerNewFile", true);
      const result = await runExplorerRegistration(context, enabled ? "install" : "remove");
      if (!enabled && result.enabled) throw Error("Another application owns the BGIN New menu entry. Its registration was preserved.");
      output.appendLine(`Windows Explorer New BGIN: ${JSON.stringify(result)}`);
      return true;
    }).catch((error) => {
      output.appendLine(`Windows Explorer: ${error.message}`);
      void vscode.window.showWarningMessage(`BGIN: ${error.message}`);
      return false;
    });
    return queue;
  };
  if (explorerSupported()) {
    context.subscriptions.push(vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration("bgin.windowsExplorerNewFile")) void sync();
    }));
    // Isolated extension-host tests must not change the real Explorer registration.
    if (context.extensionMode !== vscode.ExtensionMode.Test) void sync();
  }
  return sync;
}
