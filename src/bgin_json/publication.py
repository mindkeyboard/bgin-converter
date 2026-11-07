"""Atomic file publication shared by the editor converter and MCP server."""

import os
from pathlib import Path
import tempfile
import uuid


def atomic_write(path, data, *, overwrite=False, expected=None):
    """Publish a complete file; retain the previous bytes before replacement."""
    path = Path(path)
    if not path.parent.is_dir():
        raise ValueError(f"Destination directory does not exist: {path.parent}")
    before = path.read_bytes() if path.exists() else None
    if before is not None and not overwrite:
        raise ValueError(f"Destination exists; choose another path or set overwrite: {path}")
    if expected is not None and before != expected:
        raise ValueError("Destination changed since it was read; reload before saving")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    backup = None
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if before is not None:
            backup = path.with_name(path.name + "." + uuid.uuid4().hex[:12] + ".bak")
            with backup.open("xb") as stream:
                stream.write(before)
                stream.flush()
                os.fsync(stream.fileno())
            if path.read_bytes() != before:
                raise ValueError("Destination changed while preparing the save; reload it")
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {"path": str(path), "bytes": len(data), "backup": str(backup) if backup else None}
