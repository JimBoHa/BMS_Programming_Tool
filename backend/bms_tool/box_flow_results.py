"""Decode the two recorded results of a native Box Flow Test."""

import math
import struct

from bacpypes3.primitivedata import TagClass


def flow_samples(tags, entry_context):
    """Each ordered result contains the native flow and damper position, both Real."""
    if len(tags) % 4 or len(tags) > 4096:
        raise ValueError("Incomplete or oversized box flow test sample list.")
    samples = []
    for start in range(0, len(tags), 4):
        opening, flow, position, closing = tags[start : start + 4]
        if (
            opening.tag_class != TagClass.opening
            or closing.tag_class != TagClass.closing
            or opening.tag_number != entry_context
            or closing.tag_number != entry_context
        ):
            raise ValueError("Invalid box flow test sample framing.")
        values = []
        for member in (flow, position):
            if (
                member.tag_class != TagClass.application
                or member.tag_number != 4
                or len(member.tag_data) != 4
            ):
                raise ValueError("A box flow test sample requires two native Real values.")
            number = struct.unpack(">f", member.tag_data)[0]
            if not math.isfinite(number):
                raise ValueError("Nonfinite box flow test sample.")
            values.append(number)
        samples.append({"flow": values[0], "damper_position_percent": values[1]})
    return samples


def result_bits(tags):
    if (
        len(tags) != 1
        or tags[0].tag_class != TagClass.application
        or tags[0].tag_number != 8
        or len(tags[0].tag_data) != 2
        or tags[0].tag_data[0] != 0
    ):
        raise ValueError("A box flow test result summary requires exactly eight bits.")
    return list(tags[0].app_to_object())
