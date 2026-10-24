"""Explicit hardware-survey targets; serial capability does not widen other APIs."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, model_validator

from .device_details import DeviceDetailsRequest
from .models import StrictModel
from .mstp import MstpMaster


class HardwareTargetRequest(DeviceDetailsRequest):
    transport: Literal["bacnet-ip", "direct-mstp"] = "bacnet-ip"

    @model_validator(mode="after")
    def exact_destination(self):
        if self.transport == "bacnet-ip":
            return super().exact_destination()
        if self.router is not None or self.dnet is not None:
            raise ValueError("Direct MS/TP hardware targets cannot specify an IP router or DNET.")
        if not re.fullmatch(r"(?:0|[1-9][0-9]{0,2})", self.address) or int(self.address) > 254:
            raise ValueError(
                "Direct MS/TP hardware targets require a canonical decimal remote MAC in 0..254."
            )
        return self


class SerialInterfaceIdentity(StrictModel):
    transport: Literal["mstp"]
    port: str = Field(min_length=1, max_length=256)
    mac: int = Field(ge=0, le=127, strict=True)
    instance: int = Field(ge=0, le=4194302, strict=True)
    baudrate: int = Field(strict=True)
    max_master: int = Field(ge=0, le=127, strict=True)
    max_info_frames: int = Field(ge=1, le=255, strict=True)

    @model_validator(mode="after")
    def valid_master(self):
        MstpMaster(
            self.mac,
            baudrate=self.baudrate,
            max_master=self.max_master,
            max_info_frames=self.max_info_frames,
        )
        if any(ord(char) < 32 for char in self.port):
            raise ValueError("Serial interface identity requires a plain device path.")
        return self


def serial_identity(config, target):
    identity = SerialInterfaceIdentity.model_validate(config).model_dump()
    if int(target.address) == identity["mac"]:
        raise ValueError("Select a remote MS/TP MAC, not this interface's own station.")
    return identity
