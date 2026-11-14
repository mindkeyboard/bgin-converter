# Binary GIN Editor 0.6.3

Practical guide for the 0.6.3 sources. Extension 0.6.3 uses worker version 0.6.3 with bundled MCP.
[User guide](https://octane-loader.utmsoft.ru/en/guide/octane-devtools/bgin-editor/v0.6.3/).

Opening detects the document's wire mode. Saving preserves it. New documents
offer ~0.0.2, ~1.6.0, ~3.7.0 and ~5.8.0. Use the sidebar's BGIN → BGIN converter
with an explicit target for another mode. Conversion rejects data loss.
Unknown identifiers, property variants and animation channels are preserved.
Special second-table records and inconsistent catalogs are currently rejected.

In **Resources**, auto-fill offers **Extracted archive** and
**Unpacked zdata / Play Asset Delivery**. For zdata, choose its root, `files`,
`assetpacks` or a specific `assets/data` directory. The tool discovers the
common pack's GUI/fonts and texture packs without hardcoded version numbers.
Multiple common-pack versions require an explicit directory choice.

Only needed folders are required. Keep selected GUI files (usually including
widgets and sprites), the required fonts and texture JPKs. Alternatively,
configure independent GUI, texture and font directories. The texture root can
contain loose files, JPKs or PAD texture packs. ZIP-based JPK members are read
on demand; original archives remain unchanged. Duplicate texture names are
reported rather than chosen arbitrarily.

**BGIN: Convert Texture Separately** exports a PVR texture into another file
for ~1.6.0. Removing outer compression preserves GPU blocks and all mips;
incompatible ETC2/ASTC is rejected. RGBA8 decodes each mip and increases size.
Convert a separate alpha texture explicitly as well. Game loading has not yet
been verified. BGIN saving never transcodes textures.

The MCP sidebar shows multiple clients and their actions. You can stop an
operation, pause a client's edits or disconnect it. Applied changes use normal
VS Code undo. Client previews appear in a gallery and are marked stale after
the document or resources change.

The stdio MCP adapter, dependencies and legacy Zstd support are bundled in
the VSIX. No Python, pip or source checkout is required. **Copy MCP configuration**
copies ready `command` and `args` settings. Rendering requires Chrome or Edge
installed where the adapter runs; the driver is bundled.

Use **Copy client command**, and set a distinct `--client-name` for each client.
The discovery file identifies one VS Code window and contains a local access
token. Start with `bgin_editor`, read a document, then send its revision as
`base_revision` with a unique `operation_id`. Unsaved human edits belong to the
same live document; stale writes fail and require rereading it. Subscribe to
`bgin://editor/state` for updates. Whether notifications immediately enter a
running model's context depends on the client application.

Modern preview still uses the older layout model. Variant selection and the
new hashed color channels are preserved but not reproduced by the renderer.

## Open-screen inspection in extension 0.6.1

After a manual render, choose Normal, Spread branches or X-ray. Branch depth
splits the current screen into smaller visual groups while retaining the layout
calculated with its ancestors. Ancestor paint gets its own cell. The top-layer
slider hides painted objects in reverse paint order; it does not infer engine
state or logical layer semantics. Reset view restores the composition.
Inspection covers the whole current screen despite tree selection, uses cached
paint and never edits the document or triggers a render. Changed documents and
resources require another explicit refresh. The native worker now also includes MCP.

The screen-name button opens a searchable dialog with All and By prefix views.
Prefixes are derived from names using separators and CamelCase. Select a result
and Open, or double-click. Large result lists are virtualized.

Extension 0.6.3 shows each screen's object count, including the root and all
nested children and tracks. External definitions and animation frames are not
counted as additional stored objects.
