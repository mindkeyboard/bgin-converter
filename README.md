# Binary GIN Editor

Open, edit, and preview game interface files (`.bgin`) in VS Code.

## Quick install

In VS Code 1.105 or later, open **Extensions → … → Install from VSIX…**
and select the package for your platform. The package includes the BGIN worker,
so a separate Python installation is unnecessary.

[Download](https://github.com/mindkeyboard/bgin-converter/releases/latest) ·
[Installation and user guide](https://octane-loader.utmsoft.ru/en/guide/octane-devtools/bgin-editor/v0.6.3/) ·
[Русский](README.ru.md)

Created by **mindkeyboard**.

Version 0.6.3: [formats, partial zdata resources and MCP connections](development/editor-0.6.md).

The ~0.0.2, ~1.6.0, ~3.7.0 and ~5.8.0 mode labels identify BGIN formats around those Asphalt 8 releases, rather than strict game-version requirements. Files from neighboring A8 releases and other games of the same period may work; compatibility depends on the actual file structure and is not guaranteed. Saving retains the source format; conversion to another mode is explicit. Texture conversion is separate.
