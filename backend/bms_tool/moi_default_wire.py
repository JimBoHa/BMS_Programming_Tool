"""Compose two qualified existing-field edits over the same saved native image."""

from .moi_effective_wire import EffectiveWireCompiler
from .moi_effective_wire import compiler_from_snapshot as wire_from_snapshot
from .moi_identity import MoiIdentity, sha
from .moi_signal_defaults import MoiSignalDefaults
from .moi_wire_sources import MoiWireSources
from .native_signal_compiler import EffectiveSignalCompiler
from .native_signal_compiler import compiler_from_snapshot as signal_from_snapshot

PROFILE = "native-effective-default-wire-compiler/1"
SCOPE = (
    "Compile one existing class 526/527 Real default and one existing connection source "
    "from the identical identity-qualified retained File 3/11/12 saved-parameter merge. "
    "Qualify both edits independently, reparse both composition orders and preserve every "
    "other merged expanded byte. Local review/export only: no controller queries/writes, "
    "fresh-setting guarantee, transfer grant, new blocks/connections, general compiler, "
    "resource/package/runtime qualification or CCT/physical acceptance."
)


class EffectiveDefaultWireCompiler:
    def __init__(self, files, *, snapshot=None):
        self.signal = (
            signal_from_snapshot(snapshot, files)
            if snapshot is not None
            else EffectiveSignalCompiler(files)
        )
        self.wire = (
            wire_from_snapshot(snapshot, files)
            if snapshot is not None
            else EffectiveWireCompiler(files)
        )
        # Both existing compiler qualifications run against the original files.
        # Neither is allowed to merge saved parameters over an edited intermediate.
        if self.signal.merged != self.wire.merged or self.signal.parameters != self.wire.parameters:
            raise ValueError("The two native compilers did not qualify the identical saved merge.")
        self.merged = self.signal.merged
        self.parameters = self.signal.parameters
        self.files = self.signal.files

    def diagrams(self):
        records = self.wire.effective.reader.records
        refs = sorted(ref for ref, row in records.items() if row["class_id"] in (536, 575))
        if len(refs) > 4096:
            raise ValueError("This combined compiler view supports at most 4096 native diagrams.")
        result = []
        for ref in refs:
            row = {
                "ref": ref,
                "class_id": records[ref]["class_id"],
                "archive_record_sha256": self.wire.archive.reader.records[ref]["sha256"],
                "effective_record_sha256": records[ref]["sha256"],
            }
            try:
                graph, _, _, wires = self.wire.effective.graph(ref)
                row.update(
                    name=graph["name"], wire_count=len(wires), available=bool(wires), error=None
                )
            except ValueError as exc:
                row.update(name=ref, wire_count=0, available=False, error=str(exc))
            result.append(row)
        return result

    def selection(self, *, source_sha256, effective_sha256, diagram_ref, record_sha256, wire_index):
        if source_sha256 != self.wire.archive.editor.source_sha256:
            raise ValueError("The original native archive changed; reopen the retained source.")
        if effective_sha256 != sha(self.merged):
            raise ValueError("The saved native merge changed; reopen the retained source.")
        record = self.wire.archive.reader.records.get(diagram_ref)
        if record is None or record["sha256"] != record_sha256:
            raise ValueError("The original native diagram changed; inspect it again.")
        return self.wire.effective.inspect(diagram_ref, wire_index)

    def compile(
        self,
        *,
        record_ref,
        encoded_sha256,
        value_text,
        effective_sha256,
        effective_record_sha256,
        diagram_ref,
        property_sha256,
        wire_index,
        old,
        source_ref,
    ):
        # Retain the original reports verbatim: a combined result is not either
        # narrow compiler's output or a grant from either narrow transfer profile.
        signal_output, signal_report = self.signal.compile(
            record_ref=record_ref, encoded_sha256=encoded_sha256, value_text=value_text
        )
        wire_args = dict(
            diagram_ref=diagram_ref,
            property_sha256=property_sha256,
            wire_index=wire_index,
            old=old,
            source_ref=source_ref,
        )
        wire_output, wire_report = self.wire.compile(
            effective_sha256=effective_sha256,
            effective_record_sha256=effective_record_sha256,
            **wire_args,
        )
        default_edit = signal_report["selected_edit"]
        wire_edit = wire_report["wire_edit"]
        signal_offset = default_edit["native_byte_offset"]
        wire_offset, width = wire_edit["source_index_offset"], wire_edit["source_index_bytes"]
        before = self.signal.effective.editor
        if not (
            0 <= signal_offset <= len(before.data) - 4
            and 0 <= wire_offset <= len(before.data) - width
            and 1 <= width <= 4
            and (signal_offset + 4 <= wire_offset or wire_offset + width <= signal_offset)
        ):
            raise ValueError("Combined edits require disjoint bounded existing native fields.")
        expected = bytearray(before.data)
        expected[signal_offset : signal_offset + 4] = bytes.fromhex(default_edit["after_bits"])
        expected[wire_offset : wire_offset + width] = wire_edit["new"][0].to_bytes(width, "big")

        wire_after_signal = MoiWireSources(signal_output)
        forward, forward_edit = wire_after_signal.compile(
            source_sha256=sha(signal_output), record_sha256=effective_record_sha256, **wire_args
        )
        signal_after_wire = MoiSignalDefaults(wire_output)
        reverse_request = dict(
            source_sha256=sha(wire_output),
            record_ref=record_ref,
            encoded_sha256=encoded_sha256,
            value_text=value_text,
        )
        reverse_plan = signal_after_wire.preview(**reverse_request)
        reverse, reverse_edit = signal_after_wire.export(
            **reverse_request, plan_sha256=reverse_plan["plan_sha256"]
        )
        checked = MoiIdentity(forward)
        reverse_checked = MoiIdentity(reverse)
        if (
            checked.data != bytes(expected)
            or reverse_checked.data != bytes(expected)
            or forward != reverse
            or checked.reader.records.keys() != before.reader.records.keys()
            or any(
                checked.summary()[key] != before.summary()[key]
                for key in ("instance", "name", "model")
            )
        ):
            raise ValueError(
                "Combined native output failed byte, identity or composition preservation."
            )
        if not default_edit["changed"] and not wire_edit["changed"] and forward != self.merged:
            raise ValueError("A combined no-op must preserve the exact merged source bytes.")
        return forward, {
            "profile": PROFILE,
            "scope": SCOPE,
            "files": self.files,
            "parameter_merge": self.parameters,
            "archive_sha256": self.wire.archive.editor.source_sha256,
            "effective_sha256": sha(self.merged),
            "effective_native_sha256": sha(before.data),
            "independent_default": signal_report,
            "independent_wire": wire_report,
            "default_then_wire": {
                "intermediate_sha256": sha(signal_output),
                "wire_edit": forward_edit,
            },
            "wire_then_default": {
                "intermediate_sha256": sha(wire_output),
                "default_edit": reverse_edit,
            },
            "selected_default": default_edit,
            "selected_wire": wire_edit,
            "compiled_sha256": sha(forward),
            "compiled_native_sha256": sha(checked.data),
            "native_record_count": len(checked.records),
            "both_orders_identical": True,
            "disjoint_fields": True,
            "other_merged_bytes_preserved": True,
            "saved_settings_merged": True,
            "controller_queries": False,
            "controller_write": False,
            "field_transfer_enabled": False,
            "can_apply": False,
        }
