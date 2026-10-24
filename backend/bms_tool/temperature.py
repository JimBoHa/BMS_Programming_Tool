"""Explicit absolute/difference temperature contracts; not dimensional algebra.

Existing arbitrary engineering-unit strings and legacy math semantics are kept.
Only the new quantity blocks apply these port-specific contracts.
"""

ABSOLUTE_UNITS = ("degF", "degC", "K")
DELTA_FOR_ABSOLUTE = {"degF": "delta-degF", "degC": "delta-degC", "K": "delta-K"}
DELTA_UNITS = tuple(DELTA_FOR_ABSOLUTE.values())
TEMPERATURE_BLOCKS = frozenset({"TemperatureDifference", "DeltaConvert", "TemperatureOffset"})


def input_units(kind, params, output_unit):
    """Validate a quantity block and return exact required input unit tokens."""
    if kind == "DeltaConvert":
        source, target = params["from"], params["to"]
        if source not in DELTA_UNITS or target not in DELTA_UNITS:
            raise ValueError("Difference conversion requires delta-degF, delta-degC or delta-K.")
        expected = target
        required = {"in": source}
    else:
        absolute = params["unit"]
        if absolute not in ABSOLUTE_UNITS:
            raise ValueError("Absolute temperature unit must be degF, degC or K.")
        if kind == "TemperatureDifference":
            expected = DELTA_FOR_ABSOLUTE[absolute]
            required = {"a": absolute, "b": absolute}
        elif kind == "TemperatureOffset":
            difference = params["difference_unit"]
            if difference not in DELTA_UNITS:
                raise ValueError("Temperature offset requires an explicit delta temperature unit.")
            expected = absolute
            required = {"base": absolute, "difference": difference}
        else:
            raise ValueError("Unknown temperature quantity block.")
    if output_unit != expected:
        raise ValueError(f"Output unit must be {expected} for this temperature quantity.")
    return required


def delta_ratio(source, target):
    """Return exact small integer scale factors; temperature differences have no offset."""
    if source not in DELTA_UNITS or target not in DELTA_UNITS:
        raise ValueError("Difference conversion requires explicit delta temperature units.")
    if source == "delta-degF" and target != "delta-degF":
        return 5, 9
    if target == "delta-degF" and source != "delta-degF":
        return 9, 5
    return 1, 1


def convert_difference(value, source, target):
    numerator, denominator = delta_ratio(source, target)
    return value if numerator == denominator else value / denominator * numerator


def difference_expression(expression, source, target, *, real_literals=True):
    """Lower the same quantity contract to explicit arithmetic target syntax."""
    numerator, denominator = delta_ratio(source, target)
    if numerator == denominator:
        return expression
    suffix = ".0" if real_literals else ""
    return f"({expression} / {denominator}{suffix} * {numerator}{suffix})"
