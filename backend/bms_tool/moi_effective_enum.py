"""Local Enum code compilation after an identity-qualified saved-value merge."""

from .moi_enum_defaults import MoiEnumDefaults
from .moi_identity import MoiIdentity, sha
from .moi_parameters import STORAGE, ParameterApplication

PROFILE = "native-effective-enum-default-compiler/1"
SCOPE = (
    "Compile one existing class 528/529 Enumerated Default Value after merging "
    "this identity-qualified retained File 3/11/12 snapshot's saved values. "
    "Preserve other merged native bytes and captured state metadata. A captured "
    "fixed Enum slot bounds the proposed numeric code; no slot means only the "
    "local unsigned32 representation is checked. Code membership, state meaning, "
    "executable mappings, release/resource compatibility and physical acceptance "
    "remain unverified. No current-setting guarantee, saved-file mutation, "
    "controller transfer or general native logic generation."
)


class EffectiveEnumCompiler:
    def __init__(self, files):
        if set(files) != {3, 11, 12}:
            raise ValueError("Compile from one complete retained File 3/11/12 snapshot.")
        self.archive = MoiEnumDefaults(files[3])
        parameters = ParameterApplication(files[3], files[11], files[12])
        self.merged, self.parameters = parameters.compile()
        self.effective = MoiEnumDefaults(self.merged)
        before, after = self.archive.editor.summary(), self.effective.editor.summary()
        if any(before[key] != after[key] for key in ("instance", "name", "model")):
            raise ValueError("Saved values would change native identity; this compiler refuses it.")
        if self.archive.candidates.keys() != self.effective.candidates.keys():
            raise ValueError("Saved values changed supported Enum membership or references.")
        for ref, (record, _) in self.effective.candidates.items():
            original, _ = self.archive.candidates[ref]
            old_id = self.archive.editor.data[original["offset"] + 6 : original["offset"] + 10]
            new_id = self.effective.editor.data[record["offset"] + 6 : record["offset"] + 10]
            if old_id != new_id or original["class_id"] != record["class_id"]:
                raise ValueError("Saved values reassigned an Enum reference or native class.")
        self.files = {
            str(key): {"bytes": len(value), "sha256": sha(value)} for key, value in files.items()
        }
        # The existing parameter parser has already validated every directory
        # row, selector, range, datatype, CRC and dynamic-storage byte. Retain
        # actual fixed Enum capacity; never select a capacity from a model name.
        self.storage = {}
        static, offset = files[11], 0
        while offset < len(static):
            length = int.from_bytes(static[offset : offset + 2], "big")
            row = static[offset : offset + length]
            selector = int.from_bytes(row[2:6], "big")
            pid, flags, datatype = int.from_bytes(row[6:8], "big"), row[8], row[9]
            cid = int.from_bytes(row[10:12], "big")
            if cid in (528, 529) and pid == 3113 and flags in (0x6F, 0xEF) and datatype == 9:
                width = STORAGE[datatype][0]
                key = cid, selector & 4194303
                if key in self.storage:
                    raise ValueError("Multiple saved Enum capacities refer to one native object.")
                self.storage[key] = {
                    "kind": "captured-fixed-enum-slot",
                    "datatype": datatype,
                    "bytes": width,
                    "maximum_code": (1 << (8 * width)) - 1,
                    "static_record_offset": offset,
                    "dynamic_value_offset": int.from_bytes(row[12:14], "big"),
                }
            offset += length

    def fields(self):
        if len(self.effective.candidates) > 4096:
            raise ValueError("This compiler view supports at most 4096 existing Enum defaults.")
        result = []
        for ref, (record, prop) in sorted(self.effective.candidates.items()):
            _, original = self.archive.candidates[ref]
            instance = (
                int.from_bytes(
                    self.effective.editor.data[record["offset"] + 6 : record["offset"] + 10], "big"
                )
                & 4194303
            )
            storage = self.storage.get((record["class_id"], instance))
            result.append(
                {
                    "ref": ref,
                    "class_id": record["class_id"],
                    "property": 3113,
                    "datatype": "Enumerated",
                    "encoded_sha256": prop["encoded_sha256"],
                    "archive_value": original["scalar"]["value"],
                    "effective_value": prop["scalar"]["value"],
                    "saved_value_differs": prop["encoded_sha256"] != original["encoded_sha256"],
                    "saved_storage": storage,
                    "maximum_code": storage["maximum_code"] if storage else 4294967295,
                    "states_text_evidence": record["properties"].get(931, {}).get("scalar"),
                    "states_text_encoded_sha256": record["properties"]
                    .get(931, {})
                    .get("encoded_sha256"),
                    "enum_semantics_verified": False,
                }
            )
        return result

    def compile(self, *, record_ref, encoded_sha256, value):
        arguments = {
            "source_sha256": self.effective.editor.source_sha256,
            "record_ref": record_ref,
            "encoded_sha256": encoded_sha256,
            "value": value,
        }
        plan = self.effective.preview(**arguments)
        field = next(row for row in self.fields() if row["ref"] == record_ref)
        if value > field["maximum_code"]:
            raise ValueError(
                "Proposed Enum code exceeds its captured fixed saved-storage capacity."
            )
        output, edit = self.effective.export(**arguments, plan_sha256=plan["plan_sha256"])
        checked = MoiIdentity(output)
        return output, {
            "profile": PROFILE,
            "scope": SCOPE,
            "files": self.files,
            "parameter_merge": self.parameters,
            "selected_edit": edit,
            "saved_storage": field["saved_storage"],
            "maximum_code": field["maximum_code"],
            "compiled_sha256": sha(output),
            "compiled_native_sha256": sha(checked.data),
            "native_record_count": len(checked.records),
            "other_merged_bytes_preserved": edit["unrelated_native_bytes_preserved"],
            "saved_settings_merged": True,
            "enum_semantics_verified": False,
            "controller_write": False,
            "field_transfer_enabled": False,
        }


def compiler_from_snapshot(snapshot, files):
    if (
        snapshot.get("source_identity_matches") is not True
        or snapshot.get("identity", {}).get("vendor-identifier") != 5
    ):
        raise ValueError(
            "Select an identity-verified native vendor 5 backup for effective compilation."
        )
    compiler = EffectiveEnumCompiler(files)
    identity = compiler.archive.editor.summary()
    if (
        snapshot["device"] != f"device,{identity['instance']}"
        or snapshot["identity"].get("object-name") != identity["name"]
        or snapshot["identity"].get("model-name") != identity["model"]
    ):
        raise ValueError("Retained native archive and snapshot identity disagree.")
    return compiler
