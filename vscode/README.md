# Binary GIN Editor

Open, edit, and preview game interface files (`.bgin`) in VS Code.

## Quick install

In VS Code 1.105 or later, open **Extensions → … → Install from VSIX…**
and select the package for your platform. The package includes the BGIN worker,
so a separate Python installation is unnecessary.

[Download](https://github.com/mindkeyboard/bgin-converter/releases/latest) ·
[Installation and user guide](https://octane-loader.utmsoft.ru/en/guide/octane-devtools/bgin-editor/v0.6.3/) ·
[Русский](https://octane-loader.utmsoft.ru/ru/guide/octane-devtools/bgin-editor/v0.6.3/)

Created by **mindkeyboard**.

## Version 0.6.3

This build adds four explicit BGIN profiles, connected MCP sessions with live
VS Code edits, partial unpacked zdata resources and separate texture conversion.
Saving keeps the source profile. Some special records remain unsupported;
newer layout variants are preserved but are not reproduced by the preview.
The stdio MCP adapter is bundled. Use Copy MCP configuration in the sidebar; no Python or pip setup is required. Rendering requires an installed Chrome or Edge.
Game loading of converted resources has not been tested.

Open-screen inspection adds spread branches, depth, X-ray and top-layer cutoff
on cached paint. The screen picker supports search, derived prefix groups and recursive object counts.
