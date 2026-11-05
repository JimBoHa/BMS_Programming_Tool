"""Remove one existing connection after an identity-qualified retained saved merge."""

from .moi_connection_removal import MoiConnectionRemoval
from .moi_effective_wire import EffectiveWireCompiler
from .moi_effective_wire import compiler_from_snapshot as qualified_saved_merge
from .moi_identity import seal, sha

PROFILE = "native-effective-connection-removal-compiler/1"
SCOPE = (
    "Local compilation removing one exact existing native connection after merging an "
    "identity-qualified retained File 3/11/12 snapshot. Preserve original graph members, "
    "identity, order, layout and continuation across the merge; retain every other merged "
    "expanded byte during removal. Captured saved values are not current measurements. "
    "No destination fallback/retention semantics, new blocks/I/O, field transfer, inverse "
    "recovery authority, general compiler/resource/package or CCT/physical acceptance."
)


class EffectiveConnectionRemovalCompiler:
    def __init__(self, files, *, _merge=None):
        merged = _merge if _merge is not None else EffectiveWireCompiler(files)
        before, after = merged.archive.reader, merged.effective.reader
        for ref, record in before.records.items():
            if record["class_id"] in (536, 575) and record["properties"].get(3384, {}).get(
                "encoded_sha256"
            ) != after.records[ref]["properties"].get(3384, {}).get("encoded_sha256"):
                raise ValueError("Saved values changed native connection continuation metadata.")
        self.archive = MoiConnectionRemoval(files[3])
        self.effective = MoiConnectionRemoval(merged.merged)
        self.parameters, self.files = merged.parameters, merged.files

    def compile(self, *, effective_sha256, effective_record_sha256, **proposal):
        output, edit = self.effective.compile(
            source_sha256=effective_sha256,
            record_sha256=effective_record_sha256,
            **proposal,
        )
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "files": self.files,
            "parameter_merge": self.parameters,
            "archive_sha256": self.archive.editor.source_sha256,
            "effective_sha256": self.effective.editor.source_sha256,
            "connection_removal": edit,
            "compiled_sha256": sha(output),
            "compiled_native_sha256": edit["output_native_sha256"],
            "native_record_count": len(self.effective.editor.records),
            "other_merged_bytes_preserved": True,
            "saved_settings_merged": True,
            "controller_write": False,
            "field_transfer_enabled": False,
        }
        return output, {**body, "compilation_sha256": seal(body)}


def compiler_from_snapshot(snapshot, files):
    return EffectiveConnectionRemovalCompiler(files, _merge=qualified_saved_merge(snapshot, files))
