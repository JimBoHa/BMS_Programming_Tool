"""Separate local-only recorded Math template route family."""

from .caf_constant_api import constant_router
from .caf_math_copy import CafMathCopies


def math_router(get_caf):
    return constant_router(get_caf, compiler=CafMathCopies, suffix="math-copy")
