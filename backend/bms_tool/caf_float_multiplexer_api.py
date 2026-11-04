"""Separate local-only recorded Float Multiplexer route family."""

from .caf_constant_api import constant_router
from .caf_float_multiplexer_service import CafFloatMultiplexerService


def float_multiplexer_router(get_caf):
    return constant_router(
        get_caf, compiler=CafFloatMultiplexerService, suffix="float-multiplexer-copy"
    )
