# Binary GIN Editor

Edit game interface files (`.bgin`) in VS Code: select objects in a tree,
change properties, and preview the result. Open BGIN directly; exporting a
separate JSON file is optional.

Creator: **mindkeyboard**. Distributed under the included terms of use.

[Full guide](https://octane-loader.utmsoft.ru/en/guide/octane-devtools/bgin-editor/v0.5.0/)
· [Русский](https://octane-loader.utmsoft.ru/ru/guide/octane-devtools/bgin-editor/v0.5.0/)

## Choose the package

| Environment | File suffix |
| --- | --- |
| Windows x64 / ARM64 | `win32-x64` / `win32-arm64` |
| macOS Intel / Apple Silicon | `darwin-x64` / `darwin-arm64` |
| Linux with glibc, x64 / ARM64 / ARMv7 hard float | `linux-x64` / `linux-arm64` / `linux-armhf` |
| Alpine Linux with musl, x64 / ARM64 | `alpine-x64` / `alpine-arm64` |

With WSL, SSH, or Dev Containers, choose the OS and architecture of the remote
workspace. Linux packages target glibc 2.36 and later, and Alpine packages target
Alpine 3.23 and later. The editor requires VS Code with a native extension host.

## First-time setup

1. If you received a ZIP, extract it into a normal folder.
2. Install [VS Code](https://code.visualstudio.com/download) 1.105 or later.
   Open **Extensions**, click **… → Install from VSIX…**, and select the
   supplied `bgin-editor-….vsix`. Reload if asked.
3. If your archive includes `Preview.code-workspace`, open it via **File → Open
   Workspace from File…** to use the supplied preview resources. Keep it next to
   the `resources` folder. Confirm folder trust if you trust the package.
4. Open a `.bgin` file. If it appears as text, right-click its tab →
   **Reopen Editor With… → Binary GIN**. Read and accept the terms on first opening.
5. Choose a **Screen** and click **Refresh** to preview it. Select an object
   to change properties, then use **Refresh** to see changes and **Ctrl+S** (**⌘S** on macOS) to save.

The VSIX includes the BGIN worker and its preview libraries. Python installation,
`PATH` changes, and first-run downloads are unnecessary.

## If it does not open

- Opens as text: use **Reopen Editor With… → Binary GIN** on the file's tab.
- Still failing: choose **View → Output**, select **Binary GIN** in the log
  dropdown rather than **Window**, and copy the error text.
- Tree opens but images are missing: open `Preview.code-workspace`, or set
  your folders through **Resources**, then click **Refresh**.

[Step-by-step troubleshooting](https://octane-loader.utmsoft.ru/en/guide/octane-devtools/bgin-editor/v0.5.0/troubleshooting).
Interface language is in **Editor settings → Interface language**.

Keep copies of original files before replacing them in a game. The preview
can differ from the game and does not run game actions. Closing the first
terms dialog does not accept it. After its first close or acceptance, the
[Octane Telegram channel](https://t.me/octaneloader) opens once.

Read LICENSE and THIRD_PARTY_NOTICES.txt for the terms and third-party notices.
The full user documentation is maintained on the website linked above.
