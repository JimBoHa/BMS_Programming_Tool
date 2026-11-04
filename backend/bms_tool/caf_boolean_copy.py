"""Observed Boolean constant/output schema using the shared local CAF writer."""

from .caf_constant_copy import CafConstantCopies, ConstantProfile

PROFILE = "caf-recorded-boolean-constant-copy/1"
SCOPE = (
    "One unconnected local Boolean Constant and its required output object copied from "
    "recorded version 1.0 configuration. Recorded standard name and Boolean value are retained. "
    "Controller allocation, resources, CCT/PCT acceptance and field transfer are unverified."
)


class CafBooleanCopies(CafConstantCopies):
    spec = ConstantProfile(
        PROFILE,
        SCOPE,
        "Boolean Constant",
        "552",
        "531",
        5,
        frozenset({"13"}),
        "boolean",
        (frozenset({"75", "32527", "3113", "3365"}),),
    )
