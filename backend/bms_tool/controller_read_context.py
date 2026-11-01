"""Optional selected-controller binding for legacy read-only acquisition APIs."""

from __future__ import annotations

import json

from pydantic import model_serializer, model_validator

from .hardware_target import HardwareTargetRequest, serial_identity
from .models import StrictModel


class AcquisitionTargetRequest(HardwareTargetRequest):
    @model_serializer(mode="wrap")
    def legacy_ip_shape(self, handler):
        data = handler(self)
        if self.transport == "bacnet-ip":
            data.pop("transport", None)
        return data


class ControllerReadContext(StrictModel):
    controller_target: AcquisitionTargetRequest | None = None
    expected_connector_config: dict | None = None

    @model_validator(mode="after")
    def paired_context(self):
        if (self.controller_target is None) != (self.expected_connector_config is None):
            raise ValueError("Selected-controller reads require both target and connector context.")
        if self.expected_connector_config is not None:
            try:
                raw = json.dumps(self.expected_connector_config, allow_nan=False)
            except (ValueError, TypeError, RecursionError) as exc:
                raise ValueError("Invalid selected-controller connector context.") from exc
            if len(raw.encode("utf-8")) > 8192 or len(self.expected_connector_config) > 64:
                raise ValueError("Selected-controller connector context exceeds its bound.")
        return self

    @model_serializer(mode="wrap")
    def legacy_shape(self, handler):
        data = handler(self)
        if self.controller_target is None:
            data.pop("controller_target", None)
            data.pop("expected_connector_config", None)
        return data


def selected_address(address, target):
    candidate = type(target)(**(target.model_dump() | {"address": address}))
    if candidate.address != target.address:
        raise ValueError("The acquisition address differs from the selected controller.")
    return target.address


def check_connector_context(request, config):
    if request.controller_target is None:
        return
    if config != request.expected_connector_config:
        raise ValueError("The selected controller interface changed; reopen the controller.")
    if config is None:
        raise ValueError("Open the selected controller's matching interface first.")
    if request.controller_target.transport == "direct-mstp":
        # Python equality alone equates False/0 and 38400.0/38400. Validate
        # the caller's original serial identity with strict native types too.
        serial_identity(request.expected_connector_config, request.controller_target)
        serial_identity(config, request.controller_target)
    elif config.get("transport") == "mstp":
        raise ValueError("Selected serial acquisition requires an explicit direct-MS/TP target.")
