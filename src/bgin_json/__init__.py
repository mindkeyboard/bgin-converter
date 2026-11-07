"""Read Binary GIN without loading the game or importing workspace tools."""

from .parser import BginError, Limits, load, parse
from .writer import encode
from .export import convert_file, dumps, load_json

__all__ = ["BginError", "Limits", "parse", "load", "encode", "dumps", "load_json", "convert_file"]
__version__ = "0.4.0"
