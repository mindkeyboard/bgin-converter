import * as vscode from "vscode";

export const resourceFolderKeys = [
  "assetRoot",
  "bginRoot",
  "textureRoot",
  "fontRoot",
] as const;
export type ResourceFolders = Record<
  (typeof resourceFolderKeys)[number],
  string
>;

export function resourceFolders(input: unknown): ResourceFolders {
  if (!input || typeof input !== "object" || Array.isArray(input))
    throw Error("Invalid resource folders");
  const values = input as Record<string, unknown>;
  return Object.fromEntries(
    resourceFolderKeys.map((key) => {
      const value = values[key] ?? "";
      if (
        typeof value !== "string" ||
        value.length > 8192 ||
        value.includes("\0")
      )
        throw Error("Invalid resource folder: " + key);
      return [key, value.trim()];
    }),
  ) as ResourceFolders;
}

/** Keep a durable draft before touching VS Code settings, which may have stale registration. */
export async function saveResourceFolders(
  cfg: Pick<vscode.WorkspaceConfiguration, "inspect" | "update">,
  state: Pick<vscode.Memento, "update">,
  key: string,
  folders: ResourceFolders,
  target: vscode.ConfigurationTarget,
) {
  await state.update(key, folders);
  try {
    if (!cfg.inspect("resourceFolders"))
      throw Error("bgin.resourceFolders is not registered");
    await cfg.update("resourceFolders", folders, target);
    await state.update(key, undefined);
    return "";
  } catch {
    // The fallback also covers read-only settings and remains effective after reopening the file.
    return "Resource folders saved for this workspace. VS Code Settings could not be updated. Run Developer: Reload Window after an extension update, then save again.";
  }
}
