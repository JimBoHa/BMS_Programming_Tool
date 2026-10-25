"""Length-delimited native application records, including opaque metadata."""

MAX_RECORDS = 20000


def native_frames(data, *, required=False):
    if len(data) < 14 or int.from_bytes(data[8:10], "little") != 1:
        if required:
            raise ValueError("Unsupported tagged-MOI application header.")
        return None
    count = int.from_bytes(data[10:14], "little")
    if not 1 <= count <= MAX_RECORDS:
        raise ValueError("Native application record count exceeds the supported profile.")
    frames, offset = [], 14
    for _ in range(count):
        if offset + 2 > len(data):
            raise ValueError("Truncated native record length.")
        size, prefix = int.from_bytes(data[offset : offset + 2], "little"), 2
        if size == 0:
            if offset + 6 > len(data):
                raise ValueError("Truncated extended native record length.")
            size, prefix = int.from_bytes(data[offset + 2 : offset + 6], "little"), 6
        start, end = offset + prefix, offset + size
        if size < prefix + 13 or end > len(data):
            raise ValueError("Native record length is inconsistent with the archive.")
        cid, oid = int.from_bytes(data[start : start + 2], "little"), data[start + 6 : start + 10]
        if (
            cid > 1023
            or data[start + 2 : start + 6] != b"\x02\x00\x0e\x1c"
            or int.from_bytes(oid, "big") >> 22 != cid
        ):
            raise ValueError("Unsupported native object identity framing.")
        frames.append((start, cid, oid, end))
        offset = end
    if offset != len(data):
        raise ValueError("Native application has unaccounted trailing records or data.")
    return frames
