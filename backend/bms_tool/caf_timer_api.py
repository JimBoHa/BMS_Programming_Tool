"""Separate local-only eight-object recorded Timer route family."""

from .caf_constant_api import constant_router
from .caf_timer_copy import CafTimerCopies


def timer_router(get_caf):
    return constant_router(get_caf, compiler=CafTimerCopies, suffix="timer-copy")
