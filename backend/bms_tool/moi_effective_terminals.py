"""Local terminal copies after an identity-qualified retained saved-setting merge."""

from .moi_effective_wire import compiler_from_snapshot as qualified_saved_merge
from .moi_identity import seal, sha
from .moi_terminal_copies import MoiTerminalCopies

PROFILE = "native-effective-local-terminal-copy/1"
SCOPE = (
    "Merge identity-qualified retained File 3/11/12 values, then move one existing local "
    "analog/binary input to a free universal terminal in a separate native file. Preserve "
    "all other merged bytes, graph, identities, modes and framing. Captured settings are "
    "not current live values. No SA/cross-host/dedicated-BI move, allocation, field transfer, "
    "physical wiring or CCT/physical acceptance."
)


class EffectiveTerminalCopies:
    def __init__(self, snapshot, files):
        merged = qualified_saved_merge(snapshot, files)
        for ref, record in merged.archive.reader.records.items():
            if record["class_id"] in {536, 575} and record["properties"].get(3384, {}).get(
                "encoded_sha256"
            ) != merged.effective.reader.records[ref]["properties"].get(3384, {}).get(
                "encoded_sha256"
            ):
                raise ValueError("Saved values changed native graph continuation metadata.")
        self.archive = MoiTerminalCopies(files[3])
        self.effective = MoiTerminalCopies(merged.merged)
        if self.archive.inputs.keys() != self.effective.inputs.keys():
            raise ValueError("Saved values changed the recorded local input inventory.")
        self.parameters, self.files = merged.parameters, merged.files

    def compile(self, *, effective_sha256, effective_record_sha256, **proposal):
        output, edit = self.effective.compile(
            source_sha256=effective_sha256, record_sha256=effective_record_sha256, **proposal
        )
        body = {
            "profile": PROFILE,
            "scope": SCOPE,
            "files": self.files,
            "parameter_merge": self.parameters,
            "archive_sha256": self.archive.editor.source_sha256,
            "effective_sha256": self.effective.editor.source_sha256,
            "terminal_edit": edit,
            "compiled_sha256": sha(output),
            "compiled_native_sha256": edit["output_native_sha256"],
            "native_record_count": len(self.effective.editor.records),
            "other_merged_bytes_preserved": True,
            "saved_settings_merged": True,
            "controller_write": False,
            "field_transfer_enabled": False,
        }
        return output, {**body, "compilation_sha256": seal(body)}
