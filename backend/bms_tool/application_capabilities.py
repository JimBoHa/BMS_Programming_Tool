"""Operation support from actual captured bytes; no field or vendor-tool actions."""

from .moi_identity import MoiIdentity
from .moi_signal_defaults import MoiSignalDefaults

PROFILE = "controller-application-operation-capabilities/1"


def operation_capabilities(receipt, data, application):
    identity = receipt["device_identity"]
    config = receipt["connector_config"]
    native, parse_error = None, None
    try:
        native = MoiIdentity(data).summary()
    except ValueError as exc:
        parse_error = str(exc)[:256]
    plain_ip = config.get("transport") is None and not config.get("bbmd_address")
    matches = bool(native) and (
        identity.get("object-identifier") == f"device,{native['instance']}"
        and identity.get("object-name") == native["name"]
        and identity.get("model-name") == native["model"]
    )
    family = identity.get("vendor-identifier") == 5
    rows = []

    def add(key, operation, status, basis, next_step):
        rows.append(
            {
                "id": key,
                "operation": operation,
                "status": status,
                "basis": basis,
                "next_step": next_step,
            }
        )

    add(
        "file-read",
        "Read published application File",
        "observed",
        "A complete retained File capture supplies these bytes.",
        "Read controller application to acquire a later snapshot.",
    )
    add(
        "diagram-read",
        "Inspect blocks and wires",
        "source-qualified" if application["capabilities"]["logic_read"] else "unavailable",
        "The installed reader recognized recorded diagrams."
        if application["capabilities"]["logic_read"]
        else "This source has no complete diagram recognized by the installed reader.",
        "Inspect recorded properties and retain unrecognized details.",
    )
    add(
        "identity-compile",
        "Edit and compile Device instance",
        "source-qualified" if native else "unsupported-source",
        "The typed identity compiler recognizes this exact source." if native else parse_error,
        "Overview → Edit instance number: acquire a native backup and review the exact proposed change.",
    )
    name_supported = native is not None and isinstance(native["name"], str)
    add(
        "name-compile",
        "Edit and compile controller name",
        "source-qualified" if name_supported else "unsupported-source",
        "The source exposes a typed root Device name."
        if name_supported
        else parse_error or "No typed root Device name was found.",
        "Overview → Edit controller name: native backup, exact name/encoding review and confirmation are required.",
    )
    if not plain_ip:
        status, basis = (
            "transport-unavailable",
            "Connected native transfer currently requires plain direct or routed BACnet/IPv4; this capture used another interface profile.",
        )
    elif not family:
        status, basis = (
            "protocol-unconfirmed",
            "The captured vendor identity does not establish the installed vendor-5 native service family.",
        )
    elif not native:
        status, basis = "unsupported-source", parse_error
    elif not matches:
        status, basis = (
            "source-mismatch",
            "The native root instance, name or model differs from the captured Device identity.",
        )
    else:
        status, basis = (
            "preflight-required",
            "Captured identity and typed source agree; the installed connected adapter still requires its native protocol and saved-parameter preflight.",
        )
    add(
        "identity-transfer",
        "Transfer reviewed instance or name change",
        status,
        basis,
        "Use the separate Overview commissioning workflow: native credentials, fresh backup/parameter layout, capacity, one-use review and exact readback remain required. Backup and readback use backup-state commands.",
    )
    try:
        defaults = MoiSignalDefaults(data).capabilities()
        eligible = defaults["available"]
        default_basis = (
            f"This source contains {defaults['candidate_count']} recognized existing Real defaults."
            if eligible
            else "This source contains no supported existing Real default fields."
        )
    except ValueError as exc:
        eligible, default_basis = False, str(exc)[:256]
    add(
        "signal-default-copy",
        "Review and save a native Real-default file copy",
        "source-qualified" if eligible else "unsupported-source",
        default_basis,
        "Select the actual captured field. The local file-copy review changes one known Real payload and performs no controller transfer.",
    )
    effective_status = (
        "unsupported-source"
        if not eligible
        else "protocol-unconfirmed"
        if not family
        else "source-mismatch"
        if not matches
        else "native-backup-required"
    )
    add(
        "effective-default-compile",
        "Compile an effective Real default from native saved settings",
        effective_status,
        default_basis + " A published File capture does not supply verified native Files 3/11/12.",
        "Program → Native backup defaults opens a separate identity-verified native snapshot, merges saved application values and reviews a local compiled copy. Current interface transport does not restrict offline snapshot compilation.",
    )
    add(
        "default-transfer",
        "Transfer one reviewed effective native default",
        status if eligible else "unsupported-source",
        basis if eligible else default_basis,
        "Program → Native backup defaults requires its own native backup, fresh selected-value guard, other-setting preservation, capacity, one-use operation review and full native/effective-setting readback. No transfer is prepared by this capture analysis.",
    )
    add(
        "general-logic",
        "Edit/compile arbitrary native blocks and wires",
        "unavailable",
        "The reader and typed identity/default compilers do not generate arbitrary controller logic.",
        "Retain the original source; a separately qualified logic writer and native resource contract are required.",
    )
    add(
        "release-packages",
        "Verify package and destination release compatibility",
        "not-evaluated",
        "Captured firmware and native ACS/DMCS codes are evidence in distinct namespaces, not a compatibility table.",
        "Use the existing offline CAF target/toolchain preflight for declared package/release evidence; it does not certify this controller transfer.",
    )
    add(
        "physical-acceptance",
        "Establish physical controller acceptance",
        "not-inferred",
        "Reading or recognizing this file does not establish application transfer, restart or hardware acceptance.",
        "Retain each actual transfer/readback result and its exact target separately; no physical qualification is inferred here.",
    )
    return {
        "profile": PROFILE,
        "source": {
            "capture_id": receipt["id"],
            "sha256": receipt["sha256"],
            "received_at": receipt["received_at"],
            "target": receipt["target"],
            "connector_config": config,
            "device_identity": identity,
            "format": application["format"],
        },
        "native_identity": native,
        "native_identity_matches_capture": bool(matches),
        "operations": rows,
        "can_apply": False,
        "field_actions": False,
        "scope": "Local analysis of one retained controller File capture. Source-qualified means recognized by installed software, not a prepared write or physical acceptance. No protocol probe, compilation intent or transfer is performed.",
    }
