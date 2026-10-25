"""Instance-write admission from retained protocol evidence, never model guesses.

BACnet Device metadata and WriteProperty service support do not establish that
Object_Identifier is writable. A matching explicit permission denial blocks that
method; neither a timeout nor a generic Reject is a permission determination.
"""

IDENTITY_FIELDS = (
    "object-name",
    "vendor-identifier",
    "model-name",
    "firmware-revision",
    "application-software-version",
)


def permission_denied(attempt):
    """Accept only a validated Error reply retained by the commissioning service.

    Older sealed receipts predate structured error fields. Their exact native
    error text is recognized without rewriting those immutable records.
    """
    return (
        attempt.get("status") == "rejected"
        and attempt.get("dispatch_started") is True
        and attempt.get("protocol_accepted") is False
        and attempt.get("may_have_applied") is False
        and (
            attempt.get("protocol_error") == {"class": "property", "code": "write-access-denied"}
            or "property: write-access-denied" in attempt.get("errors", [])
        )
    )


def assess_method(identity, denied_attempt=None):
    """Describe this method's evidence separately from allocation/collision checks."""
    assessment = {
        "profile": "bacnet-instance-method/1",
        "method": "standard-bacnet-write-property",
        "state": "unverified",
        "can_attempt": True,
        "reason": (
            "Property write support is unverified. Readable metadata and a clear collision "
            "query do not prove that Device.object-identifier is writable. Apply sends "
            "one attempt and the controller may reject it."
        ),
        "evidence": [],
        "external_transfer_available": False,
        "next_steps": [],
        "sources": [],
    }
    if denied_attempt is None:
        return assessment
    assessment.update(
        state="write_access_denied",
        can_attempt=False,
        reason=(
            "This station with matching controller metadata previously rejected "
            "Device.object-identifier with property: write-access-denied. Another "
            "number or router does not establish permission to repeat this method. "
            "The reply does not identify the controller's internal reason or prove "
            "that this property is permanently read-only."
        ),
        evidence=[
            {
                "kind": "retained-controller-rejection",
                "receipt_id": denied_attempt["id"],
                "observed_at": denied_attempt["finished_at"],
                "evidence_sha256": denied_attempt["evidence_sha256"],
            }
        ],
        next_steps=[
            "Use a manufacturer-supported commissioning procedure for this controller and firmware.",
            "Retain the original application and review supervisor, peer, trend and alarm references before a change.",
            "After external commissioning, use the retained receipt's Read back instance (no write) at its original station.",
        ],
    )
    # A protocol-family adapter is a candidate. A successful capture and strict
    # format/parameter validation decide whether that application can be edited.
    if identity["vendor-identifier"] == 5:
        assessment["native_application_adapter"] = "mce-native-application"
        assessment["next_steps"] = [
            "Choose Connected application transfer in this controller's instance editor.",
            "Read and retain the controller's original application and both saved parameter files. The adapter validates the actual protocol and application format independently of the model name.",
            "Enter the reserved instance, review the application change, and apply the reviewed transfer to this exact physical station.",
            "Verify both the new Device identity and the application readback before starting the observation period.",
        ]
    return assessment
