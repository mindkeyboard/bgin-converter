const vscode = require("vscode");
const assert = require("node:assert/strict");
const path = require("node:path");
const delay = (ms) => new Promise((r) => setTimeout(r, ms));
exports.run = async () => {
  const extension = vscode.extensions.getExtension("a8devtools.bgin-editor");
  assert(extension, "Extension registered");
  const {
    provider,
    backend,
    discoverResources,
    scanBginFolder,
    saveResourceFolders,
    converter,
    documentationUrl,
    editorGuideUrl,
  } = await extension.activate();
  assert.deepEqual(await backend.call("ping"), { ready: true });
  assert.equal(editorGuideUrl("ru"), "https://octane-loader.utmsoft.ru/ru/guide/octane-devtools/bgin-editor/v0.5.0/");
  assert.equal(editorGuideUrl("en"), "https://octane-loader.utmsoft.ru/en/guide/octane-devtools/bgin-editor/v0.5.0/");
  assert.match(documentationUrl("en", "gin::LabelWidget"), /\/en\/reference\/\?view=class&name=gin::LabelWidget$/);
  assert.match(documentationUrl("ru", "https://wrong.invalid"), /name=gin$/);
  const onboardingState = new Map();
  let firstAcceptVisits = 0;
  const memory = { get: (key, fallback) => onboardingState.has(key) ? onboardingState.get(key) : fallback,
    update: async (key, value) => { onboardingState.set(key, value); } };
  const oneVisit = new provider.onboarding.constructor(memory, async () => { firstAcceptVisits++; return true; });
  await Promise.all([oneVisit.complete(), oneVisit.complete()]);
  await new provider.onboarding.constructor(memory, async () => { firstAcceptVisits++; return true; }).complete();
  assert.equal(firstAcceptVisits, 1, "First acceptance, simultaneous closes and reopening share one persisted visit");
  const calls = [],
    originalCall = backend.call.bind(backend);
  backend.call = (method, params) => {
    calls.push(method);
    return originalCall(method, params);
  };
  const uri = vscode.Uri.joinPath(
    vscode.workspace.workspaceFolders[0].uri,
    "fixture.bgin",
  );
  const original = Buffer.from(await vscode.workspace.fs.readFile(uri));
  if (process.env.BGIN_LEGACY_CORPUS) {
    const legacyRoot = process.env.BGIN_LEGACY_CORPUS;
    const indexed = await scanBginFolder(legacyRoot);
    assert.deepEqual(indexed.errors, [], "All old namespaces are indexed without encoding errors");
    assert.equal(Object.keys(indexed.bindings).length, 9);
    const oldUri = vscode.Uri.file(path.join(legacyRoot, "profile.bgin"));
    const oldBytes = Buffer.from(await vscode.workspace.fs.readFile(oldUri));
    const legacyCopy = vscode.Uri.joinPath(vscode.workspace.workspaceFolders[0].uri, "legacy-profile.bgin");
    await vscode.workspace.fs.writeFile(legacyCopy, oldBytes);
    await vscode.commands.executeCommand("vscode.openWith", legacyCopy, "bgin.editor");
    let oldDocument;
    for (let i = 0; i < 100 && !oldDocument; i++) {
      oldDocument = provider.documents.get(legacyCopy.toString());
      if (!oldDocument) await delay(100);
    }
    assert(oldDocument?.panels.size, "Old BGIN opens in the real custom editor");
    assert.equal(JSON.parse(oldDocument.text).format, "legacy");
    const legacyOutput = legacyCopy.with({ path: legacyCopy.path + ".saved.bgin" });
    await provider.saveCustomDocumentAs(oldDocument, legacyOutput);
    assert.deepEqual(Buffer.from(await vscode.workspace.fs.readFile(legacyOutput)), oldBytes, "Old custom editor Save As is byte exact");
    const oldTree = JSON.parse(oldDocument.text);
    oldTree.screens[0].name += "_host_edited";
    provider.edit(oldDocument, JSON.stringify(oldTree));
    await vscode.commands.executeCommand("workbench.action.files.save");
    const readback = await backend.call("decode", { data: Buffer.from(await vscode.workspace.fs.readFile(legacyCopy)).toString("base64") });
    assert.equal(JSON.parse(readback.text).screens[0].name, oldTree.screens[0].name);
    assert.equal(JSON.parse(readback.text).format, "legacy");
    assert.deepEqual(Buffer.from(await vscode.workspace.fs.readFile(oldUri)), oldBytes);
    await vscode.commands.executeCommand("workbench.action.closeActiveEditor");
  }
  const unopenedDrafts = ["unopened-a.bgin", "unopened-b.bgin"].map(name => vscode.Uri.joinPath(vscode.workspace.workspaceFolders[0].uri, name));
  for (const file of unopenedDrafts) await vscode.workspace.fs.writeFile(file, new Uint8Array());
  for (let i = 0; i < 80 && unopenedDrafts.some(file => !vscode.languages.getDiagnostics(file).some(d => d.severity === vscode.DiagnosticSeverity.Warning)); i++) await delay(100);
  for (const file of unopenedDrafts) {
    const diagnostics = vscode.languages.getDiagnostics(file);
    assert(diagnostics.some(d => d.severity === vscode.DiagnosticSeverity.Warning), "Each unopened empty BGIN has a workspace warning");
    assert(!diagnostics.some(d => d.severity === vscode.DiagnosticSeverity.Error));
  }
  assert(extension.packageJSON.contributes.viewsContainers.activitybar.some(v => v.id === "bgin"));
  await vscode.commands.executeCommand("bgin.converter.focus");
  const convertedJson = uri.with({ path: uri.path.replace(/\.bgin$/, ".converted.json") });
  const convertedBinary = uri.with({ path: uri.path.replace(/\.bgin$/, ".converted.bgin") });
  for (const file of [convertedJson, convertedBinary]) {
    try { await vscode.workspace.fs.delete(file); } catch {}
  }
  await converter.convert(uri, convertedJson, "json");
  await converter.convert(convertedJson, convertedBinary, "bgin");
  assert.deepEqual(Buffer.from(await vscode.workspace.fs.readFile(convertedBinary)), original, "Sidebar conversion round trip is byte exact");
  await assert.rejects(() => converter.convert(uri, uri, "json"), /different files/);
  // Save the real host-generated HTML for the browser accessibility and message test.
  const converterView = { webview: { options: {}, html: "", onDidReceiveMessage: () => ({ dispose() {} }) }, onDidDispose: () => ({ dispose() {} }) };
  converter.resolveWebviewView(converterView);
  await vscode.workspace.fs.writeFile(vscode.Uri.joinPath(vscode.workspace.workspaceFolders[0].uri, "converter.html"), Buffer.from(converterView.webview.html));
  await vscode.commands.executeCommand("vscode.openWith", uri, "bgin.editor");
  let doc;
  for (let i = 0; i < 100 && !doc; i++) {
    doc = provider.documents.get(uri.toString());
    await delay(100);
  }
  assert(doc, "Custom editor opened a binary file");
  assert(doc.panels.size === 1, "File has a custom webview editor");
  // Exercise the host-side terms gate with the real registered VS Code configuration.
  const termsSettings = vscode.workspace.getConfiguration("bgin");
  const previousTerms = termsSettings.inspect("acceptedTermsVersion").globalValue;
  const previousChannelVisit = provider.context.globalState.get("bgin.firstTermsChannelVisited");
  const previousChannelOpener = provider.onboarding.openChannel;
  let channelVisits = 0;
  provider.onboarding.openChannel = async () => { channelVisits++; return true; };
  await provider.context.globalState.update("bgin.firstTermsChannelVisited", undefined);
  await termsSettings.update("acceptedTermsVersion", "", vscode.ConfigurationTarget.Global);
  const gateMessages = [];
  let receiveGate, disposeGate;
  const gatePanel = {
    webview: {
      options: {}, html: "", cspSource: "test",
      asWebviewUri: uri => uri,
      postMessage: message => { gateMessages.push(message); return Promise.resolve(true); },
      onDidReceiveMessage: handler => { receiveGate = handler; },
    },
    onDidChangeViewState: () => {},
    onDidDispose: handler => { disposeGate = handler; },
  };
  await provider.resolveCustomEditor(doc, gatePanel);
  await receiveGate({ type: "ready" });
  assert(gateMessages.some(m => m.type === "termsRequired"));
  assert(!gateMessages.some(m => m.type === "init"));
  await receiveGate({ type: "firstTermsDismissed" });
  assert.equal(channelVisits, 1, "First close opens the channel");
  assert.equal(termsSettings.inspect("acceptedTermsVersion").globalValue, "", "Closing does not accept terms");
  await receiveGate({ type: "firstTermsDismissed" });
  assert.equal(channelVisits, 1, "Repeated close never reopens the channel");
  const gatedText = doc.text;
  await receiveGate({ type: "edit", text: "{}" });
  assert.equal(doc.text, gatedText, "Unaccepted editor cannot edit");
  await receiveGate({ type: "acceptTerms", version: "wrong-version" });
  assert.equal(termsSettings.inspect("acceptedTermsVersion").globalValue, "");
  await receiveGate({ type: "acceptTerms", version: "2026-10-22" });
  assert.equal(termsSettings.inspect("acceptedTermsVersion").globalValue, "2026-10-22");
  assert(gateMessages.some(m => m.type === "termsAccepted"));
  assert.equal(channelVisits, 1, "Acceptance after closing keeps the visit one-time");
  await receiveGate({ type: "ready" });
  assert(gateMessages.some(m => m.type === "init"));
  disposeGate();
  provider.onboarding.openChannel = previousChannelOpener;
  await provider.context.globalState.update("bgin.firstTermsChannelVisited", previousChannelVisit);

  const clean = doc.text,
    changed = JSON.parse(clean);
  changed.screens[0].name = "edited_in_vscode";
  provider.edit(doc, JSON.stringify(changed, null, 2));
  await vscode.commands.executeCommand("workbench.action.files.save");
  let disk = await backend.call("decode", {
    data: Buffer.from(await vscode.workspace.fs.readFile(uri)).toString(
      "base64",
    ),
  });
  assert.equal(JSON.parse(disk.text).screens[0].name, "edited_in_vscode");
  await vscode.commands.executeCommand("undo");
  await delay(100);
  assert.equal(doc.text, clean, "VS Code undo restores the document");
  await vscode.commands.executeCommand("redo");
  await delay(100);
  assert.equal(
    JSON.parse(doc.text).screens[0].name,
    "edited_in_vscode",
    "VS Code redo",
  );
  provider.edit(doc, '{"screens": [}');
  await delay(600);
  assert(
    vscode.languages
      .getDiagnostics(uri)
      .some((d) => d.severity === vscode.DiagnosticSeverity.Error),
    "Syntax error published to Problems",
  );
  const before = Buffer.from(await vscode.workspace.fs.readFile(uri));
  await assert.rejects(() => provider.saveCustomDocument(doc));
  assert.deepEqual(
    Buffer.from(await vscode.workspace.fs.readFile(uri)),
    before,
    "Invalid JSON never overwrites BGIN",
  );
  const backupUri = vscode.Uri.joinPath(
    vscode.workspace.workspaceFolders[0].uri,
    "draft.backup",
  );
  const backup = await provider.backupCustomDocument(doc, {
    destination: backupUri,
  });
  const restored = await provider.openCustomDocument(
    vscode.Uri.joinPath(
      vscode.workspace.workspaceFolders[0].uri,
      "restored.bgin",
    ),
    { backupId: backup.id },
  );
  assert.equal(
    restored.text,
    doc.text,
    "Invalid JSON is recoverable from backup",
  );
  restored.dispose();
  await backup.delete();
  await provider.revertCustomDocument(doc);
  await delay(600);
  assert.equal(JSON.parse(doc.text).screens[0].name, "edited_in_vscode");
  assert.equal(
    vscode.languages
      .getDiagnostics(uri)
      .filter((d) => d.source !== "Binary GIN resources").length,
    0,
    "Revert clears syntax errors",
  );
  const copy = vscode.Uri.joinPath(
    vscode.workspace.workspaceFolders[0].uri,
    "save-as.bgin",
  );
  await provider.saveCustomDocumentAs(doc, copy);
  assert.deepEqual(
    Buffer.from(await vscode.workspace.fs.readFile(copy)),
    before,
    "Save As compiles binary",
  );
  assert(!calls.includes("render"), "Editor never renders automatically");
  assert(
    !calls.includes("validate"),
    "Edits never compile BGIN in the background",
  );
  const blankUri = vscode.Uri.joinPath(
    vscode.workspace.workspaceFolders[0].uri,
    "empty-new.bgin",
  );
  await vscode.workspace.fs.writeFile(blankUri, new Uint8Array());
  const blankCalls = calls.length;
  await vscode.commands.executeCommand(
    "vscode.openWith",
    blankUri,
    "bgin.editor",
  );
  let blank;
  for (let i = 0; i < 100 && !blank?.panels.size; i++) {
    blank = provider.documents.get(blankUri.toString());
    await delay(100);
  }
  assert(blank?.panels.size, "A zero-byte BGIN opens in the custom editor");
  assert.deepEqual(JSON.parse(blank.text), {
    screens: [],
  });
  assert.equal(
    (await vscode.workspace.fs.stat(blankUri)).size,
    0,
    "Opening an empty file never writes it",
  );
  assert(
    !calls
      .slice(blankCalls)
      .some((method) =>
        ["encode", "decode", "validate", "render"].includes(method),
      ),
    "Empty file opening requires no Python parsing, compilation or render",
  );
  const beforeEmptySave = calls.length;
  await provider.saveCustomDocument(blank);
  assert(
    !calls.slice(beforeEmptySave).includes("encode"),
    "Saving an unnamed empty draft needs no compiler",
  );
  assert.equal((await vscode.workspace.fs.stat(blankUri)).size, 0);
  await delay(400);
  assert(vscode.languages.getDiagnostics(blankUri).some(d => d.severity === vscode.DiagnosticSeverity.Warning), "Unnamed empty file has a warning");
  assert(!vscode.languages.getDiagnostics(blankUri).some(d => d.severity === vscode.DiagnosticSeverity.Error), "Empty storage is not an error");
  assert.throws(() => provider.edit(blank, '{"name":"bypass","screens":[]}'), /before editing/, "Ordinary edits cannot bypass the required name");
  assert.throws(() => provider.nameDocument(blank, '   '), /blank/);
  const nameMessages = [];
  let receiveName, disposeName;
  const namePanel = { webview: { options: {}, html: "", cspSource: "test", asWebviewUri: uri => uri,
    postMessage: message => { nameMessages.push(message); return Promise.resolve(true); }, onDidReceiveMessage: fn => { receiveName = fn; } },
    onDidChangeViewState: () => {}, onDidDispose: fn => { disposeName = fn; } };
  await provider.resolveCustomEditor(blank, namePanel);
  await receiveName({ type: "ready" });
  assert(nameMessages.some(m => m.type === "nameRequired"));
  assert(!nameMessages.some(m => m.type === "init"), "Editor contents stay gated until a name is set");
  await receiveName({ type: "setDocumentName", name: "My Interface" });
  assert.equal(JSON.parse(blank.text).name, "My Interface");
  assert(nameMessages.some(m => m.type === "nameAccepted"));
  await receiveName({ type: "ready" });
  assert(nameMessages.some(m => m.type === "init"));
  disposeName();
  await delay(300);
  await vscode.commands.executeCommand("vscode.openWith", blankUri, "bgin.editor");
  const draft = JSON.parse(blank.text);
  draft.screens.push({
    type: "StackContainer",
    name: "new_screen",
    properties: {},
    children: [],
  });
  const firstScreen = JSON.stringify(draft, null, 2);
  provider.edit(blank, firstScreen);
  await delay(100);
  await vscode.commands.executeCommand("undo");
  await delay(100);
  assert.equal(
    JSON.parse(blank.text).screens.length,
    0,
    "Undo removes the first newly created screen",
  );
  await vscode.commands.executeCommand("redo");
  await delay(100);
  assert.equal(blank.text, firstScreen, "Redo restores the first screen");
  await provider.revertCustomDocument(blank);
  assert.equal(
    JSON.parse(blank.text).screens.length,
    0,
    "Revert can read the untouched zero-byte file",
  );
  provider.nameDocument(blank, "My Interface");
  provider.edit(blank, firstScreen);
  assert.equal(blank.text, firstScreen);
  await vscode.commands.executeCommand("workbench.action.files.save");
  const newBinary = Buffer.from(await vscode.workspace.fs.readFile(blankUri));
  assert(newBinary.length > 0, "First save creates a binary document");
  const newReadback = JSON.parse(
    (await backend.call("decode", { data: newBinary.toString("base64") })).text,
  );
  assert.equal(newReadback.name, "My Interface");
  assert.equal(newReadback.screens[0].name, "new_screen");
  const badUri = vscode.Uri.joinPath(
    vscode.workspace.workspaceFolders[0].uri,
    "bad-not-empty.bgin",
  );
  const badBytes = Buffer.from("not a BGIN file");
  await vscode.workspace.fs.writeFile(badUri, badBytes);
  await assert.rejects(
    () => provider.openCustomDocument(badUri, {}),
    "Nonempty corrupt files are not new documents",
  );
  assert.deepEqual(
    Buffer.from(await vscode.workspace.fs.readFile(badUri)),
    badBytes,
  );
  assert(!provider.documents.has(badUri.toString()));
  const untitled = await provider.openCustomDocument(
    vscode.Uri.parse("untitled:Untitled-1.bgin"),
    {},
  );
  assert.equal(
    JSON.parse(untitled.text).screens.length,
    0,
    "Untitled drafts need no filesystem entry",
  );
  untitled.set(firstScreen);
  const untitledSaveUri = vscode.Uri.joinPath(
    vscode.workspace.workspaceFolders[0].uri,
    "untitled-saved.bgin",
  );
  await provider.saveCustomDocumentAs(untitled, untitledSaveUri);
  assert.deepEqual(
    Buffer.from(await vscode.workspace.fs.readFile(untitledSaveUri)),
    newBinary,
    "Untitled Save As compiles the edited draft",
  );
  untitled.dispose();
  assert(
    (await vscode.commands.getCommands(true)).includes("bgin.newFile"),
    "New BGIN file command is registered",
  );
  assert(
    !calls.includes("render"),
    "New document creation never renders automatically",
  );
  await vscode.commands.executeCommand("vscode.openWith", uri, "bgin.editor");
  const panel = [...doc.panels][0],
    session = provider.previews.get(panel);
  const running = session.render(
    doc,
    700,
    { width: 800, height: 480 },
    {},
    () => {},
  );
  const workerPid = session.worker.process.pid;
  assert.notEqual(
    workerPid,
    backend.process.pid,
    "Preview and document use independent workers",
  );
  await Promise.race([
    backend.call("validate", { text: doc.text }),
    delay(2000).then(() => {
      throw new Error("Save worker blocked by preview");
    }),
  ]);
  let resourcePanelOpened = false;
  const originalPost = panel.webview.postMessage.bind(panel.webview);
  panel.webview.postMessage = (m) => {
    if (m.type === "openResources") resourcePanelOpened = true;
    return originalPost(m);
  };
  await vscode.commands.executeCommand("bgin.resources");
  assert(
    resourcePanelOpened,
    "Resource command opens the editor panel during rendering",
  );
  let resourceSaveReply;
  panel.webview.postMessage = (message) => {
    if (message.type === "resourcesSaved") resourceSaveReply = message;
    return originalPost(message);
  };
  const resourceDirectory = path.join(
      path.dirname(uri.fsPath),
      "resource-folders",
    ),
    bginDirectory = path.join(resourceDirectory, "gui"),
    textureDirectory = path.join(resourceDirectory, "textures_android"),
    fontDirectory = path.join(resourceDirectory, "texter_fonts"),
    boundFile = path.join(bginDirectory, "custom-library.bgin");
  for (const folder of [bginDirectory, textureDirectory, fontDirectory])
    await vscode.workspace.fs.createDirectory(vscode.Uri.file(folder));
  await vscode.workspace.fs.writeFile(vscode.Uri.file(boundFile), original);
  const discovered = await discoverResources(resourceDirectory);
  assert.equal(
    discovered.resourceSettings.bginRoot,
    bginDirectory,
    "Discovery chooses the gui folder",
  );
  assert.equal(
    (await scanBginFolder(resourceDirectory)).bindings[JSON.parse(clean).name],
    boundFile,
    "Archive root scan reads internal namespaces, not filenames",
  );
  const rootExtra = vscode.Uri.file(path.join(resourceDirectory, "root.bgin")),
    rootName = Buffer.from("RootLibrary"),
    rootHeader = Buffer.from(original.subarray(0, 10));
  rootHeader.writeUInt16LE(rootName.length, 8);
  await vscode.workspace.fs.writeFile(
    rootExtra,
    Buffer.concat([rootHeader, rootName]),
  );
  assert.equal(
    (await discoverResources(resourceDirectory)).resourceSettings.bginRoot,
    resourceDirectory,
    "Auto-fill retains BGIN namespaces in both root and gui",
  );
  const rootScan = await scanBginFolder(resourceDirectory);
  assert(rootScan.bindings.RootLibrary);
  assert(rootScan.bindings[JSON.parse(clean).name]);
  await vscode.workspace.fs.delete(rootExtra);
  const duplicate = vscode.Uri.file(path.join(bginDirectory, "duplicate.bgin"));
  await vscode.workspace.fs.writeFile(duplicate, original);
  const ambiguous = await scanBginFolder(resourceDirectory);
  assert.equal(
    Object.keys(ambiguous.bindings).length,
    0,
    "Ambiguous namespace is never chosen arbitrarily",
  );
  assert(
    ambiguous.errors.some((error) =>
      error.includes("Duplicate BGIN namespace"),
    ),
  );
  await vscode.workspace.fs.delete(duplicate);
  await vscode.env.clipboard.writeText(
    JSON.stringify(JSON.parse(clean).screens[0]),
  );
  assert.equal(
    JSON.parse(await vscode.env.clipboard.readText()).name,
    JSON.parse(clean).screens[0].name,
    "System clipboard accepts object JSON",
  );
  const folders = {
    assetRoot: resourceDirectory,
    bginRoot: bginDirectory,
    textureRoot: textureDirectory,
    fontRoot: fontDirectory,
  };
  await provider.applyResources(doc, panel, folders);
  assert.equal(
    resourceSaveReply?.error,
    undefined,
    "Resource panel persists folders without Python",
  );
  assert.equal(
    resourceSaveReply.notice,
    "",
    "Registered settings save without a fallback notice",
  );
  assert.deepEqual(
    vscode.workspace.getConfiguration("bgin", uri).get("resourceFolders"),
    folders,
    "All folder paths including textureRoot are atomically registered and persisted",
  );
  const pendingKey = provider.resourceStateKey(doc),
    fallbackFolders = { ...folders, bginRoot: resourceDirectory };
  let updateCalls = 0;
  const notice = await saveResourceFolders(
    {
      inspect: () => undefined,
      update: () => {
        updateCalls++;
        throw Error("Unregistered");
      },
    },
    provider.context.workspaceState,
    pendingKey,
    fallbackFolders,
    vscode.ConfigurationTarget.WorkspaceFolder,
  );
  assert.equal(
    updateCalls,
    0,
    "Unregistered configuration never attempts partial individual writes",
  );
  assert.match(notice, /Reload Window/);
  assert.deepEqual(
    provider.context.workspaceState.get(pendingKey),
    fallbackFolders,
    "Draft persists despite stale setting registration",
  );
  assert.equal(
    provider.config(doc).resources.bginRoot,
    resourceDirectory,
    "Persisted fallback is effective immediately",
  );
  const sibling = await provider.openCustomDocument(copy, {}),
    siblingMessages = [];
  let siblingCancelled = 0;
  const siblingPanel = {
    webview: { postMessage: (message) => siblingMessages.push(message) },
  };
  sibling.panels.add(siblingPanel);
  provider.previews.set(siblingPanel, {
    cancel: () => siblingCancelled++,
  });
  const callsBeforeRefresh = calls.filter(
    (method) => method === "render",
  ).length;
  await provider.refreshResourceDocuments(doc);
  assert(
    siblingCancelled > 0,
    "Fallback cancels a sibling document's stale preview",
  );
  assert.equal(
    siblingMessages.find((message) => message.type === "config")?.resources
      .bginRoot,
    resourceDirectory,
    "Fallback updates every open document sharing its resource folders",
  );
  assert(provider.watchers.get(sibling)?.length > 0);
  assert.equal(
    calls.filter((method) => method === "render").length,
    callsBeforeRefresh,
    "Resource synchronization never starts rendering",
  );
  provider.previews.delete(siblingPanel);
  sibling.panels.clear();
  sibling.dispose();
  await provider.context.workspaceState.update(pendingKey, undefined);
  const failedState = new Map();
  const failedNotice = await saveResourceFolders(
    {
      inspect: () => ({}),
      update: async () => {
        updateCalls++;
        throw Error("Unable to write User Settings");
      },
    },
    { update: async (key, value) => failedState.set(key, value) },
    "test",
    folders,
    vscode.ConfigurationTarget.Global,
  );
  assert.match(failedNotice, /saved for this workspace/);
  assert.deepEqual(
    failedState.get("test"),
    folders,
    "Settings write failure retains the entire draft",
  );
  assert.equal(
    updateCalls,
    1,
    "Only one settings object is written on failure",
  );
  session.cancel();
  await running;
  let previewAlive = true;
  for (let i = 0; i < 40 && previewAlive; i++) {
    try {
      process.kill(workerPid, 0);
    } catch {
      previewAlive = false;
    }
    if (previewAlive) await delay(50);
  }
  assert(!previewAlive, "Cancel terminates the actual preview process");
  assert.equal(
    session.worker.process,
    undefined,
    "Cancel terminates the preview process",
  );
  assert.equal(
    (await backend.call("validate", { text: doc.text })).valid,
    true,
    "Document worker survives cancellation",
  );
  const result = await backend.call("render", {
    text: doc.text,
    source: uri.fsPath,
    options: { width: 800, height: 480 },
    resources: { bindings: { Missing: path.join(uri.fsPath, "absent.bgin") } },
  });
  assert.match(result.svg, /<svg/);
  assert(
    result.errors.some((e) => e.message.includes("Missing")),
    "Broken binding reported",
  );
  await provider.applyResources(doc, panel, {
    ...folders,
    bginRoot: path.join(resourceDirectory, "missing-bgin"),
  });
  let broken = false;
  for (let i = 0; i < 100 && !broken; i++) {
    broken = vscode.languages
      .getDiagnostics(uri)
      .some((d) => d.message.includes("missing-bgin"));
    await delay(100);
  }
  assert(
    broken,
    "Missing BGIN folder reaches actual VS Code Problems through the webview",
  );
  await vscode.workspace
    .getConfiguration("bgin", uri)
    .update("resourceFolders", {}, vscode.ConfigurationTarget.WorkspaceFolder);
  await vscode.workspace.fs.writeFile(uri, original);
  await provider.revertCustomDocument(doc);
  await termsSettings.update("acceptedTermsVersion", previousTerms, vscode.ConfigurationTarget.Global);
  console.log(
    "BGIN_EXTENSION_TESTS: binary editing, empty/untitled drafts, first screen save, undo/redo, corrupt input rejection, Problems, zero automatic renders/compilations, independent workers, cancellation and resource panel command: passed.",
  );
  await vscode.commands.executeCommand("workbench.action.closeAllEditors");
};
