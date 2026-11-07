const path = require("node:path");
const fs = require("node:fs/promises");
const { runTests } = require("@vscode/test-electron");
(async () => {
  const root = path.resolve(__dirname, ".."),
    workspace = path.resolve(root, "../build/editor-test");
  await fs.mkdir(workspace, { recursive: true });
  await fs.copyFile(
    path.resolve(root, "../examples/hierarchy.bgin"),
    path.join(workspace, "fixture.bgin"),
  );
  await runTests({
    vscodeExecutablePath: process.env.BGIN_VSCODE,
    extensionDevelopmentPath: process.env.BGIN_EXTENSION_PATH || root,
    extensionTestsPath: path.join(__dirname, "suite.cjs"),
    launchArgs: [
      workspace,
      "--disable-extensions",
      "--disable-gpu",
      "--skip-welcome",
      "--skip-release-notes",
      "--disable-workspace-trust",
      "--user-data-dir=" + path.resolve(root, "../build/vscode-test-user"),
      "--extensions-dir=" +
        path.resolve(root, "../build/vscode-test-extensions"),
    ],
  });
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
