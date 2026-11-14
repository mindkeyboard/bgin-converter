# Binary GIN Editor

- Use at most three concurrent subagents, only for substantial independent work.
  Reuse completed results; do not restart agents for routine follow-up checks.
  Incident 2026-11-14: excessive delegation exhausted the user's usage budget.

- The four user-facing modes are approximately 0.0.2, 1.6.0, 3.7.0 and 5.8.0.
  Detect the wire profile when opening, preserve it when saving, and require an
  explicit target for cross-profile conversion. Keep portable JSON self-contained.
- Treat BGIN serialization, archive compression, GPU texture format and texture
  payload compression as separate capabilities. A successful preview does not
  prove that an older game can read the resource. Incident 2026-11-14: the user
  corrected the assumption that support for newer BGIN alone would make resources
  compatible with 1.6.0; real newer PVR files also use jlz4/zstd payload envelopes.
- Preserve unknown identifiers, variants and special records. Never silently
  discard them or infer engine semantics from byte layout. Reject unsupported
  writes before changing the destination.
- Connected MCP operations use the live VS Code document, including unsaved
  human edits. Enforce revision checks for every editing channel and keep normal
  undo/redo. Never silently fall back to an independent disk copy.
- Read-only inspection of private Play Asset Delivery paths may be blocked by
  Android. Keep inferred paths distinct from verified paths; do not change app
  data or installation to obtain a research input.

- For local transactional saves, replace the verified temporary file through the
  host filesystem rather than workspace.fs.rename: VS Code treats the latter
  as a file move and clears the destination undo history. Verify undo and redo
  after saving in a real Extension Host. Incident 2026-11-14.

- Keep the screen picker separate from inspecting the currently open screen.
  For overlapping content, propose visual scene-wide inspection that requires
  no prior object name or ID. Incident 2026-11-14: repeated suggestions about
  choosing screens and searching named containers missed the user's question.

- Transfer binary device resources with adb exec-out or adb pull, and compare
  copied bytes with device hashes or source archive CRCs. adb shell stdout can
  change binary bytes in this host environment. Incident 2026-11-14: copied
  font bytes were altered and a control render exposed invalid composite glyphs.
