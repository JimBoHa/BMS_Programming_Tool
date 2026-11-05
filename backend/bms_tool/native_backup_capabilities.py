"""Operation evidence from one immutable native backup, with no field actions."""

from .moi_boolean_defaults import MoiBooleanDefaults
from .moi_connection_copies import MoiConnectionCopies
from .moi_effective_boolean import compiler_from_snapshot as boolean_compiler_from_snapshot
from .moi_effective_connection import compiler_from_snapshot as connection_compiler_from_snapshot
from .moi_effective_enum import compiler_from_snapshot as enum_compiler_from_snapshot
from .moi_effective_wire import compiler_from_snapshot as wire_compiler_from_snapshot
from .moi_enum_defaults import MoiEnumDefaults
from .moi_graph_candidates import eligible_connection, eligible_wire
from .moi_identity import MoiIdentity
from .moi_parameters import ParameterApplication
from .moi_signal_defaults import MoiSignalDefaults
from .moi_wire_sources import MoiWireSources
from .native_signal_compiler import compiler_from_snapshot

LEGACY_PROFILE = "native-backup-operation-capabilities/11"
PROFILE = "native-backup-operation-capabilities/12"
CONNECTION_TRANSFER_PROFILE = "native-backup-operation-capabilities/13"


def backup_capabilities(snapshot, files, application, *, capability_profile=PROFILE):
    if capability_profile not in (PROFILE, LEGACY_PROFILE, CONNECTION_TRANSFER_PROFILE):
        raise ValueError("Select a supported native operation capability profile.")
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
    enum_count, enum_error = 0, None
    try:
        enum_count = len(MoiEnumDefaults(files[3]).candidates)
    except ValueError as exc:
        enum_error = str(exc)[:512]
    effective_booleans, effective_boolean_error = [], None
    try:
        effective_booleans = boolean_compiler_from_snapshot(snapshot, files).fields()
    except ValueError as exc:
        effective_boolean_error = str(exc)[:512]
    effective_enums, effective_enum_error = [], None
    try:
        effective_enums = enum_compiler_from_snapshot(snapshot, files).fields()
    except ValueError as exc:
        effective_enum_error = str(exc)[:512]
    fixed_enums = sum(field["saved_storage"] is not None for field in effective_enums)
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
        wire_copy, wire_copy_error = eligible_wire(MoiWireSources(files[3]))
    except ValueError as exc:
        wire_copy_error = str(exc)[:512]

    effective_wire, effective_wire_error = None, None
    try:
        effective_wire, effective_wire_error = eligible_wire(
            wire_compiler_from_snapshot(snapshot, files).effective
        )
    except ValueError as exc:
        effective_wire_error = str(exc)[:512]

    connection_copy = effective_connection = None
    connection_copy_error = effective_connection_error = None
    if capability_profile in (PROFILE, CONNECTION_TRANSFER_PROFILE):
        try:
            connection_copy, connection_copy_error = eligible_connection(
                MoiConnectionCopies(files[3])
            )
        except ValueError as exc:
            connection_copy_error = str(exc)[:512]
        try:
            effective_connection, effective_connection_error = eligible_connection(
                connection_compiler_from_snapshot(snapshot, files).effective
            )
        except ValueError as exc:
            effective_connection_error = str(exc)[:512]

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
    add(
        "retained-backup-comparison",
        "Compare original retained backups",
        "source-qualified",
        "This manifest and Files 3/11/12 passed integrity checks and can supply one local comparison source.",
        "Select both original backups in Compare retained backups. Byte comparisons remain separate from unambiguous engineering-record/property alignment; no saved-setting merge, compatibility or restore is inferred.",
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
        "enum-default-copy",
        "Save an archive Enum-code copy",
        "source-qualified" if enum_count else "unsupported-source",
        f"The archive contains {enum_count} supported existing Enumerated defaults. Code membership and state meanings remain unverified."
        if enum_count
        else enum_error or "No supported class 528/529 Enumerated Default Value was found.",
        "Inspect the actual record and review a local Enum code file copy. Saved settings are not merged; no executable mapping, Enum field transfer or physical acceptance is granted.",
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
        "effective-wire-compile",
        "Compile an effective native wire source",
        "source-qualified" if effective_wire else "unsupported-source",
        "The identity-qualified saved merge preserves the original graph structure and admits an existing source under the wire-copy profile."
        if effective_wire
        else effective_wire_error
        or "No alternate existing source passes the saved-effective wire profile.",
        "Open saved wire sources in the recorded diagram and review a separate compiled file. Retained settings are not current live values; no field transfer, new blocks/connections or general compiler is granted.",
    )
    if capability_profile in (PROFILE, CONNECTION_TRANSFER_PROFILE):
        add(
            "matching-connection-copy",
            "Save a matching native connection archive copy",
            "source-qualified" if connection_copy else "unsupported-source",
            "An actual recorded prototype has a matching observed source and unused compatible input under the connection-copy profile."
            if connection_copy
            else connection_copy_error
            or "No existing-member connection passes this archive's prototype, pin, input ownership, order, cycle and tag profile.",
            "Inspect the recorded diagram, choose Add matching connection and Original archive, then review a separate file. Review still checks final output size and exact native readback. No new blocks/I/O, field transfer or physical acceptance is granted.",
        )
        add(
            "effective-connection-compile",
            "Compile a matching saved-effective native connection",
            "source-qualified" if effective_connection else "unsupported-source",
            "The identity-qualified retained saved merge preserves graph/continuation structure and admits an actual matching existing-member connection."
            if effective_connection
            else effective_connection_error
            or "No existing-member connection passes the saved-effective connection profile.",
            "Choose Add matching connection and Saved effective snapshot in the recorded diagram. Review a separate compiled file with final size/readback checks. Captured settings are not current live values; no fresh-setting guarantee, new blocks/I/O or field transfer is prepared.",
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
        "effective-enum-compile",
        "Compile an effective native Enum default",
        "source-qualified" if effective_enums else "unsupported-source",
        f"The saved-setting compiler qualified {len(effective_enums)} existing Enum defaults and the retained Device identity; {fixed_enums} have captured fixed numeric storage. Code membership and state meanings remain unverified."
        if effective_enums
        else effective_enum_error or "No supported effective Enum defaults were found.",
        "Inspect the actual Enum record, select Merge retained saved settings and review/save a local compiled copy. Captured storage bounds are not allowed-state tables; without a selected fixed slot only UInt32 representation is checked. No Enum field transfer is prepared.",
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
        "enum-default-transfer",
        "Transfer one effective native Enum code",
        *transfer_status(
            bool(fixed_enums),
            effective_enum_error
            or "No supported effective Enum default has a selected captured fixed Enum slot.",
        ),
        "Use the separate Enum controller review/apply/readback workflow. Check the intended numeric code; membership and meanings remain unverified. Fresh selected-value/storage, other-setting, capacity, credential and one-use checks remain mandatory. Capture/readback use backup-state commands; Apply can interrupt control. This analysis prepares no transfer.",
    )
    add(
        "wire-source-transfer",
        "Transfer an existing native wire source",
        "source-mismatch"
        if not verified
        else "unsupported-source"
        if not effective_wire
        else "preflight-required"
        if plain_ip
        else "transport-unavailable",
        "Retained identity, an effective existing-wire candidate and captured plain IPv4 separately qualify a connected transfer preflight."
        if verified and effective_wire and plain_ip
        else effective_wire_error
        or "A qualified effective wire source and native IPv4 route are required.",
        "Review the exact connected station, original/effective wire and application interruption separately. Fresh graph/source/target configuration, saved settings, capacity, credentials, one-use intent and full native/effective readback remain required. No field action is prepared here.",
    )
    add(
        "general-logic",
        "Compile arbitrary native blocks and wires",
        "unavailable",
        "Installed native compilers cover typed identity, existing Real/Boolean defaults and a scoped existing-wire source archive copy, not arbitrary logic generation.",
        "Retain original bytes; broader writers require independently qualified native references and resource allocation.",
    )
    if capability_profile == CONNECTION_TRANSFER_PROFILE:
        add(
            "matching-connection-transfer",
            "Transfer one matching native connection",
            *transfer_status(
                bool(effective_connection),
                effective_connection_error or "No matching saved-effective connection was found.",
            ),
            "Review the exact station and prototype/source/unused destination separately. Fresh graph/configuration, saved settings, capacity, credentials, one-use intent and full native/effective readback remain required. Backup/readback use backup-state commands; Apply can interrupt control. No new blocks/I/O or automatic inverse deletion; this analysis prepares no field action.",
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
    result = {
        "capability_profile": capability_profile,
        "operations": rows,
        "qualification": {
            "native_identity": native,
            "native_identity_error": native_error,
            "identity_matches_snapshot": bool(matches),
            "recorded_identity_verified": bool(verified),
            "captured_plain_ipv4": bool(plain_ip),
            "archive_real_default_count": defaults,
            "archive_boolean_default_count": boolean_count,
            "archive_enum_default_count": enum_count,
            "archive_enum_default_error": enum_error,
            "enum_semantics_verified": False,
            "archive_wire_source_copy": wire_copy,
            "archive_wire_source_copy_error": wire_copy_error,
            "effective_wire_source_compilation": effective_wire,
            "effective_wire_source_compilation_error": effective_wire_error,
            "effective_boolean_default_count": len(effective_booleans),
            "effective_enum_default_count": len(effective_enums),
            "effective_enum_default_error": effective_enum_error,
            "effective_enum_fixed_storage_count": fixed_enums,
            "effective_enum_unknown_storage_count": len(effective_enums) - fixed_enums,
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
    if capability_profile in (PROFILE, CONNECTION_TRANSFER_PROFILE):
        result["qualification"].update(
            archive_matching_connection=connection_copy,
            archive_matching_connection_error=connection_copy_error,
            effective_matching_connection=effective_connection,
            effective_matching_connection_error=effective_connection_error,
        )
        next(row for row in rows if row["id"] == "general-logic")["basis"] = (
            "Installed compilers cover typed identity/defaults and scoped existing-member wire source or matching connection copies, including separately qualified retained saved merges. Arbitrary blocks, hardware allocation and general native logic remain unavailable."
        )
    return result
