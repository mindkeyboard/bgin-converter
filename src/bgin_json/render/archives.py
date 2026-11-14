"""Read selected texture JPK/ZIP members lazily without unpacking a game dump."""

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile


class TextureArchives:
    def __init__(self):
        self.indexes = {}
        self.temporary = None
        self.extracted = {}
        self.bytes = 0
        self.latest = None
        self.candidates = {}

    def resolve(self, root, name):
        # PAD versions and GPU variants stay explicit. Duplicate names are errors,
        # rather than a choice of whichever archive happened to be listed first.
        candidates = self.candidates.get(root)
        if candidates is None:
            candidates = set(root.glob("*.jpk")) | set(root.glob("*.zip"))
            for pattern in ("textures_pack*/*/*/assets/data*/*.jpk", "*/*/assets/data*/*.jpk", "assets/data*/*.jpk"):
                candidates.update(root.glob(pattern))
            candidates = sorted(p for p in candidates if p.is_file() and p.resolve().is_relative_to(root))
            self.candidates[root] = candidates
        if len(candidates) > 256:
            raise ValueError("Too many texture archives; choose a smaller resource folder")
        found = []
        for archive in candidates:
            stat = archive.stat()
            stamp = (str(archive), stat.st_mtime_ns, stat.st_size)
            if stamp not in self.indexes:
                self.indexes = {key: value for key, value in self.indexes.items() if key[0] != str(archive)}
                try:
                    with ZipFile(archive) as zipped:
                        index = {}
                        for info in zipped.infolist():
                            if not info.is_dir():
                                key = Path(info.filename.replace("\\", "/")).name.casefold()
                                index.setdefault(key, []).append(info.filename)
                        self.indexes[stamp] = index
                except BadZipFile as error:
                    raise ValueError(f"Unsupported texture JPK container: {archive.name}") from error
            for member in self.indexes[stamp].get(name.casefold(), []):
                found.append((archive, stamp, member))
        if not found:
            raise FileNotFoundError(name)
        if len(found) != 1:
            raise ValueError(f"Ambiguous texture {name}: " + ", ".join(f"{p.name}:{member}" for p, _, member in found))
        archive, stamp, member = found[0]
        key = (*stamp, member)
        cached = self.extracted.get(key)
        if cached and cached.is_file():
            self.latest = cached
            return cached
        if self.temporary is None:
            self.temporary = TemporaryDirectory(prefix="bgin-textures-")
        with ZipFile(archive) as zipped:
            info = zipped.getinfo(member)
            if info.file_size > 128 * 1024 * 1024:
                raise ValueError(f"Texture archive member is too large: {name}")
            if self.bytes + info.file_size > 256 * 1024 * 1024:
                # Keep the most recent texture while its separate alpha member
                # is resolved. Resource decoding is sequential within a worker.
                for old_key, old in list(self.extracted.items()):
                    if old == self.latest:
                        continue
                    self.bytes -= old.stat().st_size
                    old.unlink(missing_ok=True)
                    del self.extracted[old_key]
            target = Path(self.temporary.name) / (sha256(repr(key).encode()).hexdigest() + Path(name).suffix)
            # Use a generated destination name, never an archive-controlled path.
            target.write_bytes(zipped.read(info))
            self.bytes += info.file_size
            self.extracted[key] = target
            self.latest = target
            return target
