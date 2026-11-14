"""Stable document profiles, separate from resource namespaces and preview policy."""
import re

FORMATS = ("a8-0.0.2", "a8-1.6.0", "a8-3.7.0", "a8-5.8.0")
ALIASES = {"legacy": FORMATS[0], "hashed": FORMATS[1],
           "0.0.2": FORMATS[0], "1.6.0": FORMATS[1],
           "3.7.0": FORMATS[2], "5.8.0": FORMATS[3]}
HASH_REFERENCE = re.compile(r"^#[0-9A-Fa-f]{8}$")


def normalize_format(value=None):
    """Accept earlier JSON aliases, but persist a canonical explicit profile."""
    if value is not None and not isinstance(value, str):
        raise ValueError("BGIN format must be a string")
    value = "a8-1.6.0" if value is None else ALIASES.get(value, value)
    if value not in FORMATS:
        raise ValueError("Unknown BGIN format; expected " + ", ".join(FORMATS))
    return value


def hash_reference(value):
    """A reserved symbolic spelling for an identifier whose name is unknown."""
    return int(value[1:], 16) if isinstance(value, str) and HASH_REFERENCE.fullmatch(value) else None


def identifier(value, vocabulary, hash_function):
    reference = hash_reference(value)
    if reference is not None:
        return reference
    return vocabulary[value] if value in vocabulary else hash_function(value)
