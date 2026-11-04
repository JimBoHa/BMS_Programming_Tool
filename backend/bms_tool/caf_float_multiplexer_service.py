"""Select a separately admitted Multiplexer schema from actual source configuration."""

from .caf import CafArchive
from .caf_boolean_enum_selector_multiplexer_copy import CafBooleanEnumSelectorMultiplexerCopies
from .caf_boolean_multiplexer_copy import CafBooleanMultiplexerCopies
from .caf_enum_enum_selector_multiplexer_copy import CafEnumEnumSelectorMultiplexerCopies
from .caf_enum_multiplexer_copy import CafEnumMultiplexerCopies
from .caf_enum_selector_multiplexer_copy import CafEnumSelectorMultiplexerCopies
from .caf_float_multiplexer_copy import CafFloatMultiplexerCopies
from .caf_graph import _properties


class CafFloatMultiplexerService:
    def __init__(self, archive):
        self.archive = archive if isinstance(archive, CafArchive) else CafArchive(archive)

    def _engine(self, prototype_ref):
        obj = self.archive.objects.get(prototype_ref)
        props = _properties(obj) if obj is not None else {}
        standard = self.archive.scalar(props.get("3670"))
        if standard == {"type": "enum", "text": "18", "attributes": {"set": "432"}}:
            return CafBooleanMultiplexerCopies(self.archive)
        if standard == {"type": "enum", "text": "19", "attributes": {"set": "432"}}:
            return CafBooleanEnumSelectorMultiplexerCopies(self.archive)
        if self.archive.scalar(props.get("3670")) == {
            "type": "enum",
            "text": "17",
            "attributes": {"set": "432"},
        }:
            return CafEnumEnumSelectorMultiplexerCopies(self.archive)
        if self.archive.scalar(props.get("3670")) == {
            "type": "enum",
            "text": "16",
            "attributes": {"set": "432"},
        }:
            return CafEnumMultiplexerCopies(self.archive)
        enum = self.archive.scalar(props.get("3670")) == {
            "type": "enum",
            "text": "15",
            "attributes": {"set": "432"},
        }
        return (CafEnumSelectorMultiplexerCopies if enum else CafFloatMultiplexerCopies)(
            self.archive
        )

    def inspect(self, diagram_ref, prototype_ref):
        return self._engine(prototype_ref).inspect(diagram_ref, prototype_ref)

    def compile(self, *, diagram_ref, prototype_ref, selection_sha256, x, y):
        return self._engine(prototype_ref).compile(
            diagram_ref=diagram_ref,
            prototype_ref=prototype_ref,
            selection_sha256=selection_sha256,
            x=x,
            y=y,
        )
