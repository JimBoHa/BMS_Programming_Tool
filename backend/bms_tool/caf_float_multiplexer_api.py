"""Source-typed Multiplexer profiles; retain the original route for compatibility."""

from .caf_constant_api import constant_router
from .caf_enum_multiplexer_copy import PROFILE as ENUM_PROFILE
from .caf_float_multiplexer_service import CafFloatMultiplexerService


def float_multiplexer_router(get_caf):
    return constant_router(
        get_caf,
        compiler=CafFloatMultiplexerService,
        suffix="float-multiplexer-copy",
        artifact_suffix=lambda selection: (
            "enum-multiplexer-copy"
            if selection["profile"] == ENUM_PROFILE
            else "float-multiplexer-copy"
        ),
    )
