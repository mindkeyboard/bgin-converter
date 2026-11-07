from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class BginError(ValueError):
    pass


class BginDialect(str, Enum):
    AUTO = "auto"
    UI = "ui"
    TEMPLATES = "templates"
    SPRITES = "sprites"


@dataclass(frozen=True)
class SourceSpan:
    offset: int
    length: int

    @property
    def end(self) -> int:
        return self.offset + self.length


@dataclass(frozen=True)
class EnumToken:
    code: int
    name_hash: int
    name: str


@dataclass
class BginProperty:
    name_hash: int
    kind: int
    count: int | None
    value: Any
    encoding: str
    span: SourceSpan
    source_bytes: bytes
    dirty: bool = False
    literal_name: str | None = None

    def set_value(self, value: Any) -> None:
        self.value = value
        self.dirty = True


@dataclass
class SpriteKeyframe:
    frame_index: int
    flags: int
    span: SourceSpan
    source_bytes: bytes
    position_interpolation: int | None = None
    position: tuple[float, float] | None = None
    rotation_interpolation: int | None = None
    rotation: float | None = None
    scale_interpolation: int | None = None
    scale: tuple[float, float] | None = None
    string_pair: tuple[str, str] | None = None
    event: tuple[str, int, int, int] | None = None
    color_properties: list[BginProperty] = field(default_factory=list)
    dirty: bool = False

    def is_dirty(self) -> bool:
        return self.dirty or any(prop.dirty for prop in self.color_properties)


@dataclass
class BginNode:
    type_hash: int
    name: str
    span: SourceSpan
    source_bytes: bytes
    metadata: bytes = b""
    properties: list[BginProperty] = field(default_factory=list)
    children: list["BginNode"] = field(default_factory=list)
    decoded: bool = True
    opaque_reason: str = ""
    sprite_movie: "SpriteMoviePayload | None" = None
    dirty: bool = False
    literal_type: str | None = None

    def is_dirty(self) -> bool:
        return (
            self.dirty
            or any(prop.dirty for prop in self.properties)
            or any(child.is_dirty() for child in self.children)
            or (self.sprite_movie is not None and self.sprite_movie.is_dirty())
        )

    def require_decoded(self) -> None:
        if not self.decoded:
            raise BginError(
                f"Node {self.name!r} is opaque: {self.opaque_reason or 'unknown wire shape'}"
            )

    def walk(
        self, path: tuple[int, ...] = ()
    ) -> Iterable[tuple[tuple[int, ...], "BginNode"]]:
        yield path, self
        for index, child in enumerate(self.children):
            yield from child.walk(path + (index,))

    def find(self, path: Iterable[int]) -> "BginNode":
        node = self
        for index in path:
            node = node.children[index]
        return node

    def property_by_hash(self, name_hash: int) -> BginProperty | None:
        return next((prop for prop in self.properties if prop.name_hash == name_hash), None)

    def structural_nodes(self) -> Iterable["BginNode"]:
        yield self
        for child in self.children:
            yield from child.structural_nodes()
        if self.sprite_movie is not None:
            for sprite_movie in self.sprite_movie.sprite_movies:
                yield from sprite_movie.structural_nodes()
            for track in self.sprite_movie.tracks:
                yield from track.node.structural_nodes()


@dataclass
class SpriteMovieTrack:
    marker: int
    node: BginNode
    keyframes: list[SpriteKeyframe]
    terminator: int
    span: SourceSpan
    source_bytes: bytes
    dirty: bool = False

    def is_dirty(self) -> bool:
        return (
            self.dirty
            or self.node.is_dirty()
            or any(keyframe.is_dirty() for keyframe in self.keyframes)
        )


@dataclass
class SpriteMoviePayload:
    sprite_movies: list[BginNode]
    header_a: int
    header_b: int
    header_c: int
    header_flags: int
    tracks: list[SpriteMovieTrack]
    span: SourceSpan
    source_bytes: bytes
    dirty: bool = False

    def is_dirty(self) -> bool:
        return (
            self.dirty
            or any(node.is_dirty() for node in self.sprite_movies)
            or any(track.is_dirty() for track in self.tracks)
        )


@dataclass
class BginScreen:
    name_hash: int
    original_offset: int
    node: BginNode


@dataclass
class BginDocument:
    magic: int
    file_hash: int
    name: str
    dialect: BginDialect
    screens: list[BginScreen]
    directory_count: int
    directory_trailing_bytes: bytes
    source_bytes: bytes
    dirty: bool = False
    wire_format: str = "hashed"

    def is_dirty(self) -> bool:
        return self.dirty or any(screen.node.is_dirty() for screen in self.screens)

    def walk(self) -> Iterable[tuple[int, tuple[int, ...], BginNode]]:
        for screen_index, screen in enumerate(self.screens):
            for path, node in screen.node.walk():
                yield screen_index, path, node

    def stats(self) -> dict[str, int]:
        nodes = 0
        decoded_nodes = 0
        opaque_nodes = 0
        properties = 0
        sprite_tracks = 0
        sprite_keyframes = 0
        for screen in self.screens:
            for node in screen.node.structural_nodes():
                nodes += 1
                if node.decoded:
                    decoded_nodes += 1
                    properties += len(node.properties)
                else:
                    opaque_nodes += 1
                if node.sprite_movie is not None:
                    sprite_tracks += len(node.sprite_movie.tracks)
                    for track in node.sprite_movie.tracks:
                        sprite_keyframes += len(track.keyframes)
                        for keyframe in track.keyframes:
                            properties += len(keyframe.color_properties)
        return {
            "nodes": nodes,
            "decoded_nodes": decoded_nodes,
            "opaque_nodes": opaque_nodes,
            "properties": properties,
            "sprite_tracks": sprite_tracks,
            "sprite_keyframes": sprite_keyframes,
        }
