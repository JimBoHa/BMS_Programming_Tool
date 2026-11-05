"""Separate, local-only HTTP entry points for encoding-preserving terminal copies."""

from .moi_terminal_labels import (
    EFFECTIVE_PROFILE,
    MERGED_SCOPE,
    PROFILE,
    SCOPE,
    EncodedEffectiveTerminalCopies,
    EncodedTerminalCopies,
)
from .native_terminal_copies import (
    EffectiveNativeTerminalCopies,
    NativeTerminalCopies,
    terminal_copy_router,
)

ARCHIVE_PROFILE = "native-archive-local-terminal-copy/2"


class EncodedNativeTerminalCopies(NativeTerminalCopies):
    compiler_type = EncodedTerminalCopies
    profile = ARCHIVE_PROFILE
    compiler_profile = PROFILE
    scope = SCOPE


class EncodedEffectiveNativeTerminalCopies(EffectiveNativeTerminalCopies):
    effective_compiler_type = EncodedEffectiveTerminalCopies
    profile = EFFECTIVE_PROFILE
    compiler_profile = PROFILE
    scope = MERGED_SCOPE


def terminal_label_router(records):
    # Reuse every strict request model, review/export check and download header.
    return terminal_copy_router(
        EncodedNativeTerminalCopies(records),
        EncodedEffectiveNativeTerminalCopies(records),
        encoded_labels=True,
    )
