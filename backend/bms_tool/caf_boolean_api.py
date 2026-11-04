"""Separate local-only route family for the recorded Boolean constant profile."""

from .caf_boolean_copy import CafBooleanCopies
from .caf_constant_api import constant_router


def boolean_constant_router(get_caf):
    return constant_router(get_caf, compiler=CafBooleanCopies, suffix="boolean-constant-copy")
