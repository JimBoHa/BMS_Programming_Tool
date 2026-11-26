"""Build a synthetic inline valve and typed primitive library without controller archives."""

import pytest
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


async def test_withdrawn_sequence_draft_stays_offline_and_old_tokens_cannot_dispatch(native_link):
    from bms_tool import native_inline_activation as activation
    from bms_tool import native_inline_shadow as shadow
    from bms_tool.moi_identity import sha

    peer, _, _, service, target = native_link
    observation_peer(peer, "")
    peer.files = authored_source(catalog=True)
    donor = await service.capture(**target, operation_id="capture-primitives")
    peer.files = authored_source()
    cap = await service.capture(**target, operation_id="capture-field")
    options = ShadowReview(
        **target,
        operation_id="draft-application",
        capture_id=cap["id"],
        snapshot_sha256=cap["snapshot_evidence_sha256"],
        first_instance=200,
        prototype_capture_id=donor["id"],
        prototype_sha256=donor["snapshot_evidence_sha256"],
    )
    await service.bacnet.disconnect()
    before = list(peer.events)
    draft = await review(service, options)
    assert draft["can_apply"] is draft["controller_queries"] is False
    assert "token" not in draft and not service.plans
    assert draft["compilation"]["old_wires_replaced"] == 0
    assert draft["sizing"]["candidate_native_bytes"] > draft["sizing"]["original_native_bytes"]
    with pytest.raises(ValueError, match="exact target"):
        await review(service, options.model_copy(update={"device": "device,987"}))
    with pytest.raises(ValueError, match="exact target"):
        await review(service, options.model_copy(update={"snapshot_sha256": "0" * 64}))
    with pytest.raises(ValueError, match="same model"):
        await review(service, options.model_copy(update={"prototype_sha256": "0" * 64}))
    active = activation.ActivationReview(
        **target,
        operation_id="review-valve",
        capture_id=cap["id"],
        snapshot_sha256=cap["snapshot_evidence_sha256"],
        observation_receipt_id="a" * 32,
    )
    with pytest.raises(ValueError, match="off-equipment"):
        await activation.review(service, active)
    for kind, req in (
        (
            shadow.KIND,
            ShadowApply(
                operation_id="old-observation",
                token="a" * 32,
                review_sha256="b" * 64,
                sequence_observation_confirmed=True,
                application_transfer_confirmed=True,
            ),
        ),
        (
            activation.KIND,
            activation.ActivationApply(
                operation_id="old-activation",
                token="c" * 32,
                review_sha256="d" * 64,
                valve_connection_confirmed=True,
                application_transfer_confirmed=True,
            ),
        ),
    ):
        service.plans[req.token] = {"digest": req.review_sha256, "body": {"can_apply": True}}
        with pytest.raises(ValueError, match="off-equipment"):
            await service.apply_reviewed(req, default_edit=False, inline_kind=kind)
        assert req.token not in service.plans
    assert before == peer.events

    # Historical images can still be reconstructed and verified from a sealed journal.
    _, files = service.storage.load(cap["id"])
    historical_selection = {**draft["selection"], "sampling_mode": "elapsed-phase"}
    raw, report = shadow.compile_shadow(service, cap["identity"], historical_selection, files)
    parent = service.storage.intent(
        {
            "id": "e" * 32,
            "identity": cap["identity"],
            "target": cap["target"],
            "change_kind": shadow.KIND,
            "operation_profile": shadow.PROFILE,
            "backup_id": cap["id"],
            "compilation": report,
            "sequence_selection": historical_selection,
            "sequence_observation_confirmed": True,
            "payload_sha256": sha(raw),
            "native_payload_sha256": sha(MoiIdentity(raw).data),
        }
    )
    with pytest.raises(ValueError, match="offline-only"):
        shadow.reconstruct(service, {**parent, "sequence_selection": draft["selection"]})
    after = {**files, 3: raw}
    verified = shadow.verify(service, parent, after)
    service.storage.finish(
        parent["id"],
        {
            "status": "verified",
            "operational": True,
            "intent_sha256": parent["evidence_sha256"],
            "preservation": verified,
        },
    )
    enabled, proposal = activation.prepare(
        service, cap["identity"], after, parent["id"], cap["target"]
    )
    assert enabled != raw and len(proposal["selectors"]) >= 10
    assert len(report["control_edges"]) == 2 and verified["existing_control_connections_preserved"]
    with pytest.raises(ValueError, match="station"):
        activation.prepare(
            service,
            cap["identity"],
            after,
            parent["id"],
            {**cap["target"], "address": "different-station"},
        )
    assert before == peer.events


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
