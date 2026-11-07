from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .codec import decode_document, encode_document
from .model import BginDialect, BginDocument, BginError, BginNode


@dataclass(frozen=True)
class BginAddress:
    screen: int
    path: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if type(self.screen) is not int or self.screen < 0:
            raise BginError("BGIN screen index must be a nonnegative integer")
        try:
            normalized = tuple(self.path)
        except TypeError as error:
            raise BginError("BGIN child path must be an iterable of indexes") from error
        if any(type(index) is not int or index < 0 for index in normalized):
            raise BginError("BGIN child path indexes must be nonnegative integers")
        object.__setattr__(self, "path", normalized)


@dataclass(frozen=True)
class BginRevision:
    label: str
    before: bytes
    after: bytes


class BginSession:
    """Validated byte-exact editing history for one BGIN document."""

    def __init__(
        self,
        source: bytes,
        dialect: BginDialect | str = BginDialect.AUTO,
    ) -> None:
        self._dialect = BginDialect(dialect)
        self._bytes = bytes(source)
        self._document = decode_document(self._bytes, self._dialect)
        self._dialect = self._document.dialect
        self._undo: list[BginRevision] = []
        self._redo: list[BginRevision] = []

    @property
    def document(self) -> BginDocument:
        return self._document

    @property
    def data(self) -> bytes:
        return self._bytes

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_labels(self) -> tuple[str, ...]:
        return tuple(revision.label for revision in self._undo)

    @property
    def redo_labels(self) -> tuple[str, ...]:
        return tuple(revision.label for revision in self._redo)

    @staticmethod
    def _checked_index(value: int, field: str) -> int:
        if type(value) is not int or value < 0:
            raise BginError(f"{field} must be a nonnegative integer")
        return value

    def snapshot(self) -> BginDocument:
        return decode_document(self._bytes, self._dialect)

    def _resolve(self, document: BginDocument, address: BginAddress) -> BginNode:
        try:
            return document.screens[address.screen].node.find(address.path)
        except (IndexError, KeyError) as error:
            raise BginError(f"Invalid BGIN address: {address}") from error

    def _resolve_parent(
        self,
        document: BginDocument,
        address: BginAddress,
    ) -> tuple[BginNode, int]:
        if not address.path:
            raise BginError("A screen root cannot be removed or moved as a node")
        parent = self._resolve(
            document,
            BginAddress(address.screen, address.path[:-1]),
        )
        parent.require_decoded()
        index = address.path[-1]
        if not 0 <= index < len(parent.children):
            raise BginError(f"Invalid child index in BGIN address: {address}")
        return parent, index

    @staticmethod
    def _contains(root: BginNode, candidate: BginNode) -> bool:
        if root is candidate:
            return True
        return any(BginSession._contains(child, candidate) for child in root.children)

    def _commit(
        self,
        label: str,
        mutate: Callable[[BginDocument], None],
    ) -> bool:
        candidate = decode_document(self._bytes, self._dialect)
        mutate(candidate)
        rebuilt = encode_document(candidate)
        if rebuilt == self._bytes:
            return False

        validated = decode_document(rebuilt, self._dialect)
        if encode_document(validated, force=True) != rebuilt:
            raise BginError("BGIN validation did not reproduce the candidate bytes")

        revision = BginRevision(label=label, before=self._bytes, after=rebuilt)
        self._bytes = rebuilt
        self._document = validated
        self._undo.append(revision)
        self._redo.clear()
        return True

    def set_property(
        self,
        address: BginAddress,
        property_hash: int,
        value: Any,
    ) -> bool:
        def mutate(document: BginDocument) -> None:
            node = self._resolve(document, address)
            node.require_decoded()
            prop = node.property_by_hash(property_hash)
            if prop is None:
                raise BginError(
                    f"Property 0x{property_hash:08x} is absent on node {node.name!r}"
                )
            prop.set_value(value)

        return self._commit(
            f"set property 0x{property_hash:08x} at {address}",
            mutate,
        )

    def rename_node(self, address: BginAddress, name: str) -> bool:
        def mutate(document: BginDocument) -> None:
            node = self._resolve(document, address)
            node.require_decoded()
            node.name = name
            node.dirty = True

        return self._commit(f"rename node at {address}", mutate)

    def delete_node(self, address: BginAddress) -> bool:
        def mutate(document: BginDocument) -> None:
            parent, index = self._resolve_parent(document, address)
            parent.children.pop(index)
            parent.dirty = True

        return self._commit(f"delete node at {address}", mutate)

    def clone_node(
        self,
        source: BginAddress,
        destination_parent: BginAddress,
        index: int | None = None,
        name: str | None = None,
    ) -> bool:
        return self.create_node_from_template(
            source,
            destination_parent,
            index=index,
            name=name,
            include_children=True,
            _label=f"clone node from {source}",
        )

    def create_node_from_template(
        self,
        template: BginAddress,
        destination_parent: BginAddress,
        index: int | None = None,
        name: str | None = None,
        include_children: bool = True,
        _label: str | None = None,
    ) -> bool:
        if index is not None:
            index = self._checked_index(index, "node insertion index")
        if type(include_children) is not bool:
            raise BginError("include_children must be boolean")

        def mutate(document: BginDocument) -> None:
            source_node = self._resolve(document, template)
            destination = self._resolve(document, destination_parent)
            destination.require_decoded()

            # Decode the record by itself through deepcopy-free source reuse:
            # unchanged node bytes are immutable and safe to duplicate.
            import copy

            clone = copy.deepcopy(source_node)
            clone.require_decoded()
            if not include_children:
                clone.children.clear()
                clone.dirty = True
            if name is not None:
                clone.name = name
                clone.dirty = True
            insert_at = len(destination.children) if index is None else index
            if not 0 <= insert_at <= len(destination.children):
                raise BginError(f"Invalid insertion index: {insert_at}")
            destination.children.insert(insert_at, clone)
            destination.dirty = True

        return self._commit(
            _label or f"create node from template {template}",
            mutate,
        )

    def create_node_from_external_template(
        self,
        template_node: BginNode,
        destination_parent: BginAddress,
        index: int | None = None,
        name: str | None = None,
        include_children: bool = False,
    ) -> bool:
        """Insert a validated decoded prototype taken from another BGIN."""
        if index is not None:
            index = self._checked_index(index, "node insertion index")
        if type(include_children) is not bool:
            raise BginError("include_children must be boolean")
        template_node.require_decoded()

        def mutate(document: BginDocument) -> None:
            import copy

            destination = self._resolve(document, destination_parent)
            destination.require_decoded()
            clone = copy.deepcopy(template_node)
            clone.require_decoded()
            if not include_children:
                clone.children.clear()
                clone.dirty = True
            if name is not None:
                clone.name = name
                clone.dirty = True
            insert_at = len(destination.children) if index is None else index
            if not 0 <= insert_at <= len(destination.children):
                raise BginError(f"Invalid insertion index: {insert_at}")
            destination.children.insert(insert_at, clone)
            destination.dirty = True

        return self._commit(
            f"create node from external {template_node.name!r} template",
            mutate,
        )

    def move_node(
        self,
        source: BginAddress,
        destination_parent: BginAddress,
        index: int | None = None,
    ) -> bool:
        if index is not None:
            index = self._checked_index(index, "node insertion index")

        def mutate(document: BginDocument) -> None:
            source_parent, source_index = self._resolve_parent(document, source)
            source_node = source_parent.children[source_index]
            destination = self._resolve(document, destination_parent)
            destination.require_decoded()
            if self._contains(source_node, destination):
                raise BginError("A node cannot be moved into its own subtree")

            source_parent.children.pop(source_index)
            insert_at = len(destination.children) if index is None else index
            if destination is source_parent and source_index < insert_at:
                insert_at -= 1
            if not 0 <= insert_at <= len(destination.children):
                raise BginError(f"Invalid insertion index: {insert_at}")
            destination.children.insert(insert_at, source_node)
            source_parent.dirty = True
            destination.dirty = True

        return self._commit(f"move node from {source}", mutate)

    def clone_screen(
        self,
        source_index: int,
        index: int | None = None,
        root_name: str | None = None,
        name_hash: int | None = None,
    ) -> bool:
        return self.create_screen_from_template(
            source_index,
            index=index,
            root_name=root_name,
            name_hash=name_hash,
            _label=f"clone screen {source_index}",
        )

    def create_screen_from_template(
        self,
        template_index: int,
        index: int | None = None,
        root_name: str | None = None,
        name_hash: int | None = None,
        _label: str | None = None,
    ) -> bool:
        template_index = self._checked_index(template_index, "template screen index")
        if index is not None:
            index = self._checked_index(index, "screen insertion index")
        if name_hash is not None and (
            type(name_hash) is not int or not 0 <= name_hash <= 0xFFFFFFFF
        ):
            raise BginError("screen name_hash must be a 32-bit integer")

        def mutate(document: BginDocument) -> None:
            import copy

            try:
                clone = copy.deepcopy(document.screens[template_index])
            except IndexError as error:
                raise BginError(f"Invalid template screen index: {template_index}") from error
            if root_name is not None:
                clone.node.require_decoded()
                clone.node.name = root_name
                clone.node.dirty = True
            if name_hash is not None:
                clone.name_hash = name_hash
            insert_at = len(document.screens) if index is None else index
            if not 0 <= insert_at <= len(document.screens):
                raise BginError(f"Invalid screen insertion index: {insert_at}")
            document.screens.insert(insert_at, clone)
            document.dirty = True

        return self._commit(
            _label or f"create screen from template {template_index}",
            mutate,
        )

    def delete_screen(self, index: int) -> bool:
        index = self._checked_index(index, "screen index")

        def mutate(document: BginDocument) -> None:
            if len(document.screens) == 1:
                raise BginError("A BGIN document must keep at least one screen")
            try:
                document.screens.pop(index)
            except IndexError as error:
                raise BginError(f"Invalid screen index: {index}") from error
            document.dirty = True

        return self._commit(f"delete screen {index}", mutate)

    def move_screen(self, source_index: int, index: int) -> bool:
        source_index = self._checked_index(source_index, "source screen index")
        index = self._checked_index(index, "screen insertion index")

        def mutate(document: BginDocument) -> None:
            try:
                screen = document.screens.pop(source_index)
            except IndexError as error:
                raise BginError(f"Invalid source screen index: {source_index}") from error
            insert_at = index
            if source_index < insert_at:
                insert_at -= 1
            if not 0 <= insert_at <= len(document.screens):
                raise BginError(f"Invalid screen insertion index: {insert_at}")
            document.screens.insert(insert_at, screen)
            document.dirty = True

        return self._commit(f"move screen {source_index}", mutate)

    def undo(self) -> bool:
        if not self._undo:
            return False
        revision = self._undo.pop()
        self._bytes = revision.before
        self._document = decode_document(self._bytes, self._dialect)
        self._redo.append(revision)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        revision = self._redo.pop()
        self._bytes = revision.after
        self._document = decode_document(self._bytes, self._dialect)
        self._undo.append(revision)
        return True
