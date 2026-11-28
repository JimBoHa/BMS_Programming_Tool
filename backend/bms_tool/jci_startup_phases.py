"""Decode a Johnson Controls Device Startup Phase Diagnostic from BACnet property tags."""

from bacpypes3.primitivedata import TagClass

PHASE_NAMES = (
    "Cold Start",
    "Warm Start",
    "Startup",
    "Start Inputs",
    "Enable Communications",
    "Restart Logic",
    "Feature Start",
    "Enable Field Commands",
)


def startup_phase_timings(tags):
    """Return ordered phase timings, or leave an unfamiliar layout to the raw reader."""
    if (
        len(tags) < 2
        or (tags[0].tag_class, tags[0].tag_number) != (TagClass.opening, 3)
        or (tags[-1].tag_class, tags[-1].tag_number) != (TagClass.closing, 3)
        or (len(tags) - 2) % 4
    ):
        return None
    phases = []
    for offset in range(1, len(tags) - 1, 4):
        opening, phase, elapsed, closing = tags[offset : offset + 4]
        if (
            (opening.tag_class, opening.tag_number) != (TagClass.opening, 4)
            or (closing.tag_class, closing.tag_number) != (TagClass.closing, 4)
            or (phase.tag_class, phase.tag_number) != (TagClass.application, 9)
            or len(phase.tag_data) != 1
            or (elapsed.tag_class, elapsed.tag_number) != (TagClass.application, 2)
            or not 1 <= len(elapsed.tag_data) <= 4
        ):
            return None
        code = phase.tag_data[0]
        entry = {"phase": code, "duration_ms": int.from_bytes(elapsed.tag_data, "big")}
        if code < len(PHASE_NAMES):
            entry["name"] = PHASE_NAMES[code]
        phases.append(entry)
    return phases
