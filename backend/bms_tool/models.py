"""Versioned, vendor-neutral graph representation. No executable code in projects."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Node(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_\-]{0,79}$")
    kind: str
    label: str = Field(default="", max_length=200)
    x: float = 0.0
    y: float = 0.0
    params: dict[str, Any] = Field(default_factory=dict)
    unit: str = ""
    value_type: Literal["number", "boolean"] = "number"

    @field_validator("params")
    @classmethod
    def finite_parameters(cls, value):
        json.dumps(value, allow_nan=False)
        return value


class Edge(StrictModel):
    id: str
    source: str
    target: str
    source_port: str = "out"
    target_port: str = "in"


class Target(StrictModel):
    family: str = "universal-runtime"
    model: str = ""
    firmware: str = ""
    release_mode: str = ""
    max_nodes: int = Field(default=2000, ge=1, le=20000)
    physical_inputs: int | None = Field(default=None, ge=0)
    physical_outputs: int | None = Field(default=None, ge=0)


class Program(StrictModel):
    schema_version: Literal[1] = 1
    id: str = Field(default="untitled", pattern=r"^[A-Za-z0-9_\-]{1,80}$")
    name: str = Field(default="Untitled program", min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)
    revision: int = Field(default=0, ge=0)
    scan_seconds: float = Field(default=1.0, ge=0.01, le=60)
    target: Target = Field(default_factory=Target)
    nodes: list[Node] = Field(default_factory=list, max_length=2000)
    edges: list[Edge] = Field(default_factory=list, max_length=10000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def digest(self):
        return hashlib.sha256(canonical(self)).hexdigest()


class Diagnostic(StrictModel):
    level: Literal["error", "warning", "info"]
    code: str
    message: str
    node: str | None = None


def canonical(program: Program) -> bytes:
    return json.dumps(
        program.model_dump(),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ).encode()
