import * as fs from "node:fs/promises";
import * as path from "node:path";

/** Index headers only. Loading full resource documents belongs to the renderer. */
export async function scanBginFolder(folder: string) {
  const bindings: Record<string, string> = {},
    errors: string[] = [];
  const entries = [];
  for (const directory of [folder, path.join(folder, "gui")]) {
    try {
      for (const entry of await fs.readdir(directory, { withFileTypes: true }))
        entries.push({ entry, directory });
    } catch (error) {
      if (directory === folder) throw error;
    }
  }
  const seen = new Map<string, string>(),
    ambiguous = new Set<string>();
  for (const { entry, directory } of entries.sort((a, b) =>
    a.entry.name.localeCompare(b.entry.name),
  )) {
    if (!entry.isFile() || !entry.name.toLowerCase().endsWith(".bgin"))
      continue;
    const file = path.join(directory, entry.name);
    let stream;
    try {
      stream = await fs.open(file, "r");
      const header = Buffer.alloc(10),
        read = await stream.read(header, 0, 10, 0);
      if (read.bytesRead !== 10 || header.readUInt32LE(0) !== 0x000c1aaa)
        throw Error("Invalid BGIN header");
      let offset = 10, length = header.readUInt16LE(8);
      if (header.subarray(4, 10).equals(Buffer.from([8, 0, 68, 97, 116, 97]))) {
        const rest = Buffer.alloc(6);
        const next = await stream.read(rest, 0, 6, 10);
        if (next.bytesRead !== 6 || rest.toString("ascii", 0, 4) !== "base") throw Error("Invalid or truncated legacy BGIN header");
        length = rest.readUInt16LE(4);
        offset = 16;
      }
      const bytes = Buffer.alloc(length);
      const nameRead = await stream.read(bytes, 0, length, offset);
      if (nameRead.bytesRead !== length)
        throw Error("Truncated BGIN namespace");
      let name: string;
      try { name = new TextDecoder("utf-8", { fatal: true }).decode(bytes); }
      catch { throw Error("Invalid UTF-8 in BGIN namespace"); }
      if (!name || /[\\/\s\x00-\x1f]/.test(name))
        throw Error("Invalid BGIN namespace");
      const key = name.toLowerCase(),
        prior = seen.get(key);
      if (prior) {
        errors.push(
          `Duplicate BGIN namespace ${name}: ${path.basename(prior)}, ${entry.name}`,
        );
        ambiguous.add(key);
        continue;
      }
      seen.set(key, file);
      Object.defineProperty(bindings, name, {
        value: file,
        enumerable: true,
        configurable: true,
      });
    } catch (error) {
      errors.push(`${entry.name}: ${String(error)}`);
    } finally {
      await stream?.close();
    }
  }
  for (const name of Object.keys(bindings))
    if (ambiguous.has(name.toLowerCase())) delete bindings[name];
  return { bindings, errors };
}

/** Inspect the selected archive layout without reading textures or parsing BGIN trees. */
export async function discoverResources(root: string, layout: "archive" | "zdata" = "archive") {
  let base = path.resolve(root);
  if (!(await fs.stat(base)).isDirectory())
    throw Error("Resource root must be a directory");
  let texturePacks = "";
  if (layout === "zdata") {
    // Follow the known PAD hierarchy only; never recursively scan an entire dump.
    for (const packs of [path.join(base, "files", "assetpacks"), path.join(base, "assetpacks"), base]) {
      const entries = await directories(packs);
      if (!entries.includes("common_pack") && !entries.some((name) => /^textures_pack\d+$/.test(name))) continue;
      if (entries.some((name) => /^textures_pack\d+$/.test(name))) texturePacks = packs;
      const candidates: string[] = [];
      for (const version of await directories(path.join(packs, "common_pack"))) {
        if (!/^\d+$/.test(version)) continue;
        for (const revision of await directories(path.join(packs, "common_pack", version))) {
          if (!/^\d+$/.test(revision)) continue;
          const candidate = path.join(packs, "common_pack", version, revision, "assets", "data");
          if (await isDirectory(candidate)) candidates.push(candidate);
        }
      }
      if (candidates.length > 1) throw Error("Multiple common_pack versions found. Choose the required assets/data folder or configure folders separately.");
      if (candidates.length) base = candidates[0];
      break;
    }
  } else if (layout !== "archive") throw Error("Unknown resource layout");
  const resourceSettings = {
    assetRoot: base,
    bginRoot: "",
    textureRoot: "",
    fontRoot: "",
  };
  const notes: string[] = [];
  const hasRootBgin = (await fs.readdir(base, { withFileTypes: true })).some(
    (entry) => entry.isFile() && entry.name.toLowerCase().endsWith(".bgin"),
  );
  // A root containing BGIN files must retain both its own and gui namespaces.
  for (const folder of hasRootBgin ? [base] : [path.join(base, "gui"), base]) {
    try {
      const result = await scanBginFolder(folder);
      if (Object.keys(result.bindings).length || result.errors.length) {
        resourceSettings.bginRoot = folder;
        notes.push(
          `${Object.keys(result.bindings).length} BGIN namespaces found. Review and save.`,
          ...result.errors,
        );
        break;
      }
    } catch {
      /* An archive need not contain a gui folder. */
    }
  }
  if (!resourceSettings.bginRoot)
    notes.push("No BGIN files found in the archive root or gui folder.");
  for (const [key, folder] of [
    ["textureRoot", "textures_android"],
    ["fontRoot", "texter_fonts"],
  ] as const) {
    try {
      const candidate = path.join(base, folder);
      if ((await fs.stat(candidate)).isDirectory())
        resourceSettings[key] = candidate;
    } catch {
      notes.push("Folder not found: " + folder);
    }
  }
  if (texturePacks && !resourceSettings.textureRoot) {
    resourceSettings.textureRoot = texturePacks;
    notes.push("Texture JPK packs found. Only requested files are read; texture conversion is separate.");
  }
  if (layout === "zdata") notes.push("Partial zdata is supported. Missing folders can be selected separately; the full game archive is not required.");
  return { resourceSettings, notes };
}

async function directories(folder: string): Promise<string[]> {
  try { return (await fs.readdir(folder, { withFileTypes: true })).filter((entry) => entry.isDirectory()).map((entry) => entry.name).sort(); }
  catch { return []; }
}

async function isDirectory(folder: string) {
  try { return (await fs.stat(folder)).isDirectory(); }
  catch { return false; }
}
