import * as vscode from "vscode";
import { open } from "node:fs/promises";
import { Backend, RpcError } from "./backend";

/** Empty editor drafts are not binary documents until their first screen is created. */
export function emptyDocumentText() {
  return JSON.stringify({ screens: [] }, null, 2) + "\n";
}

export const EMPTY_DRAFT_WARNING = "Empty BGIN draft has no document name. Set a name before editing.";

export function requiresDocumentName(text: string) {
  try {
    const doc = JSON.parse(text);
    return doc && typeof doc === "object" && Array.isArray(doc.screens) &&
      (typeof doc.name !== "string" || !doc.name.trim());
  } catch { return false; }
}

export async function readDocumentText(uri: vscode.Uri, backend: Backend) {
  if (uri.scheme === "untitled") return emptyDocumentText();
  const bytes = await vscode.workspace.fs.readFile(uri);
  if (bytes.byteLength === 0) return emptyDocumentText();
  // Nonempty invalid input must still fail the binary decoder.
  return (
    await backend.call("decode", {
      data: Buffer.from(bytes).toString("base64"),
    })
  ).text as string;
}

export function isUnnamedEmptyDraft(text: string) {
  const document = JSON.parse(text);
  return document && !Object.hasOwn(document, "name") && Array.isArray(document.screens) && document.screens.length === 0;
}

export function requireFirstScreen(text: string) {
  const document = JSON.parse(text);
  if (isUnnamedEmptyDraft(text)) return;
  if (Array.isArray(document?.screens) && document.screens.length === 0)
    throw new RpcError({
      message: "Create a screen with New screen before saving this BGIN file.",
      path: "/screens",
    });
}

export async function newBginFile() {
  const uri = await vscode.window.showSaveDialog({
    title: "New Binary GIN file",
    saveLabel: "Create BGIN",
    filters: { "Binary GIN": ["bgin"] },
  });
  if (!uri) return;
  if (uri.scheme !== "file")
    throw Error("New BGIN files require a local filesystem.");
  try {
    // Exclusive creation prevents an existing file from being truncated after the dialog closes.
    const handle = await open(uri.fsPath, "wx");
    await handle.close();
  } catch (error: any) {
    if (error.code !== "EEXIST") throw error;
    if ((await vscode.workspace.fs.stat(uri)).size > 0) {
      await vscode.window.showErrorMessage(
        "Choose a new filename. The existing file has not been changed.",
      );
      return;
    }
  }
  await vscode.commands.executeCommand("vscode.openWith", uri, "bgin.editor");
}
