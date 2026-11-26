"""Authored native records, engineering review, and evaluation of the emitted graph."""

import argparse
import math
import struct

import pytest
from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    Enumerated,
    ObjectIdentifier,
    Real,
    Unsigned,
)
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.native_inline_heat import compile_permissive, local_copy
from bms_tool.native_inputs import encoded, native_record

DIAGRAM = "8-321/575_1"
OPTIONS = dict(
    diagram_ref=DIAGRAM,
    pressure_ref=DIAGRAM + ".556_45",
    flow_ref=DIAGRAM + ".570_46",
    enable_ref=DIAGRAM + ".5_47",
    passthrough_ref=DIAGRAM + ".592_48",
    valve_ref=DIAGRAM + ".555_51",
    threshold_cfm=40.0,
)


def fixture(
    *,
    order=(0, 1, 2, 3, 4, 5, 6),
    layout=False,
    pressure_slot=4,
    extra=False,
    comparison=True,
    mux_modes=(0, 2),
    valve_slot=4,
    second_valve_driver=False,
):
    rows = []

    def obj(cid, i, typ, ref, props):
        fields = {
            32527: encoded(CharacterString(ref)),
            75: encoded(ObjectIdentifier((typ, i))),
            **props,
        }
        rows.append(native_record(cid, i, list(fields.items())))

    def enum(n):
        return encoded(Enumerated(n))

    def nums(ns):
        return b"".join(encoded(Unsigned(n)) for n in ns)

    def wires(values):
        return b"".join(b"\x3e" + nums(row) + b"\x3f" for row in values)

    ds = [(556, 45), (570, 46), (5, 47), (592, 48), (540, 49), (536, 50), (555, 51)]
    obj(
        194,
        321,
        8,
        "8-321",
        {
            2390: encoded(CharacterString("Lab")),
            70: encoded(CharacterString("M4-CVM03050-0")),
            4128: encoded(Unsigned(66)),
            4129: encoded(Unsigned(65)),
        },
    )
    obj(
        240,
        45,
        0,
        "8-321/0_45",
        {
            31: encoded(CharacterString("AI1-Int")),
            518: enum(9),
            519: encoded(Unsigned(pressure_slot)),
        },
    )
    obj(
        241,
        51,
        1,
        "8-321/1_51",
        {
            2390: encoded(CharacterString("HTG-O")),
            990: encoded(Unsigned(valve_slot)),
            117: enum(98),
        },
    )
    obj(
        251,
        53,
        1,
        "8-321/1_53",
        {
            2390: encoded(CharacterString("DPR-O")),
            31: encoded(CharacterString("BO1-Int,BO2-Int")),
            990: encoded(Unsigned(6)),
            991: encoded(Unsigned(7)),
        },
    )
    links = [(0, 8000, 1, 3504), (2, 663, 3, 513), (3, 85, 4, 7008), (5, 8006, 6, 7000)]
    if second_valve_driver:
        links.append((1, 3505, 6, 7000))
    props = {
        3117: nums(order),
        3118: wires(links),
        3375: b"".join(encoded(ObjectIdentifier(pair)) for pair in ds),
    }
    if layout:
        props[3384] = b""
    obj(575, 1, 575, DIAGRAM, props)
    obj(556, 45, 556, OPTIONS["pressure_ref"], {})
    obj(570, 46, 570, OPTIONS["flow_ref"], {117: enum(58)})
    obj(
        527,
        54,
        2,
        OPTIONS["flow_ref"] + ".2_54",
        {2390: encoded(CharacterString("SA-F")), 3365: enum(3505), 3113: encoded(Real(0))},
    )
    obj(530, 47, 5, OPTIONS["enable_ref"], {2390: encoded(CharacterString("HTG-EN"))})
    obj(592, 48, 592, OPTIONS["passthrough_ref"], {3670: enum(711)})
    obj(540, 49, 540, DIAGRAM + ".540_49", {})
    obj(536, 50, 536, DIAGRAM + ".536_50", {})
    obj(527, 52, 2, DIAGRAM + ".536_50.2_52", {3365: enum(8006)})
    obj(555, 51, 555, OPTIONS["valve_ref"], {2390: encoded(CharacterString("HTG-O"))})
    specs = [
        (539, 21, None, [513, 85], [(526, 513), (531, 85)]),
        (559, 24, 1, [7000, 7001, 85], [(530, 7000), (530, 7001), (531, 85)]),
        (562, 14, None, [961, 7000, 7001, 85], [(527, 85), (530, 961), (526, 7000), (526, 7001)]),
    ]
    if comparison:
        specs.append(
            (560, 32, 3, [85, 50083, 50084], [(531, 85), (526, 50083), (526, 50084), (526, 637)])
        )
    for serial, (cid, fn, setup, pins, children) in enumerate(specs, 100):
        ref = f"8-321/536_1000.{cid}_{serial}"
        props = {3670: enum(fn), 3184: b"".join(enum(n) for n in pins)}
        if cid == 562:
            props.update({2381: nums(mux_modes), 3122: encoded(Unsigned(1))})
        if setup is not None:
            props[518] = enum(setup)
        if extra and fn == 21:
            props[65000] = encoded(Unsigned(1))
        obj(cid, serial, cid, ref, props)
        for seq, (child, port) in enumerate(children, 1):
            typ = 2 if child in (526, 527) else 5
            inst = 100 * serial + seq
            props = {3365: enum(port)}
            if fn == 21 and port == 85:
                props[3113] = encoded(Boolean(True))
            obj(child, inst, typ, f"{ref}.{typ}_{inst}", props)
    return struct.pack("<6sHHI", b"\x02\x00MOI\x00", 194, 1, len(rows)) + b"".join(
        struct.pack("<H", len(r) + 2) + r for r in rows
    )


def build(src, **options):
    return compile_permissive(src, source_sha256=sha(src), **(OPTIONS | options))


def evaluate(image, *, enabled, cfm, pressure_reliable, flow_reliable, demand=74.0):
    # Traverse the result by native class, bound port and execution order. No generated label
    # or fixed new instance is used to decide what the compiled gate does.
    app = MoiIdentity(image)
    rd = app.reader
    g = rd.diagram(DIAGRAM)
    state = {}
    feeds = {
        (w["target_ref"], w["target_port"]): (w["source_ref"], w["source_port"])
        for w in g["connections"]
    }
    for index in g["execution_order"]:
        b = g["blocks"][index]
        ref = b["ref"]
        kind = b["class_id"]

        def port(pid, block_ref=ref):
            if (block_ref, pid) in feeds:
                return state[feeds[(block_ref, pid)]]
            (child,) = [
                r
                for r in rd.records.values()
                if r["ref"].rsplit(".", 1)[0] == block_ref and rd.scalar(r, 3365) == pid
            ]
            return rd.scalar(child, 3113), True

        if kind == 556:
            state[ref, 8000] = 1.0, pressure_reliable
        elif kind == 570:
            state[ref, 3505] = cfm, flow_reliable
        elif kind == 530:
            state[ref, 663] = enabled, True
        elif kind == 539:
            state[ref, 85] = port(513)[1], True
        elif kind == 560:
            state[ref, 85] = port(50083)[0] >= port(50084)[0], port(50083)[1] and port(50084)[1]
        elif kind == 559:
            inputs = [p for r, p in feeds if r == ref]
            state[ref, 85] = all(port(p)[0] for p in inputs), all(port(p)[1] for p in inputs)
        elif kind == 562:
            from bacpypes3.primitivedata import Unsigned
            from bms_tool.moi_application import _list

            record = rd.records[ref]
            mapping = _list(record["properties"][2381]["tags"], Unsigned)
            selected = port(961)
            branch = int(mapping[int(selected[0])]) or rd.scalar(record, 3122)
            value, good = port(6999 + branch)
            state[ref, 85] = value, selected[1] and good
        elif kind == 592:
            state[ref, 85] = port(513)
        elif kind == 540:
            permission = port(7008)
        elif kind == 536:
            state[ref, 8006] = demand, True
        elif kind == 555:
            return permission, port(7000)
    raise AssertionError("No physical valve command in the compiled program")


def test_compiled_heat_permit_truth_table_and_saved_default():
    src = fixture()
    image, report = build(src)
    assert report["new_records"] == 29 and report["added_connections"] == 11
    assert report["verified_graph"] and not report["field_verified"]
    for enabled in (False, True):
        for pr in (False, True):
            for fr in (False, True):
                for flow in (-1, 0, 39.99, 40, 100):
                    actual = evaluate(
                        image, enabled=enabled, cfm=flow, pressure_reliable=pr, flow_reliable=fr
                    )
                    proven = pr and fr and flow >= 40
                    assert actual == ((enabled and proven, True), (74.0 if proven else 0.0, True))
    with pytest.raises(ValueError, match="already contains"):
        build(image)


@pytest.mark.parametrize("threshold", [0, -1, True, math.nan, math.inf, 1e-100])
def test_invalid_or_unrepresentable_proof_rejected(threshold):
    with pytest.raises(ValueError, match="threshold"):
        build(fixture(), threshold_cfm=threshold)


@pytest.mark.parametrize(
    "opts",
    [
        {"pressure_slot": 2},
        {"layout": True},
        {"extra": True},
        {"comparison": False},
        {"order": (0, 2, 3, 1, 4, 5, 6)},
        {"valve_slot": 2},
        {"mux_modes": (2, 0)},
        {"second_valve_driver": True},
        {"order": (0, 1, 2, 3, 4, 6, 5)},
    ],
)
def test_unqualified_sources_refused(opts):
    with pytest.raises(ValueError):
        build(fixture(**opts))


def test_stale_hash_and_swapped_sources_refused():
    src = fixture()
    with pytest.raises(ValueError, match="exact reviewed"):
        compile_permissive(src, source_sha256="0" * 64, **OPTIONS)
    with pytest.raises(ValueError):
        build(src, pressure_ref=OPTIONS["enable_ref"])


def test_local_copy_requires_same_three_files_and_review(tmp_path):
    from bms_tool.mstp import header_crc

    f = tmp_path / "app"
    s = tmp_path / "settings"
    v = tmp_path / "values"
    args = argparse.Namespace(
        application=f,
        static=s,
        dynamic=v,
        diagram=DIAGRAM,
        pressure=OPTIONS["pressure_ref"],
        flow=OPTIONS["flow_ref"],
        enable=OPTIONS["enable_ref"],
        passthrough=OPTIONS["passthrough_ref"],
        valve=OPTIONS["valve_ref"],
        first_instance=20000,
        threshold_cfm=40,
        output=None,
        review_sha256=None,
    )
    # Save a typed Real default on an existing port in the authored application.
    src = fixture()
    a = MoiIdentity(src)
    constant = next(r for r in a.records if r["class_id"] == 526)
    from bms_tool.native_inputs import archive, replace_properties

    source = archive(
        a,
        [
            replace_properties(a, r, {3113: encoded(Real(0))})
            if r["offset"] == constant["offset"]
            else a.data[r["offset"] : r["end_offset"]]
            for r in a.records
        ],
    )
    f.write_bytes(source)
    obj = ObjectIdentifier(a.reader.scalar(constant, 75))
    selector = ((int(obj[0]) << 22) | obj[1]).to_bytes(4, "big")
    s.write_bytes(
        bytes.fromhex("0010")
        + selector
        + (3113).to_bytes(2, "big")
        + bytes([0x6F, 4])
        + (526).to_bytes(2, "big")
        + bytes(4)
    )
    raw = struct.pack(">f", 0)
    v.write_bytes(raw + bytes([header_crc(raw) ^ 255]))
    review = local_copy(args)
    assert not review["local_copy_saved"]
    args.output = tmp_path / "candidate"
    args.review_sha256 = review["review_sha256"]
    assert local_copy(args)["local_copy_saved"]
    assert sha(args.output.read_bytes()) == review["candidate_sha256"]
    with pytest.raises(FileExistsError):
        local_copy(args)
    args.output = tmp_path / "other"
    args.threshold_cfm = 41
    with pytest.raises(ValueError, match="Review these backup"):
        local_copy(args)


def test_allocator_bound_requires_space_for_the_complete_edit():
    src = fixture()
    with pytest.raises(ValueError, match="Insufficient"):
        build(src, first_instance=4_194_300)
    output, review = build(src, first_instance=123456)
    assert review["verified_graph"] and "539_123456" in str(review["blocks"])
