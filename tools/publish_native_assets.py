"""Publish CI packages only when their sources match an existing release tag."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import tomllib
from xml.etree import ElementTree
from zipfile import ZipFile


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True, encoding="utf-8")


def digest(path):
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--build-commit", required=True)
    cli.add_argument("--directory", type=Path, required=True)
    cli.add_argument("--dry-run", action="store_true")
    args = cli.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.build_commit):
        cli.error("Expected a full build commit")
    manifest = subprocess.check_output(["git", "show", args.build_commit + ":pyproject.toml"])
    version = tomllib.loads(manifest.decode("utf-8"))["project"]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        cli.error("Expected a release version")
    tag = "v" + version
    release = subprocess.run(["gh", "release", "view", tag, "--json", "assets,isDraft"],
                             capture_output=True, text=True, encoding="utf-8")
    if release.returncode:
        raise SystemExit(f"Release {tag} is unavailable; nothing was published: {release.stderr}")
    state = json.loads(release.stdout)
    if state["isDraft"]:
        raise SystemExit("Draft releases require manual publication")
    # Workflow-only and test-only fixes can differ; shipped code and notices cannot.
    subprocess.run(["git", "diff", "--exit-code", tag, args.build_commit, "--",
                    "src", "vendor", "tools/build_nuitka.py", "vscode/src", "vscode/media",
                    "vscode/scripts", "vscode/build.mjs", "vscode/package.json", "vscode/package-lock.json",
                    "vscode/README.md", "README.md", "README.ru.md", "CHANGELOG.md", "CHANGELOG.ru.md", "LICENSE"], check=True)
    existing = {asset["name"]: asset for asset in state["assets"]}
    packages = sorted(args.directory.rglob(f"bgin-editor-{version}-*.vsix"))
    if not packages:
        raise SystemExit("No successful native packages to publish")
    ready = []
    for package in packages:
        target = package.stem.removeprefix(f"bgin-editor-{version}-")
        if not re.fullmatch(r"(?:win32|linux|alpine|darwin)-(?:x64|arm64|armhf)", target):
            raise ValueError("Unexpected target: " + target)
        with ZipFile(package) as archive:
            if archive.testzip():
                raise ValueError("Damaged VSIX")
            identity = ElementTree.fromstring(archive.read("extension.vsixmanifest")).find(".//{*}Identity")
            assert identity is not None and identity.get("TargetPlatform") == target
            assert json.loads(archive.read("extension/package.json"))["version"] == version
            assert json.loads(archive.read("extension/backend/target.json"))["target"] == target
            assert not any(name.endswith((".py", ".pyc", ".bgin", ".obb", ".apk", ".jpk")) for name in archive.namelist())
        bundle = package.with_suffix(".zip")
        with ZipFile(bundle) as archive:
            if archive.testzip():
                raise ValueError("Damaged release bundle")
            checks = [name for name in archive.namelist() if name.endswith("/SHA256SUMS.txt")]
            assert len(checks) == 1
            prefix = checks[0].rsplit("/", 1)[0] + "/"
            assert "sha256:" + hashlib.sha256(archive.read(prefix + package.name)).hexdigest() == digest(package)
            for line in archive.read(checks[0]).decode("utf-8").splitlines():
                expected, name = line.split("  ", 1)
                assert hashlib.sha256(archive.read(prefix + name)).hexdigest() == expected
        ready.extend([package, bundle])
    for path in ready:
        if path.name in existing:
            if existing[path.name].get("digest") != digest(path):
                raise ValueError("Refusing to replace a published package: " + path.name)
        elif args.dry_run:
            print("Would publish " + path.name)
        else:
            gh("release", "upload", tag, str(path))
    if not args.dry_run:
        assets = json.loads(gh("release", "view", tag, "--json", "assets"))["assets"]
        lines = []
        for asset in sorted(assets, key=lambda item: item["name"]):
            if asset["name"].endswith((".vsix", ".zip")):
                value = asset.get("digest", "")
                if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
                    raise ValueError("GitHub did not return an asset digest")
                lines.append(value.removeprefix("sha256:") + "  " + asset["name"] + "\n")
        with tempfile.TemporaryDirectory() as directory:
            sums = Path(directory) / "SHA256SUMS.txt"
            sums.write_text("".join(lines), encoding="utf-8")
            gh("release", "upload", tag, str(sums), "--clobber")
    print(f"{tag}: {len(ready)} verified package files; published packages remain immutable")


if __name__ == "__main__":
    main()
