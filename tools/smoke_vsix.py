"""Exercise the worker from a VSIX on its target platform."""

import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from build_nuitka import native_target, verify_executable


def main(package):
    target = native_target()
    fixture = Path(__file__).resolve().parents[1] / "examples/hierarchy.bgin"
    original = base64.b64encode(fixture.read_bytes()).decode("ascii")
    with ZipFile(package) as archive, tempfile.TemporaryDirectory() as temporary:
        identity = ElementTree.fromstring(archive.read("extension.vsixmanifest")).find(".//{*}Identity")
        if not target or identity is None or identity.get("TargetPlatform") != target:
            raise ValueError(f"VSIX cannot be tested in this build environment ({target})")
        backend = "extension/backend/"
        if json.loads(archive.read(backend + "target.json"))["target"] != target:
            raise ValueError("Worker and VSIX targets differ")
        for item in archive.infolist():
            if item.filename.startswith(backend) and not item.is_dir():
                file = Path(archive.extract(item, temporary))
                if os.name != "nt":
                    file.chmod((item.external_attr >> 16) & 0o777)
        name = "bgin_backend.exe" if os.name == "nt" else "bgin_backend"
        executable = Path(temporary) / backend / name
        verify_executable(executable, target)
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON") and key.upper() != "PATH"}
        env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32") if os.name == "nt" else ""

        def rpc(requests):
            response = subprocess.run(
                [str(executable)], cwd=temporary, env=env, check=True, timeout=60,
                input="".join(json.dumps(dict(id=i, method=m, params=p)) + "\n" for i, (m, p) in enumerate(requests)),
                encoding="utf-8", stdout=subprocess.PIPE,
            )
            replies = [json.loads(line) for line in response.stdout.splitlines()]
            if len(replies) != len(requests):
                raise ValueError(f"Unexpected RPC replies: {len(replies)}")
            for i, reply in enumerate(replies):
                if reply.get("id") != i or "error" in reply:
                    raise ValueError(reply)
            return [reply["result"] for reply in replies]

        ping, catalog, decoded = rpc([("ping", {}), ("catalog", {}), ("decode", {"data": original})])
        encoded, preview = rpc([("encode", decoded), ("render", decoded)])
        if not ping["ready"] or not catalog["defaults"] or encoded["data"] != original or not preview["svg"].startswith("<svg"):
            raise ValueError("Worker failed readiness, catalog, byte-exact round trip or preview")
        print(f"{target}: packaged worker passed without Python on PATH")


if __name__ == "__main__":
    main(sys.argv[1])
