# Changes

## 0.6.3 — 2026-11-14

- Bundle the stdio MCP adapter, its dependencies and browser driver in the native worker. Copy a ready command or MCP JSON from the sidebar; Python and pip setup are unnecessary.
- Check the packaged MCP handshake, editing skill, read/edit and independent export without Python on PATH.
- Use installed Chrome or Edge for MCP previews when no managed Chromium is available.

## 0.6.2 — 2026-11-14

- Show each screen's object count in both screen-picker views, including the root
  and all nested children and tracks. Counts are calculated once per opening.

## 0.6.1 — 2026-11-14

- Inspect the currently open screen with spread branches, adjustable branch depth,
  X-ray and a top-layer cutoff. These use cached paint, retain ancestor layout,
  and never edit BGIN or trigger a render.
- Replace the screen dropdown with a searchable dialog, all/prefix views and
  prefixes derived from the document's names. Results use a virtual tree.

## 0.6.0 — 2026-11-14

- Four explicit BGIN modes (~0.0.2, ~1.6.0, ~3.7.0, ~5.8.0), preserved on save;
  separate cross-mode conversion rejects data loss. Unsupported special records
  and inconsistent catalogs fail explicitly.
- Multiple MCP clients share unsaved VS Code documents, revisions and undo.
  The sidebar shows client actions; users can pause, stop or disconnect them.
  Client renders appear in the editor, with stale results marked.
- Resource auto-fill supports partial extracted zdata/PAD as well as old archives.
  Texture JPK members are loaded on demand without unpacking the whole game.
- Preview decodes modern ETC2/ASTC and LZ4/legacy Zstd texture envelopes.
  A separate texture command exports unwrapped or RGBA8 PVR; game loading remains
  unverified. BGIN saving never transcodes textures.

## 0.5.0 — 2026-11-07

- Platform-specific packages cover Windows x64 and ARM64, macOS Intel and Apple
  Silicon, Linux x64, ARM64 and ARMv7, and Alpine x64 and ARM64.
- Each VSIX bundles a compiled BGIN worker and its preview libraries. System
  Python and first-run dependency downloads are unnecessary.

## 0.4.16 — 2026-11-02

- Fixed pasting an object into a container when copied JSON includes its list
  separator, a surrounding JSON code block, or an omitted pair of outer braces.
- Invalid clipboard text now shows a clear message and leaves the document unchanged.
- Nested object properties and resource references are retained when pasting.
