"""Read either BGIN namespace header without decoding the document tree."""
import struct

from ._wire import MAGIC, LEGACY_MARKER


def read_namespace(stream):
    header = stream.read(10)
    if len(header) != 10 or struct.unpack_from("<I", header)[0] != MAGIC:
        raise ValueError("Invalid BGIN header (invalid or truncated)")
    if header[4:10] == LEGACY_MARKER[:6]:
        if header[4:10] + stream.read(4) != LEGACY_MARKER:
            raise ValueError("Invalid or truncated legacy BGIN marker")
        length = stream.read(2)
        if len(length) != 2:
            raise ValueError("Truncated legacy BGIN namespace length")
        length = struct.unpack("<H", length)[0]
    else:
        length = struct.unpack_from("<H", header, 8)[0]
    raw = stream.read(length)
    if len(raw) != length:
        raise ValueError("Truncated BGIN namespace")
    try:
        name = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("Invalid UTF-8 in BGIN namespace") from error
    if not name or any(c.isspace() or c in "/\\" or ord(c) < 32 for c in name):
        raise ValueError("Invalid BGIN namespace")
    return name
