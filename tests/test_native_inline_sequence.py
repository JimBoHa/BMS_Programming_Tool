"""Build a synthetic inline valve and typed primitive library without controller archives."""

from types import MethodType

import pytest
from bacpypes3.apdu import ReadPropertyMultipleACK
from bacpypes3.basetypes import (
    ErrorType,
    ReadAccessResult,
    ReadAccessResultElement,
    ReadAccessResultElementChoice,
)
from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    Enumerated,
    ObjectIdentifier,
    Real,
    Unsigned,
)
from bms_tool.moi_identity import MoiIdentity
from bms_tool.native_inline_sequence import SPECS, InlineSequenceCompiler
from bms_tool.native_inline_shadow import ShadowApply, ShadowReview, review
from bms_tool.native_inputs import archive

from .test_controller_application import encoded, native_record
from .test_moi_parameters import parameters_source
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_inline_monitor import observation_peer

R = "controller/sequence"


def atoms(t, values):
    return b"".join(encoded(t(v)) for v in values)


def authored_source(*, catalog=False):
    base, static, dynamic = parameters_source(cid=194, model="FX-PCV1630-0", modules=0)
    app = MoiIdentity(base)
    rows = [app.data[r["offset"] : r["end_offset"]] for r in app.records]

    def add(cid, n, typ, ref, props):
        fields = [(75, encoded(ObjectIdentifier((typ, n)))), (32527, encoded(CharacterString(ref)))]
        rows.append(
            native_record(
                cid,
                n,
                fields + [(k, v if isinstance(v, bytes) else encoded(v)) for k, v in props.items()],
            )
        )

    if catalog:
        n = 100
        for name, (function, cls, setup, pins) in SPECS.items():
            n += 1
            parent = f"controller/library_{n}"
            p = {3670: Enumerated(function), 3184: atoms(Enumerated, pins)}
            if setup is not None:
                p[518] = Enumerated(setup)
            if name == "select":
                p.update({2381: atoms(Unsigned, [0, 2]), 3122: Unsigned(1)})
            add(cls, n, cls, parent, p)
            for pin, cid in pins.items():
                n += 1
                typ = 5 if cid in (530, 531) else 19 if cid == 528 else 2
                props = {
                    3365: Enumerated(pin),
                    3113: Boolean(False) if typ == 5 else Enumerated(0) if typ == 19 else Real(0),
                }
                if name == "timer" and pin in (518, 1083):
                    props[931] = Enumerated(21 if pin == 518 else 22)
                if name == "timer" and pin in (1080, 1081):
                    props[117] = Enumerated(73)
                add(cid, n, typ, parent + f".{typ}_{n}", props)
        return {3: archive(app, rows), 11: static, 12: dynamic}
    specs = [
        (556, 14, 556, "DA-VP"),
        (556, 15, 556, "DA-T"),
        (530, 21, 5, "HTG-EN"),
        (526, 22, 2, "ZNT-SP"),
        (570, 12, 570, "Flow calculation"),
        (592, 23, 592, "Heat enable"),
        (536, 24, 536, "Heat demand"),
        (555, 16, 555, "HTG-O"),
    ]
    edges = [
        (0, 8000, 4, 3504),
        (2, 663, 4, 3654),
        (3, 663, 4, 960),
        (3, 663, 4, 968),
        (2, 663, 5, 513),
        (6, 800, 7, 7000),
    ]
    add(
        575,
        1,
        575,
        R,
        {
            3375: atoms(ObjectIdentifier, [(t, n) for _, n, t, _ in specs]),
            3117: atoms(Unsigned, range(len(specs))),
            3118: b"".join(b"\x3e" + atoms(Unsigned, i) + b"\x3f" for i in edges),
        },
    )
    for cid, n, typ, label in specs:
        ref = f"{R}.{typ}_{n}"
        attrs = {2390: CharacterString(label)}
        if label in ("DA-VP", "DA-T"):
            attrs.update(
                {
                    3184: atoms(Enumerated, (8000, 86)),
                    3399: b"\x3e"
                    + encoded(CharacterString("controller/" + ("integral" if n == 14 else "duct")))
                    + b"\x4e\x4f"
                    + encoded(Enumerated(85))
                    + b"\x3f",
                }
            )
        elif label == "ZNT-SP":
            attrs.update(
                {
                    117: Enumerated(64),
                    2567: Boolean(True),
                    3113: Real(71),
                    3365: Enumerated(75),
                    3670: Enumerated(3),
                    3807: Boolean(True),
                }
            )
        elif cid == 570:
            attrs.update(
                {3670: Enumerated(681), 117: Enumerated(58), 3656: Real(2000), 63464: Enumerated(0)}
            )
        elif cid == 592:
            attrs[3670] = Enumerated(711)
        elif cid == 536:
            attrs[3670] = Enumerated(6653)
        add(cid, n, typ, ref, attrs)
        if label == "DA-VP":
            for num, pin in ((52, 8000), (53, 86)):
                add(527, num, 2, ref + f".2_{num}", {3365: Enumerated(pin), 661: Enumerated(4)})
        if cid == 570:
            for j, (pin, cls) in enumerate(
                [
                    (2383, 526),
                    (3504, 526),
                    (3654, 530),
                    (960, 526),
                    (968, 526),
                    (50215, 526),
                    (3505, 527),
                    (3655, 527),
                ]
            ):
                t = 5 if cls == 530 else 2
                num = 13 if pin == 3505 else 60 + j
                meta = {3365: Enumerated(pin)}
                if pin == 3505:
                    meta.update(
                        {
                            2390: CharacterString("SA-F"),
                            3807: Boolean(True),
                            3930: Boolean(True),
                            117: Enumerated(84),
                        }
                    )
                add(cls, num, t, ref + f".{t}_{num}", meta)
    for cid, n, typ, ref, label, terminal, unit in [
        (240, 14, 0, "integral", "DA-VP", "AI1-Int", 58),
        (240, 15, 0, "duct", "DA-T", "UI IN1", 64),
        (241, 16, 1, "valve", "HTG-O", "CO OUT4", 98),
        (251, 17, 1, "damper", "DPR-O", "BO1-Int,BO2-Int", 98),
    ]:
        props = {2390: CharacterString(label), 31: CharacterString(terminal), 117: Enumerated(unit)}
        if n == 16:
            props[990] = Unsigned(4)
        if n == 17:
            props.update({990: Unsigned(6), 991: Unsigned(7)})
        add(cid, n, typ, "controller/" + ref, props)
    return {3: archive(app, rows), 11: static, 12: dynamic}


def test_complete_sequence_preserves_originals_and_proposes_only_two_control_edges():
    f = authored_source()
    library = authored_source(catalog=True)
    p = InlineSequenceCompiler(f, library[3], 200)
    p.body()
    shadow, report = p.export(shadow=True)
    protected, final = p.export(shadow=False)
    original = MoiIdentity(f[3]).reader.diagram(R)
    left = MoiIdentity(shadow)
    right = MoiIdentity(protected)
    a = left.reader.diagram(R)
    b = right.reader.diagram(R)
    assert a["connections"][: len(original["connections"])] == original["connections"]
    assert sum(u != v for u, v in zip(a["connections"], b["connections"], strict=True)) == 2
    assert sorted(report["new_avs"]) == ["MAX-DA-T", "VLV-LOCKOUT-CFM"]
    assert [report["new_avs"][k]["default"] for k in ("MAX-DA-T", "VLV-LOCKOUT-CFM")] == [125, 30]
    assert report["old_wires_replaced"] == 0 and final["old_wires_replaced"] == 2
    assert (
        len(report["added_objects"]) == len(set(report["added_objects"])) == report["added_records"]
    )
    assert left.reader.scalar(left.root, 904) == "saved"
    assert all(
        x["sha256"] == y["sha256"]
        for x, y in zip(left.records, right.records, strict=True)
        if x["class_id"] != 575
    )


async def test_complete_shadow_uses_one_reviewed_native_transfer_and_preserves_old_valve(
    native_link,
):
    peer, _, _, service, target = native_link
    # The full-size peer parses the committed image before acknowledging. Exercise the
    # shipping service's wire timeout; the tiny identity-fixture timeout is 100 ms.
    service.files.timeout = 4
    observation_peer(peer, "")
    peer.files = authored_source(catalog=True)
    donor = await service.capture(**target, operation_id="capture-primitives")
    peer.files = authored_source()
    cap = await service.capture(**target, operation_id="capture-field")
    original = peer.do_ReadPropertyRequest
    from bacpypes3.apdu import ReadPropertyACK
    from bacpypes3.constructeddata import Any

    async def read(self, req):
        if int(req.propertyIdentifier) == 76 and req.propertyArrayIndex == 0:
            await self.response(
                ReadPropertyACK(
                    context=req,
                    objectIdentifier=req.objectIdentifier,
                    propertyIdentifier=req.propertyIdentifier,
                    propertyArrayIndex=0,
                    propertyValue=Any(Unsigned(110)),
                )
            )
        else:
            await original(req)

    async def multiple(self, req):
        results = [
            ReadAccessResult(
                objectIdentifier=row.objectIdentifier,
                listOfResults=[
                    ReadAccessResultElement(
                        propertyIdentifier=75,
                        readResult=ReadAccessResultElementChoice(
                            propertyAccessError=ErrorType(
                                errorClass="object", errorCode="unknown-object"
                            )
                        ),
                    )
                ],
            )
            for row in req.listOfReadAccessSpecs
        ]
        await self.response(ReadPropertyMultipleACK(context=req, listOfReadAccessResults=results))

    peer.do_ReadPropertyRequest = MethodType(read, peer)
    peer.do_ReadPropertyMultipleRequest = MethodType(multiple, peer)
    options = ShadowReview(
        **target,
        operation_id="review-shadow",
        capture_id=cap["id"],
        snapshot_sha256=cap["snapshot_evidence_sha256"],
        first_instance=200,
        prototype_capture_id=donor["id"],
        prototype_sha256=donor["snapshot_evidence_sha256"],
    )
    plan = await review(service, options)
    assert plan["live_review"]["confirmed_absent"] == plan["compilation"]["added_records"]
    req = ShadowApply(
        operation_id="apply-shadow",
        token=plan["token"],
        review_sha256=plan["review_sha256"],
        sequence_observation_confirmed=True,
        application_transfer_confirmed=True,
    )
    receipt = await service.apply_reviewed(
        req, default_edit=False, inline_kind="inline-sequence-observe"
    )
    assert receipt["result"]["status"] == "verified", receipt["result"].get("errors")
    assert receipt["result"]["preservation"]["existing_control_connections_preserved"]
    assert peer.events.count(("state", "start-restore")) == 1

    # Use the actual guarded capture and the verified observation receipt to change
    # exactly the two source wires. The authored station supplies its own runtime
    # values on UDP; a cold valve is the correct output for this zero-flow case.
    from time import monotonic

    from bms_tool import native_inline_activation as activation

    current, files = service.storage.load(receipt["result"]["verification_capture_id"])
    local_target = service.target(options)
    _, proposal = activation.prepare(
        service, current["identity"], files, receipt["intent"]["id"], local_target
    )
    with pytest.raises(ValueError, match="station"):
        activation.prepare(
            service,
            current["identity"],
            files,
            receipt["intent"]["id"],
            {**local_target, "address": "another-station"},
        )
    by_id = {oid: name for name, (oid, _) in proposal["selectors"].items()}

    async def running(self, request):
        results = []
        for spec in request.listOfReadAccessSpecs:
            name = by_id[str(spec.objectIdentifier)]
            vals = {
                "ready": Boolean(True),
                "permit": Boolean(False),
                "threshold": Real(30),
                "limit": Real(125),
                "count": Real(30),
                "duct": Real(64),
                "clock_witness": Real(59 - int(monotonic()) % 60),
            }
            fields = [
                ReadAccessResultElement(
                    propertyIdentifier=p,
                    readResult=ReadAccessResultElementChoice(propertyValue=Any(v)),
                )
                for p, v in ((85, vals.get(name, Real(0))), (103, Enumerated(0)))
            ]
            results.append(
                ReadAccessResult(objectIdentifier=spec.objectIdentifier, listOfResults=fields)
            )
        await self.response(
            ReadPropertyMultipleACK(context=request, listOfReadAccessResults=results)
        )

    peer.do_ReadPropertyMultipleRequest = MethodType(running, peer)
    active = activation.ActivationReview(
        **target,
        operation_id="review-valve",
        capture_id=current["id"],
        snapshot_sha256=current["evidence_sha256"],
        observation_receipt_id=receipt["intent"]["id"],
    )
    plan = await activation.review(service, active)
    active_req = activation.ActivationApply(
        operation_id="enable-valve",
        token=plan["token"],
        review_sha256=plan["review_sha256"],
        valve_connection_confirmed=True,
        application_transfer_confirmed=True,
    )
    receipt = await service.apply_reviewed(
        active_req, default_edit=False, inline_kind=activation.KIND
    )
    assert receipt["result"]["status"] == "verified", receipt["result"].get("errors")
    assert receipt["result"]["preservation"]["control_connections_changed"] == 2
    assert peer.events.count(("state", "start-restore")) == 2


def observations():
    return [
        {
            "time": float(t),
            "clock_witness": float(59 - t % 60),
            "sample": 60,
            "mean": 60,
            "ready": True,
            "permit": True,
            "count": 30,
            "duct": 120,
            "proposed_valve": 50,
            "actual_valve": 75,
            "threshold": 30,
            "limit": 125,
        }
        for t in range(38)
    ]


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"proposed_valve": 55}, "limit"),
        ({"mean": 15}, "limit"),
        ({"limit": 0}, "tuning"),
        ({"count": 0}, "30-sample"),
        ({"ready": False}, "30-sample"),
        ({"clock_witness": 20}, "clock"),
        ({"sample": 0}, "mean"),
        ({"time": 6}, "continuous"),
    ],
)
def test_actual_runtime_observations_gate_valve_activation(change, reason):
    from bms_tool.native_inline_activation import validate_samples

    rows = observations()
    assert validate_samples(rows)["shadow_valve"] == 50
    with pytest.raises(ValueError, match=reason):
        validate_samples([{**r, **change} for r in rows])


def test_observed_mean_must_match_the_window_after_an_airflow_step():
    from bms_tool.native_inline_activation import validate_samples

    rows = observations()
    values = [40.0 if i < 22 else 80.0 for i in range(len(rows))]
    for i, row in enumerate(rows):
        row["sample"] = values[i]
        row["mean"] = sum(values[max(0, i - 29) : i + 1]) / min(i + 1, 30)
    assert validate_samples(rows)["mean"] == pytest.approx(sum(values[-30:]) / 30)
    rows[-1]["mean"] = 79
    with pytest.raises(ValueError, match="mean"):
        validate_samples(rows)
