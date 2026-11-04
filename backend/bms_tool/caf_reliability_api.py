"""Separate local-only recorded Reliability Check route family."""

from .caf_constant_api import constant_router
from .caf_reliability_copy import CafReliabilityCopies


def reliability_router(get_caf):
    return constant_router(get_caf, compiler=CafReliabilityCopies, suffix="reliability-copy")
