"""One-property opt-in observations around the unchanged Schedule inventory read."""

from typing import Literal

from bacpypes3.primitivedata import ObjectIdentifier
from pydantic import Field, field_validator, model_validator

from .models import StrictModel
from .schedule_inventory import ScheduleReadRequest


class ScheduleTraceFocus(StrictModel):
    object_id: str
    property: Literal[
        "object-identifier",
        "object-name",
        "description",
        "present-value",
        "date-list",
        "effective-period",
        "schedule-default",
        "priority-for-writing",
        "list-of-object-property-references",
        "status-flags",
        "reliability",
        "out-of-service",
        "weekly-schedule",
        "exception-schedule",
    ]
    array_index: int | None = Field(default=None, ge=0, le=32, strict=True)

    @field_validator("object_id")
    @classmethod
    def object(cls, value):
        return ScheduleReadRequest.schedule_types([value])[0]

    @model_validator(mode="after")
    def property_reference(self):
        kind = int(ObjectIdentifier(self.object_id)[0])
        common = {"object-identifier", "object-name", "description", "present-value"}
        if kind == 6 and self.property not in common | {"date-list"}:
            raise ValueError("Select a property read by the Calendar inventory.")
        if kind == 17 and self.property == "date-list":
            raise ValueError("Date_List belongs to a Calendar, not a Schedule.")
        if self.property in ("weekly-schedule", "exception-schedule"):
            if self.array_index is None or (
                self.property == "weekly-schedule" and self.array_index > 7
            ):
                raise ValueError("Select one existing bounded array count/element index.")
        elif self.array_index is not None:
            raise ValueError("This inventory property is read without an array index.")
        return self

    def reference(self):
        return self.object_id, self.property, self.array_index


class ScheduleDiagnosticRequest(StrictModel):
    request: ScheduleReadRequest
    trace_focus: ScheduleTraceFocus

    @model_validator(mode="after")
    def explicit_selection(self):
        if not self.request.object_ids or self.trace_focus.object_id not in self.request.object_ids:
            raise ValueError("Explicitly select the traced Calendar/Schedule in this read.")
        return self
