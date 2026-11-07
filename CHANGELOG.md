# Changes

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
