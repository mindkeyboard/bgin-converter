const { chromium } = require("playwright");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const fs = require("node:fs/promises");
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
    assert(await page.getByRole("heading", { name: "MCP connections", exact: true }).isVisible());
    assert.deepEqual(await page.getByLabel("Direction").locator("option").allTextContents(), ["BGIN → JSON", "JSON → BGIN", "BGIN → BGIN"]);
    assert.deepEqual(await page.getByLabel("Target BGIN format").locator("option").allTextContents(), ["Keep source format", "~0.0.2", "~1.6.0", "~3.7.0", "~5.8.0"]);
    await page.getByLabel("Target BGIN format").selectOption("a8-5.8.0");
    await page.getByLabel("Direction").selectOption("bgin");
    await page.getByRole("button", { name: "Choose…", exact: true }).click();
    await page.getByRole("button", { name: "Save as…", exact: true }).click();
    await page.getByRole("button", { name: "Create empty BGIN", exact: true }).click();
    await page.getByRole("button", { name: "Add BGIN to the New menu", exact: true }).click();
    assert(await page.getByRole("button", { name: "Convert", exact: true }).isDisabled());
    assert.deepEqual(await page.evaluate(() => window.sent.map(message => Object.fromEntries(Object.entries(message).filter(([, value]) => value !== undefined)))), [
      { type: "format", format: "a8-5.8.0" },
      { type: "direction", to: "bgin" }, { type: "source" }, { type: "destination" }, { type: "new" }, { type: "enable" },
    ]);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Sidebar must fit a narrow width");
    await page.evaluate(() => {
      const colors = { "--vscode-font-size": "13px", "--vscode-font-family": "Segoe UI", "--vscode-foreground": "#ccc", "--vscode-descriptionForeground": "#999", "--vscode-input-background": "#303030", "--vscode-input-foreground": "#ddd", "--vscode-button-background": "#007acc", "--vscode-button-foreground": "white", "--vscode-button-secondaryBackground": "#383838", "--vscode-button-secondaryForeground": "#ddd", "--vscode-panel-border": "#444" };
      for (const [key, value] of Object.entries(colors)) document.documentElement.style.setProperty(key, value);
      document.body.style.background = "#252526";
    });
    await page.screenshot({ path: path.resolve(__dirname, "../../build/editor-test/converter.png"), fullPage: true });
    const clientsHtml = path.resolve(__dirname, "../../build/editor-test/converter-clients.html");
    try {
      await fs.access(clientsHtml);
      await page.goto(pathToFileURL(clientsHtml).href);
      assert(await page.getByText("Extension test A", { exact: true }).isVisible());
      assert(await page.getByText("Extension test B", { exact: true }).isVisible());
      await page.getByRole("button", { name: "Copy connection path", exact: true }).click();
      const resume = page.getByRole("button", { name: "Resume edits", exact: true });
      const resumedSession = await resume.getAttribute("data-session");
      await resume.click();
      const stop = page.getByRole("button", { name: "Stop operation", exact: true }).last();
      const stoppedSession = await stop.getAttribute("data-session"), stoppedOperation = await stop.getAttribute("data-operation");
      await stop.click();
      const open = page.getByRole("button", { name: "Open document", exact: true }).first();
      const openedDocument = await open.getAttribute("data-document");
      await open.click();
      const disconnect = page.getByRole("button", { name: "Disconnect", exact: true }).last();
      const disconnectedSession = await disconnect.getAttribute("data-session");
      await disconnect.click();
      assert.deepEqual(await page.evaluate(() => window.sent.map(message => Object.fromEntries(Object.entries(message).filter(([, value]) => value !== undefined)))), [
        { type: "copyConnection" },
        { type: "mcpResume", sessionId: resumedSession },
        { type: "mcpStop", sessionId: stoppedSession, operationId: stoppedOperation },
        { type: "mcpOpen", documentId: openedDocument },
        { type: "mcpDisconnect", sessionId: disconnectedSession },
      ]);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Two connected clients must fit a narrow sidebar");
      console.log("BGIN_MCP_PANEL_UI: two clients, paused state, resume, stop, jump, disconnect and connection path controls passed.");
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      console.log("BGIN_MCP_PANEL_UI: client controls not exercised; run the Extension Host suite to generate converter-clients.html.");
    }
    console.log("BGIN_CONVERTER_UI: MCP section, four explicit formats, three conversion directions, controls, disabled action, CSP scripts and narrow layout passed.");
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
