"""Select a separately admitted comparison schema from actual source configuration."""

from .caf import CafArchive
from .caf_comparison_copy import CafComparisonCopies
from .caf_enum_comparison_copy import CafEnumComparisonCopies
from .caf_graph import _properties


class CafComparisonService:
    def __init__(self, archive):
        self.archive = archive if isinstance(archive, CafArchive) else CafArchive(archive)

    def _engine(self, prototype_ref):
        obj = self.archive.objects.get(prototype_ref)
        props = _properties(obj) if obj is not None else {}
        enum = self.archive.scalar(props.get("518")) == {
            "type": "enum",
            "text": "5",
            "attributes": {"set": "287"},
        } and self.archive.scalar(props.get("3670")) == {
            "type": "enum",
            "text": "34",
            "attributes": {"set": "432"},
        }
        return (CafEnumComparisonCopies if enum else CafComparisonCopies)(self.archive)

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
