"""Separate local-only five-object Comparison template route family."""

from .caf_comparison_service import CafComparisonService
from .caf_constant_api import constant_router


def comparison_router(get_caf):
    return constant_router(get_caf, compiler=CafComparisonService, suffix="comparison-copy")
