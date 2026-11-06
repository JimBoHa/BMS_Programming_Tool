"""Compose existing typed defaults over one saved merge, without a field writer."""

import struct

from .moi_boolean_defaults import MoiBooleanDefaults
from .moi_effective_boolean import PROFILE as BOOLEAN_PROFILE
from .moi_effective_boolean import EffectiveBooleanCompiler
from .moi_effective_boolean import compiler_from_snapshot as boolean_from_snapshot
from .moi_effective_enum import PROFILE as ENUM_PROFILE
from .moi_effective_enum import EffectiveEnumCompiler
from .moi_effective_enum import compiler_from_snapshot as enum_from_snapshot
from .moi_enum_defaults import MoiEnumDefaults
from .moi_identity import MoiIdentity, sha
from .moi_signal_defaults import MoiSignalDefaults
from .native_signal_compiler import PROFILE as REAL_PROFILE
from .native_signal_compiler import EffectiveSignalCompiler
from .native_signal_compiler import compiler_from_snapshot as real_from_snapshot

PROFILE = "native-effective-default-batch-compiler/1"
LIMIT = 16
SCOPE = (
    "Local compilation of 1–16 distinct existing Real, Boolean or Enumerated Default Value "
    "fields from one identity-qualified retained File 3/11/12 saved merge. Preserve all "
    "other expanded bytes, record identities and captured metadata; independently reparse "
    "both edit orders without merging saved values over edited intermediates. Enum code "
    "membership/meaning, current settings, new logic, package/resource/runtime validation, "
    "controller transfer and CCT/physical acceptance remain separate."
)
FAMILIES = {
    "real": (EffectiveSignalCompiler, real_from_snapshot, MoiSignalDefaults, REAL_PROFILE),
    "boolean": (
        EffectiveBooleanCompiler,
        boolean_from_snapshot,
        MoiBooleanDefaults,
        BOOLEAN_PROFILE,
    ),
    "enum": (EffectiveEnumCompiler, enum_from_snapshot, MoiEnumDefaults, ENUM_PROFILE),
}


class EffectiveDefaultBatchCompiler:
    def __init__(self, files, *, snapshot=None):
        self.compilers = {
            kind: from_snapshot(snapshot, files) if snapshot is not None else constructor(files)
            for kind, (constructor, from_snapshot, _, _) in FAMILIES.items()
        }
        first = self.compilers["real"]
        self.merged, self.parameters, self.files = first.merged, first.parameters, first.files
        if any(
            compiler.merged != self.merged
            or compiler.parameters != self.parameters
            or compiler.files != self.files
            for compiler in self.compilers.values()
        ):
            raise ValueError("Typed native compilers did not qualify the identical saved merge.")
        self.original = MoiIdentity(self.merged)

    def _name(self, ref):
        name = self.original.reader.scalar(self.original.reader.records[ref], 2390)
        return name if isinstance(name, str) and name else ref

    def fields(self):
        fields = [
            {
                "kind": kind,
                "profile": FAMILIES[kind][3],
                "field": field,
                "name": self._name(field["ref"]),
            }
            for kind, compiler in self.compilers.items()
            for field in compiler.fields()
        ]
        if len(fields) > 4096:
            raise ValueError("The batch view supports at most 4096 existing typed defaults.")
        if len({row["field"]["ref"] for row in fields}) != len(fields):
            raise ValueError("Native typed default references must be distinct.")
        return fields

    def _compose(self, changes):
        """Only archive editors see intermediates; saved merging never runs here."""
        output, steps = self.merged, []
        for change in changes:
            editor = FAMILIES[change["kind"]][2](output)
            ref = change["record_ref"]
            if ref not in editor.candidates:
                raise ValueError("An intermediate lost a selected typed default.")
            _, prop = editor.candidates[ref]
            request = {
                "source_sha256": sha(output),
                "record_ref": ref,
                "encoded_sha256": prop["encoded_sha256"],
                **(
                    {"value_text": change["value_text"]}
                    if change["kind"] == "real"
                    else {"value": change["value"]}
                ),
            }
            plan = editor.preview(**request)
            output, edit = editor.export(**request, plan_sha256=plan["plan_sha256"])
            steps.append({"kind": change["kind"], "record_ref": ref, "edit": edit})
        return output, steps

    def _patch_records(self, patches):
        app = self.original
        data, previous = bytearray(app.data[:14]), 14
        for record in app.records:
            start, end = record["offset"], record["end_offset"]
            prefix, raw = app.data[previous:start], app.data[start:end]
            ref = app.reader.scalar(record, 32527)
            if isinstance(ref, str) and ref in patches:
                prop = record["properties"][3113]
                a, b = prop["value_start_offset"], prop["value_end_offset"]
                raw = app.data[start:a] + patches[ref] + app.data[b:end]
                if len(raw) != end - start:
                    prefix = (
                        b"\x00\x00" + struct.pack("<I", len(raw) + 6)
                        if len(prefix) == 6 or len(raw) + 2 > 65535
                        else struct.pack("<H", len(raw) + 2)
                    )
            data.extend(prefix + raw)
            previous = end
        return bytes(data)

    def compile(self, changes):
        if not isinstance(changes, list) or not 1 <= len(changes) <= LIMIT:
            raise ValueError("Select 1–16 distinct typed native default edits.")
        if len({row["record_ref"] for row in changes}) != len(changes):
            raise ValueError("Select each existing native default at most once.")
        available = {(row["kind"], row["field"]["ref"]): row["field"] for row in self.fields()}
        patches, independent, selected = {}, [], []
        for change in changes:
            kind, ref = change["kind"], change["record_ref"]
            field = available.get((kind, ref))
            if field is None or field["encoded_sha256"] != change["encoded_sha256"]:
                raise ValueError("The selected typed native field or encoding changed.")
            output, report = self.compilers[kind].compile(
                **{key: value for key, value in change.items() if key != "kind"}
            )
            checked = MoiIdentity(output)
            before = self.original.reader.records[ref]
            after = checked.reader.records.get(ref)
            if after is None or after["class_id"] != before["class_id"]:
                raise ValueError("An independent compiler lost or reassigned its selected default.")
            prop, new_prop = before["properties"][3113], after["properties"][3113]
            a, b = prop["value_start_offset"], prop["value_end_offset"]
            after_encoding = checked.data[
                new_prop["value_start_offset"] : new_prop["value_end_offset"]
            ]
            if (
                report["compiled_sha256"] != sha(output)
                or report["compiled_native_sha256"] != sha(checked.data)
                or report["files"] != self.files
                or report["parameter_merge"] != self.parameters
                or checked.data != self._patch_records({ref: after_encoding})
            ):
                raise ValueError(
                    "An independent typed compilation contradicts its saved source or bytes."
                )
            patches[ref] = after_encoding
            independent.append({"kind": kind, "record_ref": ref, "compilation": report})
            selected.append(
                {
                    "kind": kind,
                    "record_ref": ref,
                    "class_id": before["class_id"],
                    "property": 3113,
                    "encoded_sha256": change["encoded_sha256"],
                    "before_encoding_hex": self.original.data[a:b].hex(),
                    "after_encoding_hex": after_encoding.hex(),
                    "before_record_sha256": before["sha256"],
                    "independent_after_record_sha256": after["sha256"],
                    "original_value_start_offset": a,
                    "original_value_end_offset": b,
                    "changed": self.original.data[a:b] != after_encoding,
                    "enum_semantics_verified": False,
                }
            )
        expected = self._patch_records(patches)
        forward, forward_steps = self._compose(changes)
        reverse, reverse_steps = self._compose(list(reversed(changes)))
        checked, backward = MoiIdentity(forward), MoiIdentity(reverse)
        if (
            checked.data != expected
            or backward.data != expected
            or forward != reverse
            or checked.reader.records.keys() != self.original.reader.records.keys()
            or checked.data[:14] != self.original.data[:14]
            or any(
                checked.summary()[key] != self.original.summary()[key]
                for key in ("instance", "name", "model")
            )
        ):
            raise ValueError(
                "Native batch failed literal byte, identity or composition preservation."
            )
        changed = sum(row["changed"] for row in selected)
        if not changed and forward != self.merged:
            raise ValueError("A no-change batch must preserve the exact merged source.")
        return forward, {
            "profile": PROFILE,
            "scope": SCOPE,
            "files": self.files,
            "parameter_merge": self.parameters,
            "effective_sha256": sha(self.merged),
            "effective_native_sha256": sha(self.original.data),
            "compiled_sha256": sha(forward),
            "compiled_native_sha256": sha(checked.data),
            "compiled_native_bytes": len(checked.data),
            "effective_native_bytes": len(self.original.data),
            "native_record_count": len(checked.records),
            "edit_count": len(changes),
            "changed_count": changed,
            "selected": selected,
            "independent": independent,
            "forward": forward_steps,
            "reverse": reverse_steps,
            "both_orders_identical": True,
            "other_merged_bytes_preserved": True,
            "saved_settings_merged": True,
            "enum_semantics_verified": False,
            "controller_queries": False,
            "controller_write": False,
            "field_transfer_enabled": False,
        }
