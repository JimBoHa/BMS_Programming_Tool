"""Recover a previous source using its verified original pin when no current pin remains."""

from .moi_identity import seal, sha
from .native_historical_pin import PROFILE as PIN_PROFILE
from .native_historical_pin import HistoricalWireCompiler, RecordedWirePin
from .native_wire_compiler import EffectiveWirePreview
from .native_wire_recovery import NativeWireRecovery
from .native_wire_transfer import compile_wire

PROFILE = "native-historical-pin-wire-recovery-draft/1"
SCOPE = (
    "Local previous-source proposal using the actual original output pin from a historically "
    "verified wire transfer. The current original-after application/static directory/route/identity "
    "and prior source's non-default configuration must remain qualified. Preserve inherited "
    "class/configuration/order/cycle/width checks and current other saved settings. No arbitrary "
    "pin, old-plan replay, controller query, automatic rollback or general graph allocation. "
    "A new reviewed transfer with full native/effective readback is required."
)


class NativeHistoricalWireRecovery(NativeWireRecovery):
    def _inverse(self, files, proposal, *, original, selected):
        # An ordinary eligible candidate keeps the exact v1 report and compiler.
        from .moi_effective_wire import EffectiveWireCompiler

        current = EffectiveWireCompiler(files)
        inspection = current.effective.inspect(proposal["diagram_ref"], proposal["wire_index"])
        if any(row["ref"] == proposal["source_ref"] for row in inspection["candidates"]):
            return super()._inverse(files, proposal, original=original, selected=selected)
        before, old = original
        graph, record, _, wires = old.effective.graph(proposal["diagram_ref"])
        wire = wires[proposal["wire_index"]]
        source = next(row for row in graph["blocks"] if row["ref"] == wire["source_ref"])
        pin = RecordedWirePin.model_validate(
            {
                "profile": PIN_PROFILE,
                "original_capture_id": before["id"],
                "original_snapshot_sha256": before["evidence_sha256"],
                "original_native_sha256": sha(old.effective.editor.data),
                "after_native_sha256": selected["output_native_sha256"],
                "current_archive_sha256": sha(files[3]),
                "diagram_ref": proposal["diagram_ref"],
                "diagram_class": record["class_id"],
                "wire_index": proposal["wire_index"],
                "old": wire["old"],
                "source_ref": wire["source_ref"],
                "source_class": source["class_id"],
                "source_object": source["object"],
                "source_configuration_sha256": seal(old.effective.signatures[wire["source_ref"]]),
                "target_ref": wire["target_ref"],
                "source_index_bytes": wire["source_index_bytes"],
            }
        ).model_dump()
        return compile_wire(files, proposal, _compiler=HistoricalWireCompiler(files, pin))

    def _report(self, body, inverse, compiler):
        pin = inverse.get("historical_pin_evidence")
        if pin is None:
            return super()._report(body, inverse, compiler)
        graph = compiler.effective.graph(pin["diagram_ref"])[0]
        source = next(row for row in graph["blocks"] if row["ref"] == pin["source_ref"])
        origin = {
            **body["origin"],
            "profile": PROFILE,
            "historical_pin": pin,
            "historical_pin_sha256": seal(pin),
        }
        candidate = {key: source[key] for key in ("index", "ref", "name", "class_id", "object")} | {
            "current_source": False
        }
        result = {
            **body,
            "profile": PROFILE,
            "scope": SCOPE,
            "origin": origin,
            "origin_sha256": seal(origin),
            "proposal_candidate": candidate,
        }
        return {**result, "evidence_sha256": seal(result)}

    def compiler_for(self, prepared, files):
        """Only a freshly reconstructed report can qualify a compiler for a new write."""
        if prepared["profile"] != PROFILE:
            return None
        return HistoricalWireCompiler(files, prepared["origin"]["historical_pin"])

    def reviewed_compiler(self, options, files):
        if options.recovery_parent_receipt is None:
            return None
        prepared = self.prepare(
            {
                "receipt_id": options.recovery_parent_receipt,
                "capture_id": options.capture_id,
                "snapshot_sha256": options.snapshot_sha256,
            }
        )
        proposal = prepared["proposal"]
        if (
            proposal is None
            or prepared["origin_sha256"] != options.recovery_origin_sha256
            or seal({key: proposal[key] for key in EffectiveWirePreview.model_fields})
            != seal(options.model_dump(include=set(EffectiveWirePreview.model_fields)))
        ):
            raise ValueError("The retained-pin proposal changed; prepare and review it again.")
        return self.compiler_for(prepared, files)

    def recorded_compiler(self, intent, files):
        """Reconstruct readback/original-payload proof; never admit a new write from metadata."""
        origin = intent.get("recovery_origin")
        if not isinstance(origin, dict) or origin.get("profile") != PROFILE:
            return None
        # The recorded decoder validates its strict type, seal and child bindings.
        # New write admission instead calls reviewed_compiler/prepare above.
        from .native_ledger_details import native_reference, wire_recovery_lineage

        reference = native_reference("wire-source", intent.get("wire_edit"))
        if wire_recovery_lineage(intent, reference)["state"] != "recorded":
            raise ValueError("The recorded historical pin or its child bindings are inconsistent.")
        return HistoricalWireCompiler(files, intent["recovery_origin"]["historical_pin"])

    def _forward(self, files, edit, *, intent):
        return compile_wire(
            files,
            edit,
            fresh=True,
            expected_guard=intent.get("wire_guard"),
            _compiler=self.recorded_compiler(intent, files),
        )
