"""Offline CAF comparison against integrity-checked published BACnet File captures."""

from bacpypes3.primitivedata import ObjectIdentifier
from pydantic import Field

from .bacnet_files import MAX_CAPTURES
from .caf_native_correlation import (
    compare_archives,
    correlation_identity,
    recorded_identity_agrees,
)
from .models import StrictModel
from .moi_identity import seal

PROFILE = "caf-native-file-source-correlation/1"
SOURCE_PROFILE = "retained-native-file-comparison-source/1"
CATALOG_PROFILE = "caf-native-file-comparison-sources/1"
SCOPE = (
    "Compare the original opened CAF with the actual recognized native bytes of one retained "
    "BACnet File capture. Literal Device/record identities and recorded device agreement only. "
    "This File capture has no paired saved-setting files and does not verify a coherent "
    "native backup or current program. No compiler compatibility, application association "
    "or field action is granted."
)


class CafNativeFileCorrelationRequest(StrictModel):
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    capture_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    query: str = Field(default="", max_length=256, strict=True)
    offset: int = Field(default=0, ge=0, le=40000, strict=True)
    limit: int = Field(default=64, ge=1, le=128, strict=True)


def file_source(receipt):
    config, original = receipt["connector_config"], receipt["target"]
    # Archive comparison retains the recorded route, including serial/legacy
    # interfaces. A current network-connection DTO must not gate offline reading.
    router, dnet = config.get("router"), config.get("dnet")
    if (router is not None and not isinstance(router, str)) or (
        dnet is not None and (type(dnet) is not int or not 0 <= dnet <= 65535)
    ):
        raise ValueError("Retained File route evidence has an invalid type.")
    target = {
        "address": original["address"],
        "device": original["device"],
        "router": router,
        "dnet": dnet,
    }
    device = ObjectIdentifier(original["device"])
    if int(device[0]) != 8 or not 0 <= int(device[1]) <= 4194302:
        raise ValueError("Retained File comparison requires an actual Device identity.")
    obj = ObjectIdentifier(original["object_id"])
    if int(obj[0]) != 10 or not 0 <= int(obj[1]) <= 4194302:
        raise ValueError("Retained native File comparison requires an actual File object.")
    return {
        "profile": SOURCE_PROFILE,
        "source_kind": "controller-file-capture",
        "capture_id": receipt["id"],
        "receipt_sha256": seal(receipt),
        "sha256": receipt["sha256"],
        "bytes": receipt["bytes"],
        "target": target,
        "file_object": original["object_id"],
        "captured_at": receipt["received_at"],
        "read_started_at": receipt["read_at"],
        "identity": receipt["device_identity"],
        "metadata": receipt["metadata"],
        "connector_sha256": seal(config),
        "consistency": receipt["consistency"],
        "read_only": True,
        "controller_queries": False,
        "field_actions": False,
        "identity_verified": False,
        "full_native_backup": False,
        "saved_settings_available": False,
    }


class NativeFileCorrelation:
    def __init__(self, files):
        self.files = files

    def sources(self):
        sources = []
        for item in self.files.captures():
            # The existing loader validates the wrapper checksum, full payload,
            # target metadata and stream/record boundaries without field access.
            receipt, _ = self.files.capture_data(item["id"])
            source = file_source(receipt)
            sources.append(
                {
                    key: source[key]
                    for key in (
                        "capture_id",
                        "receipt_sha256",
                        "sha256",
                        "bytes",
                        "target",
                        "file_object",
                        "captured_at",
                        "identity",
                        "connector_sha256",
                    )
                }
                | {"format_hint": receipt["metadata"].get("file_type")}
            )
        return {
            "profile": CATALOG_PROFILE,
            "scope": "Retained File candidates; actual native content is checked on comparison.",
            "sources": sorted(sources, key=lambda row: row["captured_at"], reverse=True),
            "source_limit": MAX_CAPTURES,
            "read_only": True,
            "controller_queries": False,
            "field_actions": False,
        }

    def compare(self, caf, request):
        options = CafNativeFileCorrelationRequest.model_validate(request)
        if caf.hash != options.source_sha256:
            raise ValueError("The opened CAF changed; compare its original source again.")
        receipt, data = self.files.capture_data(options.capture_id)
        source = file_source(receipt)
        if (
            source["receipt_sha256"] != options.receipt_sha256
            or source["sha256"] != options.file_sha256
        ):
            raise ValueError("The retained File receipt or payload changed; refresh its source.")
        identity, summary = correlation_identity(data)
        agrees = receipt["device_identity"].get("object-identifier") == source["target"][
            "device"
        ] and recorded_identity_agrees(
            source["target"]["device"], receipt["device_identity"], summary
        )
        return compare_archives(
            caf,
            identity,
            summary,
            options,
            profile=PROFILE,
            scope=SCOPE,
            source_field="native_file",
            source=source,
            identity_field="recorded_device_identity_agrees",
            identity_agrees=agrees,
        )
