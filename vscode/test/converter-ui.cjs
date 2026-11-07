const { chromium } = require("playwright");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 340, height: 900 } });
    await page.addInitScript(() => {
      window.sent = [];
      window.acquireVsCodeApi = () => ({ postMessage: message => window.sent.push(message) });
    });
    await page.goto(pathToFileURL(path.resolve(__dirname, "../../build/editor-test/converter.html")).href);
    await page.getByLabel("Direction").selectOption("bgin");
    await page.getByRole("button", { name: "Choose…", exact: true }).click();
    await page.getByRole("button", { name: "Save as…", exact: true }).click();
    await page.getByRole("button", { name: "Create empty BGIN", exact: true }).click();
    await page.getByRole("button", { name: "Add BGIN to the New menu", exact: true }).click();
    assert(await page.getByRole("button", { name: "Convert", exact: true }).isDisabled());
    assert.deepEqual(await page.evaluate(() => window.sent), [
      { type: "direction", to: "bgin" }, { type: "source" }, { type: "destination" }, { type: "new" }, { type: "enable" },
    ]);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Sidebar must fit a narrow width");
    await page.evaluate(() => {
      const colors = { "--vscode-font-size": "13px", "--vscode-font-family": "Segoe UI", "--vscode-foreground": "#ccc", "--vscode-descriptionForeground": "#999", "--vscode-input-background": "#303030", "--vscode-input-foreground": "#ddd", "--vscode-button-background": "#007acc", "--vscode-button-foreground": "white", "--vscode-button-secondaryBackground": "#383838", "--vscode-button-secondaryForeground": "#ddd", "--vscode-panel-border": "#444" };
      for (const [key, value] of Object.entries(colors)) document.documentElement.style.setProperty(key, value);
      document.body.style.background = "#252526";
    });
    await page.screenshot({ path: path.resolve(__dirname, "../../build/editor-test/converter.png"), fullPage: true });
    console.log("BGIN_CONVERTER_UI: controls, labels, disabled action, CSP scripts and narrow layout passed.");
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
