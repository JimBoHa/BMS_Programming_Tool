"""Source-bound application acquisition with replaceable native format readers."""

from __future__ import annotations

import asyncio
from collections import OrderedDict

from bacpypes3.primitivedata import ObjectIdentifier
from pydantic import Field, field_validator

from .device_details import DeviceDetails, DeviceDetailsRequest
from .moi_application import MoiApplication


class ApplicationReadRequest(DeviceDetailsRequest):
    file_object: str | None = Field(default=None, max_length=80)

    @field_validator("file_object")
    @classmethod
    def actual_file(cls, value):
        if value is not None:
            oid = ObjectIdentifier(value)
            if int(oid[0]) != 10 or not 0 <= oid[1] <= 4194302:
                raise ValueError("Select an actual File object.")
            return str(oid)
        return None


class ApplicationCaptureRequest(DeviceDetailsRequest):
    capture_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class ApplicationDiagramRequest(ApplicationCaptureRequest):
    ref: str = Field(min_length=1, max_length=512)


class ControllerApplication:
    id = "bacnet-file-application"

    def __init__(self, bacnet, store, files, *, formats=(MoiApplication,)):
        self.bacnet, self.files = bacnet, files
        self.path = DeviceDetails(bacnet, store)
        self.formats = formats
        self.cache = OrderedDict()

    def capabilities(self, profile):
        # Candidate transport/format support is not proof of a readable program.
        services = profile.get("properties", {}).get("protocol-services-supported", {}).get("value")
        if not isinstance(services, list) or len(services) <= 6 or not services[6]:
            return None
        return {
            "logic_read": False,
            "file_read": True,
            "formats": [kind.format for kind in self.formats],
            "requires": "An existing readable application File with a recognized native format.",
        }

    @staticmethod
    def _target(options):
        return options.model_dump(include={"address", "device", "router", "dnet"})

    def _matches(self, receipt, options):
        target, config = receipt["target"], receipt["connector_config"]
        return (
            target["address"] == options.address
            and target["device"] == options.device
            and config == self.bacnet.config
            and (
                options.router is None
                or (config.get("router") == options.router and config.get("dnet") == options.dnet)
            )
        )

    def _supported(self, metadata):
        return any(metadata["file_type"].lower() in reader.extensions for reader in self.formats)

    def _application(self, receipt, data):
        key = receipt["sha256"]
        if key not in self.cache:
            failures = []
            for reader in self.formats:
                try:
                    self.cache[key] = reader(data)
                    break
                except ValueError as failure:
                    failures.append(str(failure))
            else:
                raise ValueError(
                    "No installed reader recognized this actual controller file. "
                    + " ".join(failures)
                )
            while len(self.cache) > 4:
                self.cache.popitem(last=False)
        return self.cache[key]

    def capture(self, request):
        options = ApplicationCaptureRequest.model_validate(request)
        receipt, data = self.files.capture_data(options.capture_id)
        if not self._matches(receipt, options):
            raise ValueError(
                "The application capture belongs to a different controller route or interface."
            )
        application = self._application(receipt, data)
        return {
            "target": self._target(options),
            "connector_config": receipt["connector_config"],
            "receipt": receipt,
            "application": application.summary(),
            "source_kind": "controller-file-capture",
            "read_only": True,
            "identity_verified": False,
            "status": "recorded",
        }

    def captures(self, request):
        options = DeviceDetailsRequest.model_validate(request)
        result = []
        for row in self.files.captures():
            receipt = self.files.capture(row["id"])
            if self._matches(receipt, options) and self._supported(receipt["metadata"]):
                result.append(row)
        return sorted(result, key=lambda row: row["received_at"], reverse=True)

    def diagram(self, request):
        options = ApplicationDiagramRequest.model_validate(request)
        receipt, data = self.files.capture_data(options.capture_id)
        if not self._matches(receipt, options):
            raise ValueError(
                "The native diagram belongs to a different controller route or interface."
            )
        return {
            "target": self._target(options),
            "capture_id": options.capture_id,
            "diagram": self._application(receipt, data).diagram(options.ref),
            "sha256": receipt["sha256"],
            "read_only": True,
        }

    async def read_application(self, target, profile=None, *, file_object=None):
        options = ApplicationReadRequest.model_validate({**target, "file_object": file_object})
        async with asyncio.timeout(245):
            async with self.path._path(options):
                if options.router is not None and (
                    self.bacnet.config.get("router") != options.router
                    or self.bacnet.config.get("dnet") != options.dnet
                ):
                    raise ValueError(
                        "Open the selected controller's exact routed interface before reading its application."
                    )
                inspection = await self.files.inspect_config(
                    options.address, options.device, lock_held=True
                )
                candidates = [
                    row
                    for row in inspection["files"]
                    if row["read_supported"] and self._supported(row)
                ]
                if file_object is not None:
                    candidates = [
                        row for row in candidates if row["object_id"] == options.file_object
                    ]
                if len(candidates) != 1:
                    return {
                        "target": self._target(options),
                        "status": "select_application" if candidates else "format_unavailable",
                        "files": candidates,
                        "read_only": True,
                        "identity_verified": False,
                        "message": "Select a published application file."
                        if candidates
                        else "No readable application File matches an installed format reader. Standard point and configuration reads remain available.",
                    }
                selected = candidates[0]
                receipt = await self.files.read_raw_file(
                    inspection["id"],
                    selected["object_id"],
                    selected["metadata_sha256"],
                    lock_held=True,
                )
        result = await asyncio.to_thread(
            self.capture, {**self._target(options), "capture_id": receipt["id"]}
        )
        result.update(status="read", identity_verified=True)
        return result
