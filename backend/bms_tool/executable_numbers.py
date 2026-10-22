"""Check executable numbers without changing archival values or source hashes."""

from __future__ import annotations

import math


def require_number(value, label="Number"):
    """Keep finite int/float values, refusing lossy integer-to-binary64 coercion.

    Exactly representable integers above 2**53 remain valid. This does not promise
    exact arithmetic, or equivalence to a target's binary32/fixed-point profile.
    Boolean values belong to a separate execution type.
    """
    if type(value) not in (int, float):
        raise ValueError(f"{label} requires a finite numeric value.")
    try:
        converted = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{label} requires a finite numeric value.") from exc
    if not math.isfinite(converted):
        raise ValueError(f"{label} requires a finite numeric value.")
    if type(value) is int and int(converted) != value:
        raise ValueError(f"{label} requires an exactly representable binary64 integer.")
    return value


def _legacy_source_projection(program):
    """Reconstruct legacy literal coercion only for archival source comparison.

    Old generators coerced these integer parameters while formatting literals.
    This separate copy must never be returned as the imported Program, compiled,
    executed, or used for a new export. The caller restores the original embedded
    document before comparing complete archive source bytes. No Engine is run.
    """
    from .blocks import BLOCKS
    from .macros import MacroLibrary, _load_library

    projected = program.model_copy(deep=True)
    definitions = _load_library(projected) if "macros" in projected.metadata else {}
    # _load_library enforces the existing 4MiB/64-definition/4000-node/depth8
    # limits and forbids nested libraries. Do not walk arbitrary opaque metadata.
    for graph in [projected, *(item.program for item in definitions.values())]:
        for node in graph.nodes:
            spec = BLOCKS.get(node.kind)
            if spec is None:
                continue
            for key, default in spec.parameters.items():
                if type(default) not in (int, float):
                    continue
                if (
                    node.value_type == "boolean"
                    and node.kind in ("Input", "Constant", "Delay")
                    and key in ("value", "default", "initial")
                ):
                    continue
                value = node.params.get(key)
                if type(value) is int:
                    try:
                        converted = float(value)
                    except OverflowError as exc:
                        raise ValueError(
                            "Legacy source parameter exceeds its finite numeric profile."
                        ) from exc
                    if not math.isfinite(converted):
                        raise ValueError(
                            "Legacy source parameter exceeds its finite numeric profile."
                        )
                    if int(converted) != value:
                        node.params[key] = converted
    if definitions:
        projected.metadata["macros"] = MacroLibrary(
            version=1, definitions=list(definitions.values())
        ).model_dump(mode="json")
    return projected
