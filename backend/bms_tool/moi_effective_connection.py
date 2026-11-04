"""Append one matched existing-member edge after a retained native saved merge."""

from .moi_connection_copies import MoiConnectionCopies
from .moi_effective_wire import EffectiveWireCompiler
from .moi_effective_wire import compiler_from_snapshot as qualified_saved_merge
from .moi_identity import seal, sha

PROFILE = "native-effective-connection-compiler/1"
SCOPE = (
    "Local compilation of one prototype-matched connection between existing native members "
    "after merging an identity-qualified retained File 3/11/12 snapshot. Preserve original "
    "graph identity, membership, order, layout and continuation across the merge; then retain "
    "all other merged expanded bytes under the matching-connection copy profile. Captured "
    "effective values are not current live readings. No fresh-setting guarantee, new blocks/I/O, "
    "field transfer, general compiler/resource/package/runtime or CCT/physical acceptance."
)


class EffectiveConnectionCompiler:
    def __init__(self, files, *, _merge=None):
        # Reuse the existing saved-merge identity, object, membership, wire, order
        # and layout guards without widening that compiler's edit/transfer scope.
        merged = _merge if _merge is not None else EffectiveWireCompiler(files)
        before, after = merged.archive.reader, merged.effective.reader
        for ref, record in before.records.items():
            if record["class_id"] in (536, 575) and record["properties"].get(3384, {}).get(
                "encoded_sha256"
            ) != after.records[ref]["properties"].get(3384, {}).get("encoded_sha256"):
                raise ValueError("Saved values changed native connection continuation metadata.")
        self.archive = MoiConnectionCopies(files[3])
        self.effective = MoiConnectionCopies(merged.merged)
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
            "connection_edit": edit,
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
    return EffectiveConnectionCompiler(files, _merge=qualified_saved_merge(snapshot, files))
