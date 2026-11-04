"""Separate local-only recorded Boolean logic route family."""

from .caf_boolean_logic_copy import CafBooleanLogicCopies
from .caf_constant_api import constant_router


def boolean_logic_router(get_caf):
    return constant_router(get_caf, compiler=CafBooleanLogicCopies, suffix="boolean-logic-copy")
