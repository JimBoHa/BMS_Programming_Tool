"""Compile one existing wire source after a retained native saved-value merge."""

from .moi_identity import MoiIdentity, sha
from .moi_parameters import ParameterApplication
from .moi_wire_sources import MoiWireSources

PROFILE = "native-effective-wire-source-compiler/1"
SCOPE = (
    "Compile one existing native connection source after merging an identity-qualified "
    "retained File 3/11/12 snapshot. Preserve every other merged expanded byte and the "
    "original graph identities, membership, connections, order and layout. No fresh-setting "
    "guarantee, field transfer, new blocks/connections, general compiler, resource/package "
    "qualification, native execution or CCT/physical acceptance."
)


class EffectiveWireCompiler:
    def __init__(self, files):
        if set(files) != {3, 11, 12}:
            raise ValueError("Compile from one complete retained File 3/11/12 snapshot.")
        self.archive = MoiWireSources(files[3])
        self.merged, self.parameters = ParameterApplication(
            files[3], files[11], files[12]
        ).compile()
        self.effective = MoiWireSources(self.merged)
        before, after = self.archive.editor, self.effective.editor
        old, new = before.summary(), after.summary()
        if any(old[key] != new[key] for key in ("instance", "name", "model")):
            raise ValueError("Saved values would change native controller identity.")
        if before.reader.records.keys() != after.reader.records.keys():
            raise ValueError("Saved values changed native record membership or references.")
        for ref, record in before.reader.records.items():
            merged = after.reader.records[ref]
            if (
                record["class_id"] != merged["class_id"]
                or before.data[record["offset"] + 6 : record["offset"] + 10]
                != after.data[merged["offset"] + 6 : merged["offset"] + 10]
                or record["properties"].get(75, {}).get("encoded_sha256")
                != merged["properties"].get(75, {}).get("encoded_sha256")
            ):
                raise ValueError("Saved values reassigned a native reference or object identity.")
            if record["class_id"] in (536, 575):
                for pid in (3375, 3117, 3118, 3383):
                    if record["properties"].get(pid, {}).get("encoded_sha256") != merged[
                        "properties"
                    ].get(pid, {}).get("encoded_sha256"):
                        raise ValueError(
                            "Saved values changed a native diagram's members, wires, order or layout."
                        )
        self.files = {
            str(key): {"bytes": len(value), "sha256": sha(value)} for key, value in files.items()
        }

    def compile(self, *, effective_sha256, effective_record_sha256, **proposal):
        output, edit = self.effective.compile(
            source_sha256=effective_sha256,
            record_sha256=effective_record_sha256,
            **proposal,
        )
        checked = MoiIdentity(output)
        offset, width = edit["source_index_offset"], edit["source_index_bytes"]
        if (
            checked.data[:offset] != self.effective.editor.data[:offset]
            or checked.data[offset + width :] != self.effective.editor.data[offset + width :]
        ):
            raise ValueError("Wire compilation changed another merged application byte.")
        return output, {
            "profile": PROFILE,
            "scope": SCOPE,
            "files": self.files,
            "parameter_merge": self.parameters,
            "archive_sha256": self.archive.editor.source_sha256,
            "effective_sha256": self.effective.editor.source_sha256,
            "wire_edit": edit,
            "compiled_sha256": sha(output),
            "compiled_native_sha256": sha(checked.data),
            "native_record_count": len(checked.records),
            "other_merged_bytes_preserved": True,
            "saved_settings_merged": True,
            "controller_write": False,
            "field_transfer_enabled": False,
        }


def compiler_from_snapshot(snapshot, files):
    if (
        snapshot.get("source_identity_matches") is not True
        or snapshot.get("identity", {}).get("vendor-identifier") != 5
    ):
        raise ValueError("Select an identity-verified native vendor 5 backup for wire compilation.")
    compiler = EffectiveWireCompiler(files)
    identity = compiler.archive.editor.summary()
    if (
        snapshot["device"] != f"device,{identity['instance']}"
        or snapshot["identity"].get("object-name") != identity["name"]
        or snapshot["identity"].get("model-name") != identity["model"]
    ):
        raise ValueError("Retained native archive and snapshot identity disagree.")
    return compiler
