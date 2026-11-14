"""Build the standalone RPC worker shipped with the VS Code editor."""

import argparse
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import sysconfig
import zipfile
from pathlib import Path
from urllib.request import urlopen


def native_target():
    machine = platform.machine().lower()
    if sys.platform == "win32":
        return {"win-amd64": "win32-x64", "win-arm64": "win32-arm64"}.get(sysconfig.get_platform())
    if sys.platform == "darwin":
        return {"x86_64": "darwin-x64", "arm64": "darwin-arm64"}.get(machine)
    if sys.platform == "linux":
        try:
            glibc = os.confstr("CS_GNU_LIBC_VERSION")
        except (OSError, ValueError):
            glibc = None
        arch = {"x86_64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
        if glibc and sysconfig.get_config_var("MULTIARCH") == "arm-linux-gnueabihf":
            return "linux-armhf"
        if arch and sys.maxsize >= 2**32:
            return f"{'linux' if glibc else 'alpine'}-{arch}"
    return None


def verify_executable(executable, target):
    with executable.open("rb") as stream:
        header = stream.read(4096)
        os_name, arch = target.split("-", 1)
        matches = False
        if os_name == "win32" and header.startswith(b"MZ"):
            stream.seek(struct.unpack_from("<I", header, 60)[0])
            signature, machine = struct.unpack("<4sH", stream.read(6))
            matches = signature == b"PE\0\0" and machine == {"x64": 0x8664, "arm64": 0xAA64}[arch]
        elif os_name == "darwin" and header.startswith(b"\xcf\xfa\xed\xfe"):
            matches = struct.unpack_from("<I", header, 4)[0] == {"x64": 0x01000007, "arm64": 0x0100000C}[arch]
        elif os_name in ("alpine", "linux") and header.startswith(b"\x7fELF"):
            machine = struct.unpack_from("<H", header, 18)[0]
            matches = machine == {"x64": 62, "arm64": 183, "armhf": 40}[arch]
            loader = elf_loader(stream, header)
            matches = matches and loader.startswith(b"ld-musl-" if os_name == "alpine" else b"ld-linux")
        if not matches:
            raise ValueError(f"{executable} does not match native target {target}")


def elf_loader(stream, header):
    # patchelf can relocate PT_INTERP and its string beyond the first file page.
    elf64 = header[4] == 2
    offset_fmt = "<Q" if elf64 else "<I"
    phoff = struct.unpack_from(offset_fmt, header, 32 if elf64 else 28)[0]
    phsize, phnum = struct.unpack_from("<HH", header, 54 if elf64 else 42)
    for index in range(phnum):
        stream.seek(phoff + index * phsize)
        segment = stream.read(phsize)
        if struct.unpack_from("<I", segment)[0] == 3:  # PT_INTERP
            offset = struct.unpack_from(offset_fmt, segment, 8 if elf64 else 4)[0]
            stream.seek(offset)
            return stream.read(256).split(b"\0", 1)[0].rsplit(b"/", 1)[-1]
    return b""


def finish_distribution(binary, target, venv):
    if not binary.is_file():
        raise SystemExit(f"Compiled worker is missing: {binary}")
    verify_executable(binary, target)
    licenses = binary.parent / "licenses"
    licenses.mkdir(exist_ok=True)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        python_license = Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copyfile(python_license, licenses / "Python.txt")
    else:
        version = platform.python_version()
        with urlopen(f"https://raw.githubusercontent.com/python/cpython/v{version}/LICENSE", timeout=30) as license_file:
            (licenses / "Python.txt").write_bytes(license_file.read())
    for metadata in venv.glob("**/*.dist-info"):
        for license_file in metadata.rglob("*"):
            if license_file.is_file() and license_file.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")):
                relative = license_file.relative_to(metadata).as_posix().replace("/", "-")
                shutil.copyfile(license_file, licenses / f"{metadata.name}-{relative}.txt")
    shutil.copyfile(Path(__file__).resolve().parents[1] / "vendor/licenses/Zstandard.txt", licenses / "Zstandard.txt")
    (binary.parent / "target.json").write_text(json.dumps({"target": target}) + "\n", encoding="utf-8")


def main():
    root = Path(__file__).resolve().parents[1]
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, default=root / "build" / "nuitka")
    cli.add_argument("--jobs", type=int, default=2)
    cli.add_argument("--timeout", type=int, default=900)
    cli.add_argument("--nuitka-version", default="4.3.1")
    cli.add_argument("--target", help="Expected VS Code target for this build environment")
    args = cli.parse_args()
    target = native_target()
    if not target or (args.target and args.target != target):
        cli.error(f"Expected {args.target or 'a supported native target'}, found {target or platform.platform()}")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "bgin_backend.dist" / "target.json").unlink(missing_ok=True)
    venv = output / "venv"
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    dependencies = ["Nuitka==" + args.nuitka_version, "Pillow==13.0.0", "texture2ddecoder==1.0.6", "lz4==4.4.5", "mcp==1.30.0"]
    native_node = target.startswith("alpine-") or target == "linux-armhf"
    dependencies += ["pyee>=13,<15", "greenlet>=3.1.1,<4"] if native_node else ["playwright==1.64.1"]
    if target.startswith("alpine-"):
        # Nuitka rejects the patchelf 0.18.0 shipped with Alpine 3.23.
        dependencies.append("patchelf==0.17.2.4")
    subprocess.run(
        [str(python), "-m", "pip", "install", *dependencies],
        check=True,
    )
    if native_node:
        # Playwright's Python API is portable; its published Node driver is not
        # available for musl/ARMv7. Use the matching Node from the build image.
        wheels = output / "playwright-wheel"
        wheels.mkdir(exist_ok=True)
        subprocess.run([str(python), "-m", "pip", "download", "--no-deps", "--only-binary=:all:",
                        "--platform", "manylinux1_x86_64", "--platform", "manylinux_2_17_x86_64",
                        "--dest", str(wheels), "playwright==1.64.1"], check=True)
        site = Path(subprocess.check_output([str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True).strip())
        wheel = next(wheels.glob("playwright-1.64.1-*.whl"))
        with zipfile.ZipFile(wheel) as archive:
            for member in archive.infolist():
                name = member.filename
                if (name.startswith(("playwright/", "playwright-1.64.1.dist-info/"))
                        and ".." not in Path(name).parts):
                    archive.extract(member, site)
        node = shutil.which("node")
        if not node:
            raise SystemExit("The target build image must provide a native Node.js executable")
        shutil.copy2(node, site / "playwright" / "driver" / "node")
        node_version = subprocess.check_output([node, "--version"], text=True).strip()
        with urlopen(f"https://raw.githubusercontent.com/nodejs/node/{node_version}/LICENSE", timeout=30) as license_file:
            (site / "playwright" / "driver" / "LICENSE").write_bytes(license_file.read())
    # The published zstd wheels omit the v0.6 decoder used by game resources.
    # Compile its source distribution with legacy support on every target.
    legacy_env = dict(os.environ, ZSTD_LEGACY="1")
    subprocess.run(
        [str(python), "-m", "pip", "install", "--use-pep517", "--no-binary=zstd", "--no-cache-dir", "--force-reinstall", "zstd==1.5.7.2"],
        env=legacy_env, check=True,
    )
    subprocess.run(
        [str(python), "-c", "import zstd; assert zstd.ZSTD_legacy_support(), 'Zstd legacy decoder was not built'"],
        check=True,
    )
    # Keep the entry outside the package so Python relative imports retain their identity.
    entry = output / "bgin_backend.py"
    entry.write_text("from bgin_json.native import main\n\nmain()\n", encoding="utf-8")
    driver = Path(subprocess.check_output(
        [str(python), "-c", "from pathlib import Path; import playwright; print(Path(playwright.__file__).parent / 'driver')"], text=True
    ).strip())
    env = dict(
        os.environ,
        PATH=str(python.parent) + os.pathsep + os.environ["PATH"],
        PYTHONPATH=os.pathsep.join(map(str, (root / "src", root / "vendor"))),
        NUITKA_CACHE_DIR=str(output / "cache"),
    )
    command = [
        str(python),
        "-m",
        "nuitka",
        "--mode=standalone",
        "--lto=no",
        "--output-filename=bgin_backend",
        "--assume-yes-for-downloads",
        "--include-module=bgin_core",
        "--include-package-data=bgin_json:parameter_help.json",
        "--include-package-data=bgin_json.mcp_server",
        "--include-module=PIL.Image",
        "--include-module=PIL.ImageFont",
        "--include-module=texture2ddecoder",
        "--include-module=lz4.block",
        "--include-module=zstd",
        "--output-dir=" + str(output),
        "--report=" + str(output / "compilation-report.xml"),
        "--jobs=" + str(args.jobs),
        str(entry),
    ]
    if os.name == "nt":
        command[3:3] = ["--msvc=latest", "--windows-console-mode=force"]
    elif sys.platform == "darwin":
        command[3:3] = ["--macos-target-arch=" + platform.machine()]
    metadata = {
        "command": command,
        "python": subprocess.check_output(
            [str(python), "--version"], text=True
        ).strip(),
        "packages": json.loads(
            subprocess.check_output(
                [str(python), "-m", "pip", "list", "--format=json"], text=True
            )
        ),
    }
    (output / "build.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "Compiling RPC worker; log: " + str(output / "compilation.log"),
        flush=True,
    )
    with (output / "compilation.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT
        )
        try:
            status = process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False
                )
            else:
                process.kill()
            process.wait()
            raise SystemExit(
                "Compilation exceeded the configured timeout; inspect compilation.log"
            ) from None
    if status:
        raise SystemExit(
            "Compilation failed; inspect compilation.log (exit " + str(status) + ")"
        )
    binary = (
        output
        / "bgin_backend.dist"
        / ("bgin_backend.exe" if os.name == "nt" else "bgin_backend")
    )
    # Playwright's driver includes a native Node executable, not only data files.
    # Preserve the complete upstream driver and its notices after compilation.
    destination_driver = binary.parent / "playwright" / "driver"
    shutil.copytree(driver, destination_driver, dirs_exist_ok=True)
    finish_distribution(binary, target, venv)
    print(str(binary), flush=True)


if __name__ == "__main__":
    main()
