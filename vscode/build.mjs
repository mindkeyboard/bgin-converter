import { build } from "esbuild";
import { spawnSync } from "node:child_process";
import { access, cp, mkdir, readFile, realpath, rm, writeFile } from "node:fs/promises";
import path from "node:path";
const backend = path.resolve(process.env.BGIN_BACKEND_DIR || "../build/nuitka/bgin_backend.dist");
const targets = [
  "win32-x64", "win32-arm64", "linux-x64", "linux-arm64", "linux-armhf",
  "alpine-x64", "alpine-arm64", "darwin-x64", "darwin-arm64",
];
const { target } = JSON.parse(await readFile(path.join(backend, "target.json"), "utf8"));
if (!targets.includes(target)) throw new Error(`Unsupported native VS Code target: ${target}`);
const executable = target.startsWith("win32-") ? "bgin_backend.exe" : "bgin_backend";
await access(path.join(backend, executable));
if (process.argv.includes("--package")) {
  const { version } = JSON.parse(await readFile("package.json", "utf8"));
  const vsce = path.resolve("node_modules/@vscode/vsce/vsce");
  const result = spawnSync(process.execPath, [vsce, "package", "--target", target,
    "--no-dependencies", "--allow-missing-repository", "--out", `../dist/bgin-editor-${version}-${target}.vsix`],
  { stdio: "inherit" });
  if (result.error) throw result.error;
  process.exit(result.status ?? 1);
}
const staged = path.join(await realpath("."), "backend");
const fromStage = path.relative(staged, await realpath(backend));
if (fromStage === "" || (!fromStage.startsWith(".." + path.sep) && fromStage !== ".." && !path.isAbsolute(fromStage))) {
  throw new Error("BGIN_BACKEND_DIR must point outside the staging folder.");
}
await rm(staged, { recursive: true, force: true });
await cp(backend, staged, { recursive: true });
await mkdir("out", { recursive: true });
await mkdir("../dist", { recursive: true });
await cp("../CHANGELOG.md", "CHANGELOG.md");
const alias = { "jsonc-parser": "jsonc-parser/lib/esm/main.js" };
const host = await build({
  entryPoints: ["src/extension.ts"],
  bundle: true,
  platform: "node",
  format: "cjs",
  outfile: "out/extension.js",
  external: ["vscode"],
  sourcemap: true,
  alias,
  metafile: true,
});
const ui = await build({
  entryPoints: ["src/webview.ts"],
  bundle: true,
  platform: "browser",
  format: "iife",
  outfile: "media/app.js",
  minify: true,
  alias,
  metafile: true,
});
const packages = new Set();
for (const file of [
  ...Object.keys(host.metafile.inputs),
  ...Object.keys(ui.metafile.inputs),
]) {
  const parts = file.replaceAll("\\", "/").split("/");
  const i = parts.indexOf("node_modules");
  if (i >= 0)
    packages.add(
      parts.slice(0, i + (parts[i + 1].startsWith("@") ? 3 : 2)).join("/"),
    );
}
const notices = [];
for (const folder of [...packages].sort()) {
  const info = JSON.parse(
    await readFile(path.join(folder, "package.json"), "utf8"),
  );
  for (const name of ["LICENSE", "LICENSE.txt", "LICENSE.md", "License.txt"]) {
    try {
      notices.push(
        info.name +
          " " +
          info.version +
          "\n" +
          (await readFile(path.join(folder, name), "utf8")),
      );
      break;
    } catch {}
  }
}
await writeFile(
  "THIRD_PARTY_NOTICES.txt",
  notices.join("\n\n--------------------\n\n"),
);
