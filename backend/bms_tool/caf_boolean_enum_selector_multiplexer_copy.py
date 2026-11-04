"""Separate recorded Boolean I/O / Enum selector profile; no Enum meaning inferred."""

from .caf_boolean_multiplexer_copy import CafBooleanMultiplexerCopies
from .caf_constant_copy import ConstantProfile

PROFILE = "caf-recorded-boolean-enum-selector-multiplexer-copy/1"
SCOPE = (
    "One unconnected local Boolean Multiplexer with an Enum selector and four recorded "
    "ports copied from version 1.0 source configuration. Raw selector metadata, "
    "bookkeeping, exact Boolean default spelling, omitted values/setup and order stay "
    "recorded. Native Enum membership, mode assignments/fallback, runtime, controller "
    "allocation, resources, CCT/PCT acceptance and transfer are unverified."
)


class CafBooleanEnumSelectorMultiplexerCopies(CafBooleanMultiplexerCopies):
    spec = ConstantProfile(
        PROFILE,
        SCOPE,
        "Boolean Multiplexer with Enum selector",
        "562",
        "531",
        5,
        frozenset({"19"}),
        "boolean",
        (frozenset({"75", "32527", "3365"}),),
    )
    enum_selector = True
    configurations = frozenset(
        {
            (("1", "2"), "0", 2, 350),
            (("1", "0", "0", "0", "0"), "2", 5, 1347),
            (("0", "0", "0", "2", "0"), "1", 5, 359),
        }
    )
