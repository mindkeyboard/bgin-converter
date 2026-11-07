const { chromium } = require("playwright");
const { spawn } = require("node:child_process");
const { createInterface } = require("node:readline");
const fs = require("node:fs/promises");
const path = require("node:path");
const assert = require("node:assert/strict");
const root = path.resolve(__dirname, ".."),
  project = path.resolve(root, "..");
const executable = path.join(
  root,
  "backend",
  process.platform === "win32" ? "bgin_backend.exe" : "bgin_backend",
);
const p = spawn(executable, [], {
  windowsHide: true,
});
let serial = 0;
const pending = new Map();
createInterface({ input: p.stdout }).on("line", (line) => {
  const m = JSON.parse(line),
    w = pending.get(m.id);
  if (w) {
    pending.delete(m.id);
    m.error ? w.reject(new Error(m.error.message)) : w.resolve(m.result);
  }
});
p.stderr.on("data", (d) => process.stderr.write(d));
const rpc = (method, params = {}) =>
  new Promise((resolve, reject) => {
    const id = ++serial;
    pending.set(id, { resolve, reject });
    p.stdin.write(JSON.stringify({ id, method, params }) + "\n");
  });
(async () => {
  let text = JSON.stringify(
    {
      name: "example",
      screens: [
        {
          type: "HorizontalContainer",
          name: "screen",
          properties: { Margins: [12, 12, 20, 20], Spacing: 4 },
          children: [
            {
              type: "StackContainer",
              name: "left",
              properties: { StretchFactor: 1 },
              children: [
                {
                  type: "Label",
                  name: "title",
                  properties: {
                    TestString: "Layout / selection",
                    FontHeight: 28,
                  },
                },
              ],
            },
            {
              type: "StackContainer",
              name: "right",
              properties: { StretchFactor: 2 },
              children: [
                {
                  type: "Label",
                  name: "detail",
                  properties: { TestString: "Binary GIN", FontHeight: 24 },
                },
              ],
            },
          ],
        },
      ],
    },
    null,
    2,
  );
  const initial = text,
    catalog = await rpc("catalog"),
    browser = await chromium.launch({
      executablePath: process.env.BGIN_BROWSER,
      channel: process.env.BGIN_BROWSER ? undefined : "msedge",
      headless: true,
    });
  try {
    const page = await browser.newPage({
        viewport: { width: 1450, height: 920 },
      }),
      errors = [];
    let last,
      lastRenderOptions,
      renderCount = 0,
      holdNext = false,
      releaseRender,
      activeRequest;
    let clipboard = "";
    let acceptedTerms = 0;
    const openedDocs = [];
    let guideOpens = 0;
    let termsDismissals = 0;
    const resourceFolder = path.join(project, "build", "external-resources");
    let savedResourceFolders;
    page.on("pageerror", (e) => errors.push(String(e)));
    const send = (m) =>
      page.evaluate(
        (m) => window.dispatchEvent(new MessageEvent("message", { data: m })),
        m,
      );
    await page.exposeFunction("send", async (m) => {
      if (m.type === "setDocumentName") {
        text = JSON.stringify({ ...JSON.parse(text), name: m.name });
        await page.evaluate(name => { window.lastName = name; }, m.name);
      }
      if (m.type === "acceptTerms") {
        assert.equal(m.version, "2026-10-22");
        acceptedTerms++;
      }
      if (m.type === "openDocs") openedDocs.push(m.target);
      if (m.type === "openEditorGuide") guideOpens++;
      if (m.type === "firstTermsDismissed") termsDismissals++;
      if (m.type === "setLanguage") await send({ type: "config", uiLanguage: m.language, resources: {} });
      if (m.type === "ready") {
        await new Promise((r) => setTimeout(r, 250));
        await send({
          type: "init",
          text,
          catalog,
          resources: { bindings: {} },
          defaults: { debugFill: true, names: true },
          uiLanguage: "en",
        });
      }
      if (m.type === "clipboardWrite") {
        clipboard = m.text;
        await send({
          type: "clipboardWritten",
          cutPath: m.cutPath,
          text: m.text,
        });
      }
      if (m.type === "clipboardRead")
        await send({
          type: "clipboardRead",
          text: clipboard,
          target: m.target,
        });
      if (m.type === "resourcesDiscover")
        await send({
          type: "resourcesDiscovered",
          resourceSettings: {
            bginRoot: m.root + "/gui",
            assetRoot: m.root,
            textureRoot: m.root + "/textures_android",
            fontRoot: m.root + "/texter_fonts",
          },
          notes: [],
        });
      if (m.type === "resourceBrowse")
        await send({
          type: "resourcePicked",
          requestId: m.requestId,
          path: resourceFolder,
        });
      if (m.type === "resourcesApply") {
        assert.equal(
          m.bindings,
          undefined,
          "Folder UI sends no per-file bindings",
        );
        const resourceSettings = Object.fromEntries(
          ["assetRoot", "bginRoot", "textureRoot", "fontRoot"].map((key) => [
            key,
            m[key],
          ]),
        );
        savedResourceFolders = resourceSettings;
        await send({
          type: "config",
          resources: resourceSettings,
          resourceSettings,
        });
        await send({ type: "resourcesSaved", resourceSettings, errors: [] });
      }
      if (m.type === "cancelRender")
        await send({ type: "renderCancelled", requestId: activeRequest });
      if (m.type === "edit") {
        text = m.text;
        try {
          JSON.parse(text);
          await send({ type: "syntax", errors: [] });
        } catch {
          await send({ type: "syntax", errors: ["Invalid JSON"] });
        }
      }
      if (m.type === "render") {
        renderCount++;
        lastRenderOptions = structuredClone(m.options);
        activeRequest = m.requestId;
        try {
          if (holdNext) {
            holdNext = false;
            await new Promise((resolve) => {
              releaseRender = resolve;
            });
          }

          last = await rpc("render", { text, options: m.options });
          await send({ type: "rendered", requestId: m.requestId, ...last });
        } catch (e) {
          await send({
            type: "renderError",
            requestId: m.requestId,
            message: String(e),
          });
        }
      }
    });
    await page.setContent(
      '<html><head><style>:root{--vscode-foreground:#ddd;--vscode-editor-foreground:#ddd;--vscode-editor-background:#1e1e1e;--vscode-input-background:#313131;--vscode-button-secondaryBackground:#383838;--vscode-panel-border:#444;--vscode-list-activeSelectionBackground:#264f78;--vscode-button-background:#087fbd;--vscode-inputValidation-errorBackground:#6a2525;--vscode-editorGroupHeader-tabsBackground:#171717;--vscode-editor-selectionBackground:#264f78}</style></head><body><div id="app"></div></body></html>',
    );
    await page.addStyleTag({ path: path.join(root, "media/styles.css") });
    await page.evaluate(() => {
      window.acquireVsCodeApi = () => ({
        getState: () => ({}),
        setState: (state) => {
          window.editorState = structuredClone(state);
        },
        postMessage: (m) => window.send(m),
      });
    });
    await page.addScriptTag({ path: path.join(root, "media/app.js") });
    await page.locator("#resourceButton").click();
    assert(
      await page.locator("#resourcePanel").isVisible(),
      "Resources open before catalog/render",
    );
    assert.equal(
      await page.locator(".binding-row, #addBinding").count(),
      0,
      "Resources have folder fields only",
    );
    // Let initial host configuration arrive before editing resource paths.
    await page.locator(".tree-row").first().waitFor();
    await page.locator("#bginRoot").locator("..").locator("button").click();
    await page.waitForFunction(
      () => document.querySelector("#bginRoot").value !== "",
    );
    await page.locator("#textureRoot").fill("C:/textures");
    await page.locator("#fontRoot").fill("C:/fonts");
    await page.locator("#saveResources").click();
    await page.waitForFunction(
      () =>
        document.querySelector("#resourceStatus").textContent ===
        "Folders saved",
    );
    assert.equal(await page.locator("#bginRoot").inputValue(), resourceFolder);
    assert.deepEqual(savedResourceFolders, {
      assetRoot: "",
      bginRoot: resourceFolder,
      textureRoot: "C:/textures",
      fontRoot: "C:/fonts",
    });
    const fallbackNotice =
      "Resource folders saved for this workspace. VS Code Settings could not be updated. Run Developer: Reload Window after an extension update, then save again.";
    await send({
      type: "resourcesSaved",
      resourceSettings: savedResourceFolders,
      notice: fallbackNotice,
    });
    assert.equal(
      await page.locator("#resourceStatus").textContent(),
      fallbackNotice,
      "Stale registration keeps folder values and explains reload",
    );
    await page.locator("#closeResources").click();
    await page.locator(".tree-row").first().waitFor();
    await page.locator('.tree-row[data-path="/screens/0"]').click();
    assert(await page.locator("#inspectorDivider").isVisible(), "Divider is usable on first selection before toggling any node");
    const initialTreeHeight = await page.locator("#tree").evaluate(el => el.clientHeight);
    const initialDivider = await page.locator("#inspectorDivider").boundingBox();
    assert.equal(initialDivider.height, 1, "Divider has a one-pixel visible line");
    const dividerColour = await page.locator("#inspectorDivider").evaluate(el => getComputedStyle(el).backgroundColor);
    await page.mouse.move(initialDivider.x + initialDivider.width / 2, initialDivider.y);
    assert.equal(await page.locator("#inspectorDivider").evaluate(el => getComputedStyle(el).backgroundColor), dividerColour, "Hover does not highlight the line");
    await page.mouse.down();
    await page.mouse.move(initialDivider.x + initialDivider.width / 2, initialDivider.y - 35, { steps: 4 });
    await page.mouse.up();
    assert((await page.locator("#tree").evaluate(el => el.clientHeight)) < initialTreeHeight, "First-selection pointer drag resizes panes");
    await page.waitForTimeout(500);
    assert.equal(
      renderCount,
      0,
      "Opening/configuring never renders automatically",
    );
    assert.equal(await page.locator("#scene svg").count(), 0);
    assert.equal(
      await page.locator(".tree-row .node-icon").count(),
      await page.locator(".tree-row").count(),
      "Each node has an SVG icon",
    );
    await page.locator("#refreshPreview").click();
    await page.locator("#scene svg").waitFor();
    assert.equal(renderCount, 1);
    const originalGeometry = structuredClone(last.geometry);
    await page.locator('.tree-row[data-path="/screens/0/children/1"]').click();
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll("#scene g[data-path]")).filter(
          (n) => n.style.display !== "none",
        ).length === 2,
    );
    assert.equal(renderCount, 1, "Selection filters cached SVG without Python");
    assert.deepEqual(last.geometry, originalGeometry);
    assert.equal(
      await page.locator("#nodeJson .cm-editor").count(),
      0,
      "Collapsed inspector does not construct a subtree editor",
    );
    await page.locator("#clearSelection").click();
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll("#scene g[data-path]")).filter(
          (n) => n.style.display !== "none",
        ).length === 5,
    );
    await page.locator('.tree-row[data-path="/screens/0/children/1"]').click();
    await page.locator("#settingsToggle").click();
    assert(
      await page
        .getByRole("dialog", { name: "Preview settings", exact: true })
        .isVisible(),
    );
    assert.equal(await page.locator("#aspectPreset").inputValue(), "16:9");
    await page.locator("#aspectPreset").selectOption("4:3");
    assert.equal(
      await page.locator("#aspectPreset").inputValue(),
      "4:3",
      "Applied aspect ratio remains visible after rebuilding fields",
    );
    assert.equal(await page.locator("#option-height").inputValue(), "960");
    await page.locator("#aspectPreset").selectOption("16:9");
    assert.equal(await page.locator("#option-height").inputValue(), "720");
    const checkboxIds = await page
      .locator('#settings input[type="checkbox"]')
      .evaluateAll((nodes) => nodes.map((node) => node.id));
    assert.equal(
      checkboxIds.length,
      16,
      "All preview boolean options are available",
    );
    const originalChecks = {};
    const changedChecks = {};
    const checkboxValues = () =>
      page
        .locator('#settings input[type="checkbox"]')
        .evaluateAll((nodes) =>
          Object.fromEntries(nodes.map((node) => [node.id, node.checked])),
        );
    for (const id of checkboxIds) {
      const before = await checkboxValues();
      const input = page.locator("#" + id);
      originalChecks[id.slice(7)] = before[id];
      assert.equal(
        await page.locator(`label[for="${id}"] input`).getAttribute("id"),
        id,
      );
      await page.locator(`label[for="${id}"] .setting-title`).click();
      const after = await checkboxValues();
      for (const sibling of checkboxIds)
        assert.equal(
          after[sibling],
          sibling === id ? !before[id] : before[sibling],
          `${id}: clicking its text changes only its own checkbox`,
        );
      const stored = await page.evaluate(() => window.editorState.options);
      changedChecks[id.slice(7)] = !before[id];
      assert.equal(
        stored[id.slice(7)],
        !before[id],
        `${id}: own option is persisted`,
      );
      if (id === "option-selectionOnly") {
        assert.equal(
          await page
            .locator("#scene g[data-path]")
            .evaluateAll(
              (nodes) =>
                nodes.filter((node) => node.style.display !== "none").length,
            ),
          5,
        );
        await page
          .locator('label[for="option-selectionOnly"] .setting-title')
          .click();
        assert.equal(
          await page
            .locator("#scene g[data-path]")
            .evaluateAll(
              (nodes) =>
                nodes.filter((node) => node.style.display !== "none").length,
            ),
          2,
        );
        await page
          .locator('label[for="option-selectionOnly"] .setting-title')
          .click();
        assert.equal(
          await page
            .locator("#scene g[data-path]")
            .evaluateAll(
              (nodes) =>
                nodes.filter((node) => node.style.display !== "none").length,
            ),
          5,
        );
        assert.equal(
          renderCount,
          1,
          "Selection checkbox filters the existing preview immediately",
        );
      }
    }
    await page
      .locator('label[for="option-selectionOnly"] .setting-title')
      .click();
    assert.equal(
      await page
        .locator("#scene g[data-path]")
        .evaluateAll(
          (nodes) =>
            nodes.filter((node) => node.style.display !== "none").length,
        ),
      2,
      "Selection checkbox still filters cached SVG after other settings became dirty",
    );
    assert(
      (await page.locator("#stats").innerText()).includes("out of date"),
      "Selection filter keeps refresh-needed status for dirty settings",
    );
    await page
      .locator('label[for="option-selectionOnly"] .setting-title')
      .click();
    await page.locator("#closeSettings").click();
    await page.locator("#clearSelection").click();
    assert.equal(
      await page
        .locator("#scene g[data-path]")
        .evaluateAll(
          (nodes) =>
            nodes.filter((node) => node.style.display !== "none").length,
        ),
      5,
      "Clearing selection shows cached whole screen even with dirty settings",
    );
    await page.locator('.tree-row[data-path="/screens/0/children/1"]').click();
    await page.locator("#settingsToggle").click();
    for (const width of [420, 320]) {
      await page.setViewportSize({ width, height: 720 });
      for (const id of checkboxIds) {
        await page.locator("#" + id).scrollIntoViewIfNeeded();
        const boxes = await page
          .locator(`label[for="${id}"]`)
          .evaluate((label) => ({
            input: label
              .querySelector("input")
              .getBoundingClientRect()
              .toJSON(),
            title: label
              .querySelector(".setting-title")
              .getBoundingClientRect()
              .toJSON(),
            dialog: label.closest("dialog").getBoundingClientRect().toJSON(),
            overflow:
              label.closest("dialog").scrollWidth -
              label.closest("dialog").clientWidth,
          }));
        assert(
          boxes.input.left >= 0 && boxes.input.right <= width,
          `${id}: checkbox stays within the ${width}px window`,
        );
        assert(
          boxes.input.right < boxes.title.left,
          `${id}: checkbox precedes its own text`,
        );
        assert(
          boxes.title.right <= boxes.dialog.right,
          `${id}: label stays inside the dialog`,
        );
        assert(
          boxes.overflow <= 1,
          `No horizontal settings overflow at ${width}px`,
        );
      }
      await page.screenshot({
        path: path.join(project, `build/editor-settings-${width}.png`),
      });
    }
    await page.setViewportSize({ width: 1450, height: 920 });
    await page.locator("#option-width").fill("-1");
    await page.locator("#option-width").press("Tab");
    assert.equal(
      await page.locator("#option-width").getAttribute("aria-invalid"),
      "true",
    );
    assert.equal(
      await page.evaluate(() => window.editorState.options.width),
      1280,
    );
    await page.locator("#option-width").fill("1024");
    await page.locator("#option-width").press("Tab");
    assert.equal(
      await page.locator("#aspectPreset").inputValue(),
      "Free",
      "Manual dimensions update displayed aspect ratio",
    );
    assert(
      Math.abs(
        (await page
          .locator("#scene")
          .evaluate((node) => node.clientWidth / node.clientHeight)) -
          1280 / 720,
      ) < 0.02,
      "Pending resolution does not stretch the last completed preview",
    );
    await page.locator("#closeSettings").click();
    await page.waitForTimeout(300);
    assert.equal(renderCount, 1, "Changing options does not render");
    await page.locator("#refreshPreview").click();
    await page.waitForFunction(
      () =>
        document.querySelector("#scene svg").getAttribute("viewBox") ===
        "0 0 1024 720",
    );
    assert.equal(renderCount, 2);
    for (const [key, value] of Object.entries(changedChecks))
      assert.equal(
        lastRenderOptions[key],
        value,
        `${key}: renderer receives the value chosen by its label`,
      );
    assert.equal(
      await page.locator("#scene svg").getAttribute("style"),
      "image-rendering:pixelated",
    );
    assert.equal(
      await page.locator("#scene #grid").count(),
      1,
      "Grid checkbox draws the grid",
    );
    assert.equal(
      await page.locator("#scene #checks").count(),
      0,
      "Checkerboard checkbox removes the pattern",
    );
    assert.equal(
      await page
        .locator('#scene g[data-path] > rect[stroke="#78abc9"]')
        .count(),
      0,
      "Bounds checkbox removes object bounds",
    );
    await page.locator("#settingsToggle").click();
    for (const id of checkboxIds) {
      assert.equal(
        await page.locator("#" + id).isChecked(),
        changedChecks[id.slice(7)],
        "Reopening preserves each checkbox",
      );
      await page.locator(`label[for="${id}"] .setting-title`).click();
      assert.equal(
        await page.locator("#" + id).isChecked(),
        originalChecks[id.slice(7)],
      );
    }
    await page.locator("#closeSettings").click();
    holdNext = true;
    await page.locator("#refreshPreview").click();
    await page.waitForFunction(
      () => !document.querySelector("#cancelPreview").hidden,
    );
    await page.locator("#resourceButton").click();
    assert(
      await page.locator("#resourcePanel").isVisible(),
      "Resources remain usable during a pending render",
    );
    await page.locator("#closeResources").click();
    await page.locator("#cancelPreview").click();
    await page.waitForFunction(
      () => !document.querySelector("#refreshPreview").disabled,
    );
    releaseRender();
    await page.waitForTimeout(250);
    assert(
      (await page.locator("#stats").innerText()).includes("out of date"),
      "Cancelled response cannot replace the preview",
    );
    await page.locator("#togglePreview").click();
    assert(await page.locator("#preview").isHidden());
    await page.locator("#togglePreview").click();
    await page.locator("#expandPreview").click();
    assert(await page.locator("#editing").isHidden());
    await page.locator("#expandPreview").click();
    await page.locator("#jsonMode").click();
    await page.locator("#jsonEditor .cm-content").fill('{"screens": [}');
    await page.locator("#banner").waitFor({ state: "visible" });
    assert((await page.locator("#banner").innerText()).includes("JSON"));
    await page.locator("#jsonEditor .cm-content").fill(initial);
    await page.waitForFunction(() => document.querySelector("#banner").hidden);
    await page.locator("#treeMode").click();
    await page.locator('.tree-row[data-path="/screens/0/children/0"]').click();
    await page.locator("#nodeName").fill("renamed");
    await page.locator("#nodeName").press("Tab");
    await page.waitForTimeout(300);
    assert.equal(JSON.parse(text).screens[0].children[0].name, "renamed");
    const left = '.tree-row[data-path="/screens/0/children/0"]';
    const menu = async (selector, label) => {
      await page.locator(selector).click({ button: "right" });
      await page.getByRole("menuitem", { name: label, exact: true }).click();
    };
    await menu(left, "Copy JSON");
    assert.equal(JSON.parse(clipboard).name, "renamed");
    assert.equal(JSON.parse(clipboard).children[0].name, "title");
    await menu(left, "Duplicate");
    assert.equal(JSON.parse(text).screens[0].children[1].name, "renamed_copy");
    await menu('.tree-row[data-path="/screens/0/children/1"]', "Delete");
    assert.equal(JSON.parse(text).screens[0].children.length, 2);
    await menu(left, "Paste into container");
    assert.equal(JSON.parse(text).screens[0].children[0].children.length, 2);
    await menu(
      '.tree-row[data-path="/screens/0/children/0/children/1"]',
      "Delete",
    );
    // Selections copied from JSON lists or chat code blocks must retain the
    // complete branch. Invalid text must not add even part of a branch.
    const beforeClipboardTests = text;
    const beforePasteRenders = renderCount;
    const pastedBranch = {
      type: "StackContainer", name: "clipboard_branch", properties: {},
      children: [{ type: "Label", name: "nested_text", properties: {
        TestString: 'Braces { }, comma, "quotes", \\path, newline\nРусский',
        TextStyle: "/Widgets/MM_White_Text", HeightFactor: 4.5,
      } }],
    };
    const branchText = JSON.stringify(pastedBranch, null, 2);
    const pasteCases = [
      ["complete object", branchText],
      ["array separator", branchText + ",\r\n"],
      ["UTF-8 marker", "\uFEFF" + branchText],
      ["chat JSON block", "```json\r\n" + branchText + "\r\n```"],
      ["object fields", branchText.trim().slice(1, -1)],
      ["single array item", "[" + branchText + "]"],
    ];
    if (process.env.BGIN_CLIPBOARD_FIXTURE) {
      const popup = await fs.readFile(process.env.BGIN_CLIPBOARD_FIXTURE, "utf8");
      pasteCases.push(["reported popup", popup], ["reported popup with separator", popup + ","]);
    }
    for (const [label, raw] of pasteCases) {
      const expected = label.startsWith("reported popup") ? JSON.parse(raw.replace(/,\s*$/, "")) : pastedBranch;
      clipboard = raw;
      await menu(left, "Paste into container");
      await page.waitForFunction(name => document.querySelector("#nodeName").value === name, expected.name);
      assert.deepEqual(JSON.parse(text).screens[0].children[0].children[1], expected, label);
      assert(await page.locator("#banner").isHidden(), label + " has no syntax error");
      // RPC encode uses the independent transaction codec to verify the saved BGIN.
      await rpc("encode", { text });
      await menu('.tree-row[data-path="/screens/0/children/0/children/1"]', "Delete");
      assert.equal(text, beforeClipboardTests, label + " leaves the rest of the document intact");
    }
    for (const raw of [branchText + " unrelated text", branchText + "," + branchText, branchText.slice(0, -1), "[]"]) {
      clipboard = raw;
      await menu(left, "Paste into container");
      await page.locator("#banner").waitFor({ state: "visible" });
      assert.equal(text, beforeClipboardTests, "Invalid clipboard cannot mutate the document");
      assert(!/SyntaxError|position \d/.test(await page.locator("#banner").innerText()), "Paste errors explain what to copy");
      await page.locator("#banner button").last().click();
    }
    assert.equal(renderCount, beforePasteRenders, "Paste never starts automatic rendering");
    await menu(left, "New child object…");
    assert.ok(await page.locator('dialog [role="option"] .node-icon').count());
    const objectCards = await page.locator('dialog [role="option"]').evaluateAll(items => items.map(item => { const r=item.getBoundingClientRect(); return { x:r.x,y:r.y }; }));
    assert(objectCards.some((a, i) => objectCards.some((b, j) => i !== j && a.y === b.y && a.x !== b.x)), "Object types use multiple columns like screen types");
    const pickerWidth = await page.locator('dialog .type-picker').evaluate(el => el.clientWidth);
    const bodyWidth = await page.locator('dialog[open] .dialog-body').evaluate(el => el.clientWidth);
    assert(pickerWidth > bodyWidth * 0.9, "Object picker occupies the dialog width");
    await page.screenshot({ path: path.join(project, "build/editor-object-grid-0410.png") });
    await page.locator('dialog input[type="search"]').fill("Movie");
    await page.locator('dialog input[type="search"]').press("Enter");
    await page.waitForFunction(
      () => document.querySelector("#nodeName").value === "new_object",
    );
    assert.equal(JSON.parse(text).screens[0].children[0].children.length, 2);
    await menu(
      '.tree-row[data-path="/screens/0/children/0/children/1"]',
      "Delete",
    );
    await menu(left, "Rename…");
    await page.locator("dialog form input").fill("renamed_again");
    await page.locator('dialog form button[type="submit"]').click();
    await page.waitForFunction(
      () => document.querySelector("#nodeName").value === "renamed_again",
    );
    assert.equal(JSON.parse(text).screens[0].children[0].name, "renamed_again");
    await menu(left, "Change type…");
    await page.locator('dialog [data-type="GridContainer"]').click();
    await page.locator('dialog [data-docs-type="MarginContainer"]').click();
    assert.equal(await page.locator('dialog .type-picker').getAttribute('data-value'), 'GridContainer', 'Card documentation does not change the selected type');
    await page.locator("dialog #typeDocs").click();
    await page.waitForFunction(() => document.querySelector("dialog #typeDocs"));
    await page.locator('dialog [data-type="FixedSizeContainer"]').click();
    await page.locator('dialog form button[type="submit"]').click();
    await page.waitForFunction(
      () => document.querySelector("#nodeType").value === "FixedSizeContainer",
    );
    assert.equal(
      JSON.parse(text).screens[0].children[0].type,
      "FixedSizeContainer",
    );
    assert.equal(
      await page
        .locator("#propertyRows .property:not(.preserved-property)")
        .count(),
      catalog.schemas.FixedSizeContainer.length,
    );
    const compiledEdit = await rpc("encode", { text });
    await fs.writeFile(
      path.join(project, "build/ui-edited.bgin"),
      Buffer.from(compiledEdit.data, "base64"),
    );
    const decodedEdit = await rpc("decode", { data: compiledEdit.data });
    assert.equal(
      JSON.parse(decodedEdit.text).screens[0].children[0].type,
      "FixedSizeContainer",
    );
    assert.equal(await page.locator("#addProperty").count(), 0);
    assert.equal(await page.locator("#propertyRows button").count(), 0);
    await page
      .locator('#propertyRows select[aria-label="EnableFixedWidth"]')
      .selectOption("1");
    assert.equal(
      JSON.parse(text).screens[0].children[0].properties.EnableFixedWidth,
      1,
    );
    const boolEncoded = await rpc("encode", { text });
    const boolDecoded = await rpc("decode", { data: boolEncoded.data });
    assert.equal(JSON.parse(boolDecoded.text).screens[0].children[0].properties.EnableFixedWidth, 1);
    await page.locator('#propertyRows select[aria-label="EnableFixedWidth"]').selectOption("0");
    assert.equal(JSON.parse(text).screens[0].children[0].properties.EnableFixedWidth, 0);
    await page.locator('#propertyRows select[aria-label="EnableFixedWidth"]').selectOption("");
    assert.equal("EnableFixedWidth" in JSON.parse(text).screens[0].children[0].properties, false);
    await page.locator("#openDocs").click();
    await page.locator("#editorDocs").click();
    await page.locator("#objectDocs").click();
    await page.waitForTimeout(50);
    assert.deepEqual(openedDocs, ["gin::MarginContainer", "gin::GridContainer", undefined, "gin::FixedSizeContainer"]);
    assert.equal(guideOpens, 1, "Guide has its own link action");
    await page.mouse.move(0, 0);
    for (const selector of ["#openDocs", "#editorDocs", "#objectDocs"]) {
      assert.equal(await page.locator(selector).evaluate(el => getComputedStyle(el).backgroundColor), "rgb(0, 120, 212)", "Documentation buttons are blue");
    }
    await page.screenshot({ path: path.join(project, "build/editor-documentation-0412.png") });
    assert.equal(await page.locator("header a").count(), 0, "Documentation is a button");
    await page.locator('#propertyRows input[aria-label="MinSize: Width"]').fill("12");
    await page.locator('#propertyRows input[aria-label="MinSize: Width"]').press("Tab");
    assert.equal("MinSize" in JSON.parse(text).screens[0].children[0].properties, false, "Pair waits for both values");
    await page.locator('#propertyRows input[aria-label="MinSize: Height"]').fill("7");
    await page.locator('#propertyRows input[aria-label="MinSize: Height"]').press("Tab");
    assert.deepEqual(JSON.parse(text).screens[0].children[0].properties.MinSize, [12, 7]);
    await page.locator('#propertyRows input[aria-label="RenderLayer"]').fill("1.5");
    await page.locator('#propertyRows input[aria-label="RenderLayer"]').press("Tab");
    assert.equal("RenderLayer" in JSON.parse(text).screens[0].children[0].properties, false, "Fractions are refused");
    assert(await page.locator('#propertyRows input[aria-label="RenderLayer"]').evaluate(e => e.classList.contains("invalid")));
    await page.locator('#tree [data-path="/screens/0"]').click();
    await page.locator("#search").click();
    await page.locator("#searchQuery").fill("detail");
    await page
      .locator("#searchResults .tree-row")
      .last()
      .click({ button: "right" });
    assert.equal(
      await page.locator(".context-menu").count(),
      0,
      "Search has no context menu",
    );
    await page.locator("#searchResults .tree-row").last().click();
    assert.equal(await page.locator("#nodeName").inputValue(), "detail");
    assert.equal(
      await page.locator("#tree .selected").getAttribute("data-path"),
      "/screens/0/children/1/children/0",
    );
    assert(
      (await page.locator("#tree .tree-row").count()) >= 4,
      "Search never filters the main tree",
    );
    await page.locator('.tree-row[data-path="/screens/0/children/1"] .expander').click();
    assert.equal(await page.locator('.tree-row[data-path="/screens/0/children/1/children/0"]').count(), 0);
    await page.locator('#revealObject').click();
    assert.equal(await page.locator('#tree .selected').getAttribute('data-path'), '/screens/0/children/1/children/0');
    assert(await page.locator('.tree-row[data-path="/screens/0/children/1/children/0"]').isVisible(), 'Reveal opens ancestors and selects the inspected object');
    const beforePane = await page
      .locator("#tree")
      .evaluate((el) => el.clientHeight);
    await page.locator("#inspectorDivider").focus();
    await page.keyboard.press("ArrowUp");
    assert(
      (await page.locator("#tree").evaluate((el) => el.clientHeight)) <
        beforePane,
      "Keyboard resizes tree/property boundary",
    );
    await page.locator("#resourceButton").click();
    await page.locator("#discoveryRoot").fill("C:/assets");
    await page.locator("#discoverResources").click();
    await page.waitForFunction(
      () =>
        document.querySelector("#textureRoot").value ===
          "C:/assets/textures_android" &&
        document.querySelector("#bginRoot").value === "C:/assets/gui",
    );
    await page.locator("#closeResources").click();
    await page.locator("#settingsToggle").click();
    await send({
      type: "config",
      uiLanguage: "ru",
      resources: { bindings: {} },
    });
    await page.waitForFunction(
      () => document.querySelector("#treeMode").textContent === "Иерархия",
    );
    await page.waitForFunction(
      () =>
        document.querySelector("#option-rtl-label").textContent ===
        "Использовать размещение справа налево",
    );
    assert.equal(
      await page
        .getByRole("checkbox", {
          name: "Использовать размещение справа налево",
          exact: true,
        })
        .count(),
      1,
    );
    const keyboardBefore = await checkboxValues();
    await page.locator("#option-rtl").focus();
    await page.keyboard.press("Space");
    const keyboardAfter = await checkboxValues();
    for (const id of checkboxIds)
      assert.equal(
        keyboardAfter[id],
        id === "option-rtl" ? !keyboardBefore[id] : keyboardBefore[id],
        "Keyboard toggles only the focused checkbox in Russian",
      );
    await page.keyboard.press("Space");
    await page.setViewportSize({ width: 320, height: 720 });
    await page.locator('label[for="option-rtl"]').scrollIntoViewIfNeeded();
    await page.screenshot({
      path: path.join(project, "build/editor-settings-ru-320.png"),
    });
    await page.setViewportSize({ width: 1450, height: 920 });
    await send({
      type: "config",
      uiLanguage: "en",
      resources: { bindings: {} },
    });
    await page.waitForFunction(
      () => document.querySelector("#treeMode").textContent === "Hierarchy",
    );
    await page.waitForFunction(
      () =>
        document.querySelector("#option-rtl-label").textContent ===
        "Use right-to-left layout",
    );
    await page.locator("#closeSettings").click();
    assert.equal(
      renderCount,
      3,
      "Edits, hide/expand and JSON do not schedule renders",
    );
    assert.deepEqual(errors, [], "No browser exceptions");
    await page.locator("#settingsToggle").click();
    await page.screenshot({
      path: path.join(project, "build/editor-preview.png"),
    });
    await page.locator("#resetSettings").click();
    const resetOptions = await page.evaluate(() => window.editorState.options);
    for (const [key, value] of Object.entries(catalog.defaults)) {
      if (key !== "screen" && key !== "selected")
        assert.deepEqual(
          resetOptions[key],
          value,
          `${key}: reset restores factory defaults instead of stale saved/workspace options`,
        );
    }
    assert.equal(
      renderCount,
      3,
      "Resetting preview settings does not render automatically",
    );
    await page.locator("#closeSettings").click();
    const large = {
      name: "large",
      screens: [
        {
          type: "StackContainer",
          name: "large-screen",
          children: Array.from({ length: 120 }, (_, i) => ({
            type: "StackContainer",
            name: "group-" + i,
            children: Array.from({ length: 80 }, (_, j) => ({
              type: "Movie",
              name: "object-" + j,
              properties: {},
            })),
          })),
        },
      ],
    };
    const staleVisibility = await page
      .locator("#scene g[data-path]")
      .evaluateAll((nodes) => nodes.map((node) => node.style.display));
    await send({ type: "document", text: JSON.stringify(large) });
    const tree = page.locator("#tree");
    await tree.evaluate((el) => {
      el.scrollTop = 1200;
    });
    await page.waitForTimeout(100);
    const row = page.locator("#tree .tree-row").nth(12);
    const scrollBefore = await tree.evaluate((el) => el.scrollTop);
    const pathBefore = await row.getAttribute("data-path");
    await row.click();
    assert.equal(
      await tree.evaluate((el) => el.scrollTop),
      scrollBefore,
      "Selection preserves scroll",
    );
    await page.locator(`#tree [data-path="${pathBefore}"] .expander`).click();
    await page.waitForTimeout(100);
    assert.equal(
      await tree.evaluate((el) => el.scrollTop),
      scrollBefore,
      "Expansion preserves scroll",
    );
    assert(
      (await page.locator("#tree .tree-row").count()) < 100,
      "Virtual tree keeps DOM bounded",
    );
    await tree.evaluate((el) => {
      el.scrollTop = 0;
    });
    await page.waitForTimeout(100);
    const selectionMs = await page.evaluate(() => {
      const start = performance.now();
      document.querySelector('.tree-row[data-path="/screens/0"]').click();
      return performance.now() - start;
    });
    assert(
      selectionMs < 1500,
      "Selecting the 9,721-node root must remain responsive",
    );
    assert.equal(
      await page.locator("#nodeJson .cm-editor").count(),
      0,
      "Large subtree is not serialized into a hidden editor",
    );
    assert.equal(
      renderCount,
      3,
      "Large document open/selection does not render",
    );
    assert.deepEqual(
      await page
        .locator("#scene g[data-path]")
        .evaluateAll((nodes) => nodes.map((node) => node.style.display)),
      staleVisibility,
      "Selection in another document does not filter stale SVG from a different document",
    );
    const allTypes = {
      name: "types",
      screens: [
        {
          type: "StackContainer",
          name: "Types",
          children: catalog.types.map((type) => ({ type, name: type })),
        },
      ],
    };
    await send({ type: "document", text: JSON.stringify(allTypes) });
    const glyphs = new Set();
    for (let y = 0; y < 1100; y += 150) {
      await page.locator("#tree").evaluate((el, y) => {
        el.scrollTop = y;
      }, y);
      await page.waitForTimeout(40);
      for (const glyph of await page
        .locator("#tree .node-icon")
        .evaluateAll((nodes) => nodes.map((n) => n.innerHTML)))
        glyphs.add(glyph);
    }
    assert(
      glyphs.size >= catalog.types.length,
      "All object types have distinct SVG icons",
    );
    await page.locator("#resourceButton").click();
    await page.screenshot({
      path: path.join(project, "build/editor-types-resources.png"),
    });
    await page.locator("#closeResources").click();
    const rendersBeforeEmpty = renderCount;
    text = JSON.stringify({ screens: [] });
    await send({ type: "document", text });
    await page.locator("#documentNameDialog").waitFor({ state: "visible" });
    assert(await page.locator("#workspace").evaluate(el => el.inert), "Unnamed document cannot be edited");
    await page.keyboard.press("Escape");
    assert(await page.locator("#documentNameDialog").isVisible(), "Escape cannot bypass naming");
    await page.locator("#documentName").fill("   ");
    assert(await page.getByRole("button", { name: "Start editing", exact: true }).isDisabled());
    await page.locator("#documentName").fill("new_interface");
    await page.screenshot({ path: path.join(project, "build/editor-name-required-049.png") });
    const nameMessage = page.waitForFunction(() => window.lastName === "new_interface");
    await page.getByRole("button", { name: "Start editing", exact: true }).click();
    await nameMessage;
    await send({ type: "nameAccepted" });
    await page.locator("#documentNameDialog").waitFor({ state: "detached" });
    text = JSON.stringify({
      name: "new_interface",
      dialect: "ui",
      screens: [],
    });
    await send({ type: "document", text });
    await page.locator("#emptyDocument").waitFor();
    assert.equal(await page.locator("#tree .tree-row").count(), 0);
    assert.equal(await page.locator("#newScreen").isEnabled(), true);
    await page.locator("#refreshPreview").click();
    assert.equal(
      renderCount,
      rendersBeforeEmpty,
      "An empty draft never renders",
    );
    assert.match(
      await page.locator("#banner").textContent(),
      /Create a screen/,
    );
    await page.locator("#newScreen").click();
    await page.locator("#newScreenName").fill("cancelled");
    await page
      .locator("#newScreenDialog")
      .getByRole("button", { name: "Close", exact: true })
      .click();
    assert.equal(
      JSON.parse(text).screens.length,
      0,
      "Cancel does not change the document",
    );
    await page.locator("#newScreen").click();
    await page.locator("#newScreenName").fill("first_screen");
    assert.equal(
      await page.locator("#newScreenType").getAttribute("data-value"),
      "StackContainer",
    );
    assert.equal(
      await page.locator('#newScreenType [data-type="Sprite"]').count(),
      0,
      "Interface roots only offer containers",
    );
    assert.ok(await page.locator('#newScreenType [role="option"] .node-icon').count());
    await page.screenshot({
      path: path.join(project, "build/editor-new-screen.png"),
    });
    await page
      .locator("#newScreenDialog")
      .getByRole("button", { name: "Create", exact: true })
      .click();
    await page.waitForFunction(
      () => document.querySelector("#screen").options.length === 1,
    );
    const firstScreenText = text;
    assert.equal(await page.locator("#screen").inputValue(), "0");
    assert.equal(
      await page
        .locator('#tree [data-path="/screens/0"]')
        .getAttribute("aria-selected"),
      "true",
    );
    assert.equal(await page.locator("#emptyDocument").isVisible(), false);
    await page.locator("#newScreen").click();
    await page.locator("#newScreenName").fill("second_screen");
    await page.locator('#newScreenType [data-type="VerticalContainer"]').click();
    assert.equal(
      await page.locator("#newDocumentKind").count(),
      0,
      "An existing document keeps its dialect",
    );
    await page
      .locator("#newScreenDialog")
      .getByRole("button", { name: "Create", exact: true })
      .click();
    await page.waitForFunction(
      () => document.querySelector("#screen").options.length === 2,
    );
    const secondScreenText = text;
    assert.equal(await page.locator("#screen").inputValue(), "1");
    await send({ type: "document", text: firstScreenText });
    assert.equal(
      await page.locator("#screen").inputValue(),
      "0",
      "Undo restores the previous screen",
    );
    await send({ type: "document", text: secondScreenText });
    assert.equal(
      await page.locator("#screen").inputValue(),
      "1",
      "Redo restores the created screen selection",
    );
    assert.equal(
      await page
        .locator('#tree [data-path="/screens/1"]')
        .getAttribute("aria-selected"),
      "true",
    );
    await page.locator("#newScreen").click();
    await page.locator("#newScreenName").fill("first_screen");
    await page
      .locator("#newScreenDialog")
      .getByRole("button", { name: "Create", exact: true })
      .click();
    assert.equal(await page.locator("#newScreenDialog").isVisible(), true);
    assert.match(
      await page.locator('#newScreenDialog [role="alert"]').textContent(),
      /unique/,
    );
    await page
      .locator("#newScreenDialog")
      .getByRole("button", { name: "Close", exact: true })
      .click();
    await page.locator("#screen").selectOption("0");
    assert.equal(
      await page.locator("#tree .tree-row").first().getAttribute("data-path"),
      "/screens/0",
    );
    const createdFile = await rpc("encode", { text: secondScreenText });
    const createdReadback = await rpc("decode", { data: createdFile.data });
    assert.deepEqual(
      JSON.parse(createdReadback.text).screens.map((screen) => [
        screen.type,
        screen.name,
      ]),
      [
        ["StackContainer", "first_screen"],
        ["VerticalContainer", "second_screen"],
      ],
    );
    await fs.writeFile(
      path.join(project, "build/ui-new-screens.bgin"),
      Buffer.from(createdFile.data, "base64"),
    );
    text = JSON.stringify({
      name: "sprite_library",
      dialect: "ui",
      screens: [],
    });
    await send({ type: "document", text });
    await page.locator("#newScreen").click();
    await page.locator("#newDocumentKind").selectOption("sprites");
    assert.equal(await page.locator("#newScreenType").getAttribute("data-value"), "Sprite");
    assert.equal(await page.locator('#newScreenType [role="option"]').count(), 1);
    await page
      .locator("#newScreenDialog")
      .getByRole("button", { name: "Create", exact: true })
      .click();
    await page.waitForFunction(
      () => document.querySelector("#screen").options.length === 1,
    );
    assert.equal(JSON.parse(text).dialect, "sprites");
    assert.equal(JSON.parse(text).screens[0].type, "Sprite");
    await rpc("encode", { text });
    assert.equal(
      renderCount,
      rendersBeforeEmpty,
      "Creating and switching screens never renders automatically",
    );
    // New controls work on the fixed catalog, screen roots and the native clipboard protocol.
    text = initial;
    await send({ type: "document", text });
    const rootRow = '#tree [data-path="/screens/0"]';
    await page.locator(rootRow).click({ button: "right" });
    await page.getByRole("menuitem", { name: "Expand all", exact: true }).click();
    assert.ok(await page.locator('#tree [data-path="/screens/0/children/0/children/0"]').count());
    await page.locator(rootRow).click({ button: "right" });
    await page.getByRole("menuitem", { name: "Collapse all", exact: true }).click();
    assert.equal(await page.locator('#tree .tree-row').count(), 1);
    await page.locator(rootRow).click({ button: "right" });
    await page.getByRole("menuitem", { name: "Cut", exact: true }).click();
    await page.locator('#pasteScreenEmpty').waitFor();
    assert.equal(JSON.parse(text).screens.length, 0);
    assert.equal(JSON.parse(clipboard).name, JSON.parse(initial).screens[0].name);
    await page.locator('#pasteScreenEmpty').click();
    await page.locator(rootRow).waitFor();
    await rpc("encode", { text });
    await page.locator(rootRow).click({ button: "right" });
    await page.getByRole("menuitem", { name: "Duplicate", exact: true }).click();
    assert.equal(JSON.parse(text).screens.length, 2);
    await page.locator('#moveUp').click();
    assert.equal(await page.locator('#screen').inputValue(), '0');
    assert.match(JSON.parse(text).screens[0].name, /_copy$/);
    await page.locator('#moveDown').click();
    assert.equal(await page.locator('#screen').inputValue(), '1');
    await page.locator('#editorSettings').click();
    await page.locator('#interfaceLanguage').selectOption('ru');
    await page.waitForFunction(() => document.documentElement.lang === 'ru');
    await page.locator('#interfaceLanguage').selectOption('en');
    await page.waitForFunction(() => document.documentElement.lang === 'en');
    await page.keyboard.press('Escape');
    await send({ type: 'termsRequired', uiLanguage: 'en' });
    await page.locator('#termsDialog').waitFor();
    assert.equal(await page.locator('#termsDialog details').getAttribute('open'), null);
    await page.locator('#termsDialog summary').click();
    assert.match(await page.locator('#termsDialog').textContent(), /mindkeyboard/);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(50);
    assert.equal(termsDismissals, 1, 'Closing first terms sends the channel visit action');
    assert.equal(acceptedTerms, 0, 'Closing terms is not acceptance');
    await page.locator('#banner button').click();
    await page.locator('#acceptTerms').click();
    await page.waitForTimeout(100);
    assert.equal(acceptedTerms, 1, 'Acceptance is explicit');
    assert.equal(termsDismissals, 2, 'Acceptance also closes the first-entry terms dialog');
    text = JSON.stringify({ name: "templates", dialect: "templates", screens: [] });
    await send({ type: "document", text });
    await page.locator('#newScreen').click();
    const styleCard = page.locator('#newScreenType [data-type="TextStyle"]');
    await styleCard.locator('span').click();
    assert.equal(await page.locator('#newScreenType').getAttribute('data-value'), 'TextStyle');
    assert.ok((await styleCard.locator('svg').boundingBox()).width >= 36);
    const cards = await page.locator('#newScreenType [role="option"]').evaluateAll(items => items.map(i => {const r=i.getBoundingClientRect();return {x:r.x,y:r.y};}));
    assert.ok(cards.some((a,i) => cards.some((b,j) => i !== j && a.y === b.y && a.x !== b.x)), 'Type choices form a grid');
    assert.equal(await page.locator('#newScreenType .type-docs').count(), await page.locator('#newScreenType [role="option"]').count(), 'Every screen type has its own documentation button');
    await page.screenshot({path: path.join(project, 'build/editor-types-grid-047.png')});
    await page.locator('#newScreenDialog').getByRole('button', {name:'Create',exact:true}).click();
    assert.equal(JSON.parse(text).screens[0].type, 'TextStyle');
    await rpc('encode', { text });
    assert.equal(errors.length, 0, errors.join("\n"));
    console.log(
      `BGIN_PERFORMANCE: root selection, 9721 nodes: ${selectionMs.toFixed(1)} ms; zero automatic renders.`,
    );
    console.log(
      "BGIN_UI_TESTS: manual render only, cached selection, cancellation, resources before/during render, browse/save, icons, virtual tree, context menu, clipboard, fixed parameters, modal search/resources, localization, JSON, empty drafts and new screens: passed.",
    );
  } finally {
    await browser.close();
  }
})()
  .catch((e) => {
    console.error(e);
    process.exitCode = 1;
  })
  .finally(() => p.kill());
