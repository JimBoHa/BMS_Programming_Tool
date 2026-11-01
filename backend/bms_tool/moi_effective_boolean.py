"""Pure saved-setting-merged Boolean default compilation."""

from .moi_boolean_defaults import MoiBooleanDefaults
from .moi_identity import MoiIdentity, sha
from .moi_parameters import ParameterApplication

PROFILE = "native-effective-boolean-default-compiler/1"
SCOPE = (
    "Compile one existing class 530/531 Boolean Default Value after merging this "
    "identity-qualified retained File 3/11/12 snapshot's saved application values. "
    "Preserve every other merged expanded byte. No fresh-setting guarantee, "
    "controller transfer, general logic generation or CCT/physical acceptance."
)


class EffectiveBooleanCompiler:
    def __init__(self, files):
        if set(files) != {3, 11, 12}:
            raise ValueError("Compile from one complete retained File 3/11/12 snapshot.")
        self.archive = MoiBooleanDefaults(files[3])
        self.merged, self.parameters = ParameterApplication(
            files[3], files[11], files[12]
        ).compile()
        self.effective = MoiBooleanDefaults(self.merged)
        before, after = self.archive.editor.summary(), self.effective.editor.summary()
        if any(before[key] != after[key] for key in ("instance", "name", "model")):
            raise ValueError("Saved values would change native identity; this compiler refuses it.")
        if self.archive.candidates.keys() != self.effective.candidates.keys():
            raise ValueError("Saved values changed supported Boolean membership or references.")
        for ref, (record, _) in self.effective.candidates.items():
            original, _ = self.archive.candidates[ref]
            old_id = self.archive.editor.data[original["offset"] + 6 : original["offset"] + 10]
            new_id = self.effective.editor.data[record["offset"] + 6 : record["offset"] + 10]
            if old_id != new_id or original["class_id"] != record["class_id"]:
                raise ValueError("Saved values reassigned a Boolean reference or native class.")
        self.files = {
            str(key): {"bytes": len(value), "sha256": sha(value)} for key, value in files.items()
        }

    def fields(self):
        if len(self.effective.candidates) > 4096:
            raise ValueError("This compiler view supports at most 4096 existing Boolean defaults.")
        result = []
        for ref, (record, prop) in sorted(self.effective.candidates.items()):
            _, original = self.archive.candidates[ref]
            result.append(
                {
                    "ref": ref,
                    "class_id": record["class_id"],
                    "property": 3113,
                    "datatype": "Boolean",
                    "encoded_sha256": prop["encoded_sha256"],
                    "archive_value": original["scalar"]["value"],
                    "effective_value": prop["scalar"]["value"],
                    "saved_value_differs": prop["encoded_sha256"] != original["encoded_sha256"],
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
        output, edit = self.effective.export(**arguments, plan_sha256=plan["plan_sha256"])
        checked = MoiIdentity(output)
        before, offset = self.effective.editor, edit["native_byte_offset"]
        if (
            checked.data[:offset] != before.data[:offset]
            or checked.data[offset + 1 :] != before.data[offset + 1 :]
        ):
            raise ValueError("Boolean compilation changed another merged application byte.")
        return output, {
            "profile": PROFILE,
            "scope": SCOPE,
            "files": self.files,
            "parameter_merge": self.parameters,
            "selected_edit": edit,
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
        raise ValueError(
            "Select an identity-verified native vendor 5 backup for effective compilation."
        )
    compiler = EffectiveBooleanCompiler(files)
    identity = compiler.archive.editor.summary()
    if (
        snapshot["device"] != f"device,{identity['instance']}"
        or snapshot["identity"].get("object-name") != identity["name"]
        or snapshot["identity"].get("model-name") != identity["model"]
    ):
        raise ValueError("Retained native archive and snapshot identity disagree.")
    return compiler
