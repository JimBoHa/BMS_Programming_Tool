"""Separate local route family for recorded Enumeration Constant creation."""

from .caf_constant_api import constant_router
from .caf_enum_copy import CafEnumCopies


def enum_constant_router(get_caf):
    return constant_router(get_caf, compiler=CafEnumCopies, suffix="enum-constant-copy")
