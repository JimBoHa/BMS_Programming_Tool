"""Operation evidence from one immutable native backup, with no field actions."""

from .moi_boolean_defaults import MoiBooleanDefaults
from .moi_effective_boolean import compiler_from_snapshot as boolean_compiler_from_snapshot
from .moi_identity import MoiIdentity
from .moi_parameters import ParameterApplication
from .moi_signal_defaults import MoiSignalDefaults
from .moi_wire_sources import MoiWireSources
from .native_signal_compiler import compiler_from_snapshot

PROFILE = "native-backup-operation-capabilities/5"


def backup_capabilities(snapshot, files, application):
    identity = snapshot["identity"]
    config = snapshot.get("connector_config", {})
    native, native_error, named = None, None, False
    try:
        editor = MoiIdentity(files[3])
        native = editor.summary()
        prop = editor.root["properties"].get(2390, {})
        named = (prop.get("scalar") or {}).get("datatype") == "CharacterString"
    except ValueError as exc:
        native_error = str(exc)[:512]
    matches = bool(native) and (
        snapshot["device"] == f"device,{native['instance']}"
        and identity.get("object-name") == native["name"]
        and identity.get("model-name") == native["model"]
    )
    vendor = identity.get("vendor-identifier") == 5
    verified = snapshot.get("source_identity_matches") is True and matches and vendor
    plain_ip = (
        isinstance(config.get("local_address"), str)
        and bool(config["local_address"])
        and config.get("transport") is None
        and not config.get("bbmd_address")
    )
    defaults, defaults_error = 0, None
    try:
        defaults = len(MoiSignalDefaults(files[3]).candidates)
    except ValueError as exc:
        defaults_error = str(exc)[:512]
    boolean_count, boolean_error = 0, None
    try:
        boolean_count = len(MoiBooleanDefaults(files[3]).candidates)
    except ValueError as exc:
        boolean_error = str(exc)[:512]
    effective_booleans, effective_boolean_error = [], None
    try:
        effective_booleans = boolean_compiler_from_snapshot(snapshot, files).fields()
    except ValueError as exc:
        effective_boolean_error = str(exc)[:512]
    parameters, parameters_error = None, None
    try:
        merged, parameters = ParameterApplication(files[3], files[11], files[12]).compile()
        MoiIdentity(merged)
    except ValueError as exc:
        parameters, parameters_error = None, str(exc)[:512]
    fields, compiler_error = [], None
    try:
        fields = compiler_from_snapshot(snapshot, files).fields()
    except ValueError as exc:
        compiler_error = str(exc)[:512]

    wire_copy, wire_copy_error = None, None
    try:
        wire_editor = MoiWireSources(files[3])
        for diagram in wire_editor.reader.summary()["diagrams"]:
            try:
                for index in range(diagram["connections"]):
                    info = wire_editor.inspect(diagram["ref"], index)
                    if info["available"]:
                        wire_copy = {
                            "diagram_ref": diagram["ref"],
                            "wire_index": index,
                            "candidate_count": len(info["candidates"]) - 1,
                        }
                        break
            except ValueError as exc:
                wire_copy_error = str(exc)[:512]
            if wire_copy:
                break
    except ValueError as exc:
        wire_copy_error = str(exc)[:512]

    rows = []

    def add(key, operation, status, basis, next_step):
        rows.append(
            dict(id=key, operation=operation, status=status, basis=basis, next_step=next_step)
        )

    add(
        "archive-read",
        "Inspect original archive records",
        "source-qualified",
        "The installed reader recognized the original retained File 3. All three file hashes and the manifest were checked.",
        "Browse captured native records. Archive values are distinct from saved settings and live measurements.",
    )
    diagrams = application["capabilities"]["logic_read"]
    add(
        "diagram-read",
        "Inspect recorded blocks and wires",
        "source-qualified" if diagrams else "unavailable",
        "The reader recognized recorded diagrams."
        if diagrams
        else "No complete diagram is recognized in this archive.",
        "Inspect the actual records; no missing diagram is generated from a model name.",
    )
    for key, title in [
        ("identity-compile", "Compile a Device instance copy"),
        ("name-compile", "Compile a controller-name copy"),
    ]:
        supported = native is not None and (key != "name-compile" or named)
        add(
            key,
            title,
            "source-qualified" if supported else "unsupported-source",
            "The typed identity compiler recognizes this archive."
            if supported
            else native_error or "No typed root Device name was found.",
            "A typed local copy is separate from native saved-setting preservation and the Overview transfer review.",
        )
    add(
        "saved-settings",
        "Merge retained saved application settings",
        "source-qualified" if parameters is not None else "unsupported-source",
        "Files 11/12 passed the installed selector, value, coverage and checksum checks."
        if parameters is not None
        else parameters_error,
        "These are retained values at acquisition time; fresh controller settings remain a separate preflight.",
    )
    add(
        "signal-default-copy",
        "Save an archive Real-default copy",
        "source-qualified" if defaults else "unsupported-source",
        f"The archive contains {defaults} supported existing Real defaults."
        if defaults
        else defaults_error or "No supported class 526/527 Real Default Value was found.",
        "An archive-only copy does not merge saved values or qualify a controller transfer.",
    )
    add(
        "boolean-default-copy",
        "Save an archive Boolean-default copy",
        "source-qualified" if boolean_count else "unsupported-source",
        f"The archive contains {boolean_count} supported existing Boolean defaults."
        if boolean_count
        else boolean_error or "No canonical class 530/531 Boolean Default Value was found.",
        "Inspect the actual record and review a separate archive copy. Saved values are not merged and no Boolean field transfer is prepared.",
    )
    add(
        "wire-source-copy",
        "Save an existing native wire source copy",
        "source-qualified" if wire_copy else "unsupported-source",
        "At least one existing wire has a same-class/configuration observed source pin, earlier execution, no introduced diagram cycle and a fitting index width."
        if wire_copy
        else wire_copy_error
        or "No alternate existing source passes the recorded wire-copy profile.",
        "Inspect the actual activity/control-sequence record and review a local archive copy. Saved settings are not merged; no block/I/O allocation, general logic compiler, field transfer or physical acceptance is granted.",
    )
    add(
        "effective-boolean-compile",
        "Compile an effective native Boolean default",
        "source-qualified" if effective_booleans else "unsupported-source",
        f"The saved-setting compiler qualified {len(effective_booleans)} existing Boolean defaults and the retained Device identity."
        if effective_booleans
        else effective_boolean_error or "No supported effective Boolean defaults were found.",
        "Inspect the actual Boolean record, select Merge retained saved settings and review/save a local compiled copy. This separate compiler prepares no Boolean field transfer.",
    )
    add(
        "effective-default-compile",
        "Compile an effective native Real default",
        "source-qualified" if fields else "unsupported-source",
        f"The actual saved-setting compiler qualified {len(fields)} existing Real defaults and the retained Device identity."
        if fields
        else compiler_error or "No supported effective Real default fields were found.",
        "Open retained backup in the default compiler, select one field and review/save a local compiled copy. Offline compilation does not require the original interface.",
    )

    def transfer_status(qualified, failure):
        if not verified:
            return (
                "source-mismatch",
                "The retained vendor, native root and acquisition identity do not jointly establish a verified vendor-5 source.",
            )
        if not qualified:
            return "unsupported-source", failure
        if not plain_ip:
            return (
                "transport-unavailable",
                "The captured interface was not plain direct or explicitly routed BACnet/IPv4. Offline compilation remains independent of this transport.",
            )
        return (
            "preflight-required",
            "This retained source passes local qualification; it is not a fresh connected review or a prepared write.",
        )

    status, basis = transfer_status(parameters is not None, parameters_error)
    add(
        "identity-transfer",
        "Transfer a reviewed instance or name change",
        status,
        basis,
        "Overview requires the exact connected route/interface, native credentials, fresh backup, settings preservation, capacity, one-use review and full readback. Backup/readback use backup-state commands.",
    )
    status, basis = transfer_status(
        bool(fields), compiler_error or "No supported effective Real default fields were found."
    )
    add(
        "default-transfer",
        "Transfer one effective native Real default",
        status,
        basis,
        "Use the separate Program capture/review/apply/readback workflow. Fresh selected-value and other-setting checks, capacity, credentials, one-use review and uncertainty recovery remain mandatory. Backup/readback use backup-state commands.",
    )
    add(
        "boolean-default-transfer",
        "Transfer one effective native Boolean default",
        *transfer_status(
            bool(effective_booleans),
            effective_boolean_error or "No supported effective Boolean defaults were found.",
        ),
        "Use the separate Boolean controller review/apply/readback workflow. Fresh selected-value and other-setting checks, capacity, credentials, one-use typed review and uncertainty recovery remain mandatory. Capture/readback use backup-state commands; Apply can interrupt control.",
    )
    add(
        "general-logic",
        "Compile arbitrary native blocks and wires",
        "unavailable",
        "Installed native compilers cover typed identity, existing Real/Boolean defaults and a scoped existing-wire source archive copy, not arbitrary logic generation.",
        "Retain original bytes; broader writers require independently qualified native references and resource allocation.",
    )
    add(
        "release-packages",
        "Verify release and package compatibility",
        "not-evaluated",
        "Captured firmware and native ACS/DMCS values are evidence in separate version namespaces, not a package compatibility table.",
        "Retain exact package/release evidence and run a separately qualified destination preflight.",
    )
    add(
        "physical-acceptance",
        "Establish physical controller acceptance",
        "not-inferred",
        "Local parsing and saved-value compilation do not establish acceptance by a physical controller.",
        "Keep actual transfer/readback outcomes tied to their target and time; this analysis does not correlate or replace those receipts.",
    )
    return {
        "capability_profile": PROFILE,
        "operations": rows,
        "qualification": {
            "native_identity": native,
            "native_identity_error": native_error,
            "identity_matches_snapshot": bool(matches),
            "recorded_identity_verified": bool(verified),
            "captured_plain_ipv4": bool(plain_ip),
            "archive_real_default_count": defaults,
            "archive_boolean_default_count": boolean_count,
            "archive_wire_source_copy": wire_copy,
            "archive_wire_source_copy_error": wire_copy_error,
            "effective_boolean_default_count": len(effective_booleans),
            "effective_real_default_count": len(fields),
            "parameter_merge": parameters,
            "parameter_merge_error": parameters_error,
            "effective_compiler_error": compiler_error,
            "captured_firmware": identity.get("firmware-revision"),
        },
        "can_apply": False,
        "current_identity_verified": False,
        "scope": "Local analysis of original File 3 and retained saved Files 11/12. Source-qualified means recognized by installed software, not a prepared write, current setting or physical acceptance. No controller query, backup-state command, compilation intent or transfer is performed.",
    }
