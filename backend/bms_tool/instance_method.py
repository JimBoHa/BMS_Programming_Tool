"""Instance-write admission from retained protocol evidence, never model guesses.

BACnet Device metadata and WriteProperty service support do not establish that
Object_Identifier is writable. A matching explicit permission denial blocks that
method; neither a timeout nor a generic Reject is a permission determination.
"""

import re

CCT_SOURCE = (
    "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/15.0/"
    "Working-with-the-Trunk-Utilities/Working-with-the-Trunk-Utilities-Steps/"
    "Reading-and-Writing-Attributes-Online"
)
CCT_SETTINGS = (
    "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/16.0/"
    "Defining-Hardware/Hardware-Definition-Tabs/Network-Settings-Tab"
)
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
    # Guidance only: this family match NEVER authorizes or blocks a field write.
    # Other vendors/models get the same evidence-based permission assessment.
    if identity["vendor-identifier"] == 5 and re.fullmatch(
        r"(?:MS-(?:VMA|FEC|IOM)|FX-PC[AGVX])[0-9]+-[A-Za-z0-9]+", identity["model-name"]
    ):
        assessment["next_steps"] = [
            "Use a licensed, compatible CCT/PCT environment and controller package. Obtain and retain a verified original CAF; a BACnet File capture is not a full CAF backup.",
            "In the manufacturer's tool, select this exact router, network and MAC. Resolve any duplicate-ID selection limitation before a transfer; do not select by instance alone.",
            "Set Instance Number (BACnet ID) in Define Hardware > Network Settings and review Transfer to Device. Johnson Controls documents that the name and instance are written during transfer, not Read/Write Attributes Online.",
            "A transfer can replace the running application. Review its contents, controller compatibility, interruption and dependent references before executing it outside this app.",
            "Return to this receipt and choose Read back instance (no write). A verified new identity at this station is required before starting the observation period.",
        ]
        assessment["sources"] = [
            {"title": "Johnson Controls: Reading and Writing Attributes Online", "url": CCT_SOURCE},
            {"title": "Johnson Controls: Network Settings Tab", "url": CCT_SETTINGS},
        ]
    return assessment
