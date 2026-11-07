"""Prepare a local distribution from an already built VSIX; never publish it."""

import argparse
import hashlib
import re
import json
from pathlib import Path
import tempfile
import zipfile
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]


def prepare(target, resource_root=None):
    manifest = json.loads((ROOT / "vscode/package.json").read_text(encoding="utf-8"))
    version = manifest["version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", version):
        raise ValueError("Unsafe release version")
    if not re.fullmatch(r"(?:win32|linux|alpine|darwin)-(?:x64|arm64|armhf)", target):
        raise ValueError("Invalid native VS Code target")
    name = f"bgin-editor-{version}-{target}"
    package = ROOT / "dist" / (name + ".vsix")
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        packed = json.loads(archive.read("extension/package.json"))
        if packed["version"] != version:
            raise ValueError("VSIX version differs from the current extension manifest")
        identity = ElementTree.fromstring(archive.read("extension.vsixmanifest")).find(".//{*}Identity")
        if identity is None or identity.get("TargetPlatform") != target:
            raise ValueError("VSIX target differs from the requested platform")
        if json.loads(archive.read("extension/backend/target.json"))["target"] != target:
            raise ValueError("VSIX worker target differs from the requested platform")
        backend = ROOT / "vscode/backend"
        expected_backend = {
            "extension/backend/" + path.relative_to(backend).as_posix(): path
            for path in backend.rglob("*") if path.is_file()
        }
        executable = "bgin_backend.exe" if target.startswith("win32-") else "bgin_backend"
        if f"extension/backend/{executable}" not in expected_backend or {
            entry for entry in names if entry.startswith("extension/backend/") and not entry.endswith("/")
        } != expected_backend.keys():
            raise ValueError("VSIX worker files differ from the current build")
        for entry, path in expected_backend.items():
            with archive.open(entry) as packed_file, path.open("rb") as built_file:
                if hashlib.file_digest(packed_file, "sha256").digest() != hashlib.file_digest(built_file, "sha256").digest():
                    raise ValueError(f"VSIX worker file differs from the current build: {entry}")
        allowed_files = {"extension/package.json", "extension/readme.md", "extension/changelog.md", "extension/LICENSE.txt", "extension/THIRD_PARTY_NOTICES.txt"}
        allowed_prefixes = ("extension/media/", "extension/out/", "extension/backend/", "extension/scripts/")
        for entry in names:
            if entry.endswith("/") or entry in ("[Content_Types].xml", "extension.vsixmanifest"):
                continue
            if entry not in allowed_files and not entry.startswith(allowed_prefixes):
                raise ValueError(f"Unexpected release file: {entry}")
            if entry.endswith((".map", ".bgin", ".py", ".pyc", ".vsix")) or any(part in ("tests", "test", "__pycache__", "node_modules") for part in Path(entry).parts):
                raise ValueError(f"Development or game data in VSIX: {entry}")
        if archive.read("extension/readme.md") != (ROOT / "vscode/README.md").read_bytes():
            raise ValueError("VSIX README is stale; rebuild the package")
        if archive.read("extension/LICENSE.txt") != (ROOT / "LICENSE").read_bytes():
            raise ValueError("VSIX terms differ from the release LICENSE; rebuild the package")
        if archive.read("extension/changelog.md") != (ROOT / "CHANGELOG.md").read_bytes():
            raise ValueError("VSIX changelog differs from the release; rebuild the package")
        for entry, source in {
            "extension/out/extension.js": "vscode/out/extension.js",
            "extension/media/app.js": "vscode/media/app.js",
            "extension/media/styles.css": "vscode/media/styles.css",
        }.items():
            if archive.read(entry) != (ROOT / source).read_bytes():
                raise ValueError(f"VSIX does not match current build: {entry}")

    files = {
        package.name: package,
        **{filename: ROOT / filename for filename in ("README.md", "README.ru.md", "CHANGELOG.md", "CHANGELOG.ru.md", "LICENSE")},
        "THIRD_PARTY_NOTICES.txt": ROOT / "vscode/THIRD_PARTY_NOTICES.txt",
    }
    resource_count = resource_bytes = 0
    if resource_root:
        resource_root = Path(resource_root).resolve(strict=True)
        for directory in ("gui", "textures_android", "texter_fonts"):
            source = resource_root / directory
            if not source.is_dir():
                raise ValueError(f"Required renderer directory is missing: {source}")
            for path in sorted(source.rglob("*")):
                if not path.is_file():
                    continue
                if not path.resolve().is_relative_to(resource_root):
                    raise ValueError(f"Resource leaves the selected root: {path}")
                files["resources/" + path.relative_to(resource_root).as_posix()] = path
                resource_count += 1
                resource_bytes += path.stat().st_size
        files["Preview.code-workspace"] = (json.dumps({
            "folders": [{"path": "."}],
            "settings": {"bgin.resourceFolders": {
                "assetRoot": "resources", "bginRoot": "resources/gui",
                "textureRoot": "resources/textures_android", "fontRoot": "resources/texter_fonts"
            }}
        }, indent=2) + "\n").encode()
        files["resources/README.md"] = (
            "# Preview resources\n\n"
            "This directory contains gui, textures_android and texter_fonts only. "
            "Open Preview.code-workspace from the release folder to use these relative paths. "
            "Resources are external to the extension and are not installed into VS Code.\n"
            f"\n[Preview resource guide](https://octane-loader.utmsoft.ru/en/guide/octane-devtools/bgin-editor/v{version}/resources)\n"
        ).encode()
        files["resources/README.ru.md"] = (
            "# Ресурсы предпросмотра\n\n"
            "Здесь только gui, textures_android и texter_fonts. Откройте Preview.code-workspace "
            "из папки выпуска: пути к ресурсам уже заданы относительно неё. "
            "Ресурсы остаются внешними файлами и не устанавливаются внутрь VS Code.\n"
            f"\n[Подключение ресурсов](https://octane-loader.utmsoft.ru/ru/guide/octane-devtools/bgin-editor/v{version}/resources)\n"
        ).encode()
        print(f"Renderer resources: {resource_count} files, {resource_bytes:,} bytes", flush=True)

    dist = (ROOT / "dist").resolve()
    folder = dist / name
    if not folder.resolve().is_relative_to(dist):
        raise ValueError("Release folder leaves dist")
    # Stage complete files before publishing the directory. Copy and hash in chunks
    # so a multi-gigabyte resource pack does not enter memory as one bytes object.
    with tempfile.TemporaryDirectory(dir=dist, prefix=f".{name}-") as staging:
        stage = Path(staging).resolve()
        if not stage.is_relative_to(dist):
            raise ValueError("Staging directory leaves dist")
        checksums = []
        for index, (filename, source) in enumerate(sorted(files.items())):
            target = stage / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with target.open("wb") as output:
                if isinstance(source, Path):
                    before = source.stat()
                    with source.open("rb") as stream:
                        while chunk := stream.read(1024 * 1024):
                            digest.update(chunk)
                            output.write(chunk)
                    after = source.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise ValueError(f"Source changed during packaging: {source}")
                else:
                    digest.update(source)
                    output.write(source)
            checksums.append(f"{digest.hexdigest()}  {filename}\n")
            if resource_root and index % 500 == 0:
                print(f"Staged {index + 1}/{len(files)} files", flush=True)
        (stage / "SHA256SUMS.txt").write_text("".join(checksums), encoding="utf-8")
        if folder.exists():
            expected = {p.relative_to(stage).as_posix(): p for p in stage.rglob("*") if p.is_file()}
            actual = {p.relative_to(folder).as_posix(): p for p in folder.rglob("*") if p.is_file()}
            if set(actual) != set(expected) or any(hashlib.file_digest(actual[n].open("rb"), "sha256").digest() != hashlib.file_digest(expected[n].open("rb"), "sha256").digest() for n in actual):
                raise ValueError("Existing release folder differs; choose a new version")
        else:
            # Both resolved paths are confined to this project's dist directory.
            stage.rename(folder)

    target = dist / (name + ".zip")
    if target.exists():
        raise ValueError("Release ZIP already exists; keep published artifacts immutable")
    with tempfile.NamedTemporaryFile(dir=dist, suffix=".zip", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
            for index, path in enumerate(sorted(folder.rglob("*"))):
                if path.is_file():
                    archive.write(path, f"{name}/{path.relative_to(folder).as_posix()}")
                    if resource_root and index % 500 == 0:
                        print(f"Archived {index} entries", flush=True)
        with zipfile.ZipFile(temporary) as archive:
            damaged = archive.testzip()
            if damaged:
                raise ValueError(f"ZIP verification failed: {damaged}")
        temporary.rename(target)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps({"version": version, "folder": str(folder), "zip": str(target),
                      "resourceFiles": resource_count, "resourceBytes": resource_bytes,
                      "published": False}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="VS Code target, for example win32-arm64")
    parser.add_argument("--resources", type=Path, help="Extracted resource root; only gui, textures_android and texter_fonts are copied")
    args = parser.parse_args()
    prepare(args.target, args.resources)
