"""Command snapshots against authored application bytes and a direct or routed UDP peer."""

import copy
import hashlib
import json
import struct

import httpx
import pytest
from bacpypes3.apdu import ReadPropertyACK
from bacpypes3.app import Application
from bacpypes3.basetypes import DateTime, PriorityArray, PriorityValue, Reliability, StatusFlags
from bacpypes3.constructeddata import Any
from bacpypes3.object import FileObject
from bacpypes3.primitivedata import Boolean, CharacterString, Null, ObjectIdentifier, Real, Unsigned
from bms_tool.app import create_app
from bms_tool.native_network_inputs import compare_points, observe_point, root_network_inputs

from .test_controller_application import encoded, native_record
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_applications import port
from .test_native_order_recovery_transfer import selected_target
from .test_native_snapshot_restore import literal_saved_image


def input_record(instance=7, flags=(True, True), prefix="controller/575_1"):
    props = [
        (32527, CharacterString(f"{prefix}.2_{instance}")),
        (75, ObjectIdentifier(("analog-value", instance))),
        (2390, CharacterString("Air target")),
    ]
    props.extend(
        (key, Boolean(v)) for key, v in zip((3807, 2567), flags, strict=True) if v is not None
    )
    return native_record(526, instance, [(pid, encoded(value)) for pid, value in props])


def image(*records):
    data = literal_saved_image(modules=0)
    rows = [
        native_record(575, 1, [(32527, encoded(CharacterString("controller/575_1")))]),
        *records,
    ]
    return (
        data[:10]
        + struct.pack("<I", int.from_bytes(data[10:14], "little") + len(rows))
        + data[14:]
        + b"".join(struct.pack("<H", len(record) + 2) + record for record in rows)
    )


def test_scopes_only_identified_commandable_root_inputs():
    found, unknown = root_network_inputs(
        image(
            input_record(),
            input_record(8, flags=(True, False)),
            input_record(9, flags=(True, None)),
            input_record(10, prefix="controller/575_1.child"),
        )
    )
    assert [(p["object"], p["name"]) for p in found] == [("analog-value,7", "Air target")]
    assert unknown == ["controller/575_1.2_9"]
    with pytest.raises(ValueError, match="ambiguous"):
        root_network_inputs(image(input_record(), input_record()))


def observation():
    point = {"object": "analog-value,7", "name": "Air target", "reference": "controller/575_1.2_7"}
    slots = [{"type": "null", "value": None} for _ in range(16)]
    slots[7] = {"type": "real", "value": 0.0}
    values = {
        "object-name": point["name"],
        "present-value": 0.0,
        "priority-array": slots,
        "relinquish-default": 1.0,
        "reliability": 0,
        "out-of-service": False,
        "status-flags": [0, 0, 0, 0],
    }
    raw = {
        "target": {},
        "connector_config": {},
        "identity_verified": True,
        "finished_at": "closed",
        "objects": [
            {
                "object": point["object"],
                "identity_verified": True,
                "properties": {k: {"status": "ok", "value": v} for k, v in values.items()},
            }
        ],
    }
    return point, raw


@pytest.mark.parametrize(
    ("key", "bad"),
    [
        ("priority-array", []),
        ("priority-array", [{"type": "unsigned", "value": 0}] * 16),
        ("present-value", True),
        ("present-value", None),
        ("present-value", float("nan")),
        ("relinquish-default", "0"),
        ("reliability", False),
        ("reliability", 7),
        ("status-flags", [0, 1, 0, 0]),
        ("status-flags", ["0", 0, 0, 0]),
        ("out-of-service", True),
        ("object-name", "Another input"),
    ],
)
def test_bad_quality_or_malformed_data_never_confirms_commands(key, bad):
    point, raw = observation()
    good = observe_point(point, raw, {}, {})
    assert good["verified"]
    raw["objects"][0]["properties"][key]["value"] = bad
    recorded = observe_point(point, raw, {}, {})
    assert not recorded["verified"] and recorded["unavailable"]
    assert compare_points([good], [recorded])[0]["status"] == "unverified"


@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("source_kind", ["native-backup", "controller-file"])
async def test_live_read_and_persistent_comparison(
    native_link, tmp_path, monkeypatch, routed, source_kind
):
    peer = native_link[0]
    original_read = peer.do_ReadPropertyRequest
    command = [Real(0)]
    field_props = []
    payload = image(input_record())
    if source_kind == "controller-file":
        peer.files[3] = payload
        peer.add_object(
            FileObject(
                objectIdentifier=("file", 3),
                objectName="Application archive",
                description="Authored program",
                fileType=".moi",
                fileSize=len(payload),
                modificationDate=DateTime("2026-01-05 12:00:00"),
                archive=False,
                readOnly=True,
                fileAccessMethod="stream-access",
            )
        )

    async def point_read(request):
        if source_kind == "controller-file" and str(request.objectIdentifier) == "file,3":
            return await Application.do_ReadPropertyRequest(peer, request)
        if (
            source_kind == "controller-file"
            and str(request.propertyIdentifier) == "configuration-files"
        ):
            response = (
                Unsigned(1) if request.propertyArrayIndex == 0 else ObjectIdentifier(("file", 3))
            )
            return await peer.response(
                ReadPropertyACK(
                    context=request,
                    objectIdentifier=request.objectIdentifier,
                    propertyIdentifier=request.propertyIdentifier,
                    propertyArrayIndex=request.propertyArrayIndex,
                    propertyValue=Any(response),
                )
            )
        if str(request.objectIdentifier) != "analog-value,7":
            return await original_read(request)
        prop = str(request.propertyIdentifier)
        field_props.append(prop)
        slots = [PriorityValue(null=Null(())) for _ in range(16)]
        if command[0] is not None:
            slots[7] = PriorityValue(real=command[0])
        value = {
            "object-identifier": ObjectIdentifier("analog-value,7"),
            "object-name": CharacterString("Air target"),
            "present-value": command[0] if command[0] is not None else Real(12),
            "relinquish-default": Real(12),
            "priority-array": PriorityArray(slots),
            "reliability": Reliability(0),
            "out-of-service": Boolean(False),
            "status-flags": StatusFlags([0] * 4),
        }[prop]
        await peer.response(
            ReadPropertyACK(
                context=request,
                objectIdentifier=request.objectIdentifier,
                propertyIdentifier=request.propertyIdentifier,
                propertyValue=Any(value),
            )
        )

    monkeypatch.setattr(peer, "do_ReadPropertyRequest", point_read)
    app = create_app(tmp_path / "service")
    native = app.state.native_applications
    async with (
        selected_target(native_link, routed) as target,
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        client.headers["X-Studio-Token"] = (await client.get("/api/session")).json()["token"]
        await client.post(
            "/api/bacnet/connect",
            json={
                "local_address": f"127.0.0.1:{port()}",
                "router": target.get("router"),
                "dnet": target.get("dnet"),
            },
        )
        target = {"router": None, "dnet": None, **target}
        identity = {
            "device": target["device"],
            **{k: v for k, v in peer.metadata.items() if k != "system-status"},
        }
        if source_kind == "controller-file":
            program = await client.post("/api/bacnet/controller/application/read", json=target)
            assert program.status_code == 200, program.text
            opened = program.json()
            assert opened["status"] == "read" and opened["identity_verified"]
            capture = opened["receipt"]
            assert peer.events and all(e[:2] == ("read", 3) for e in peer.events)
            peer.events.clear()
            digest = capture["sha256"]
        else:
            capture = native.storage.save(
                {
                    "target": {k: v for k, v in target.items() if k != "device"},
                    "device": target["device"],
                    "identity": identity,
                    "source_identity_matches": True,
                },
                {3: payload, 11: b"saved", 12: b"configuration"},
            )
            digest = capture["evidence_sha256"]
        base = "/api/bacnet/controller/native-application/network-inputs"
        options = {
            **target,
            "capture_id": capture["id"],
            "snapshot_sha256": digest,
            "operation_id": "read-network-baseline",
        }
        if source_kind == "controller-file":
            options["source_kind"] = source_kind
        first = await client.post(base + "/read", json=options)
        assert first.status_code == 200, first.text
        before = first.json()
        assert before["selection"].get("source_kind", "native-backup") == source_kind
        assert before["points"][0]["verified"], before["points"][0]["unavailable"]
        assert before["points"][0]["values"]["priority-array"][7] == {"type": "real", "value": 0.0}
        command[0] = None
        options.update(operation_id="compare-network-inputs", baseline_id=before["id"])
        second = await client.post(base + "/read", json=options)
        assert second.status_code == 200, second.text
        after = second.json()
        assert after["comparison"] == [
            {
                "object": "analog-value,7",
                "status": "changed",
                "priority_changes": [
                    {
                        "priority": 8,
                        "before": {"type": "real", "value": 0.0},
                        "after": {"type": "null", "value": None},
                    }
                ],
                "changed_fields": ["present-value"],
            }
        ]
        assert not peer.events and "priority-array" in field_props
        requests = len(field_props)
        opened = await client.get(base + "/reports/" + after["id"])
        assert (
            opened.content == second.content
            and opened.headers["x-studio-artifact-sha256"]
            == hashlib.sha256(second.content).hexdigest()
        )
        assert [r["id"] for r in (await client.get(base + "/history/" + capture["id"])).json()] == [
            after["id"],
            before["id"],
        ]
        for update in ({"limit": 1}, {"snapshot_sha256": "0" * 64}, {"device": "device,99"}):
            assert (await client.post(base + "/read", json=options | update)).status_code == 422
        if source_kind == "controller-file":
            peer.metadata["application-software-version"] = "changed since baseline"
            rejected = await client.post(base + "/read", json=options)
            assert rejected.status_code == 422 and "since the baseline" in rejected.text
            peer.metadata["application-software-version"] = identity["application-software-version"]
            peer.metadata["object-name"] = "Different controller name"
            opened = (
                await client.post("/api/bacnet/controller/application/read", json=target)
            ).json()
            assert (
                opened["identity_verified"]
                and not opened["operation_capabilities"]["native_identity_matches_capture"]
            )
            mismatched = options | {
                "capture_id": opened["receipt"]["id"],
                "snapshot_sha256": opened["receipt"]["sha256"],
                "baseline_id": None,
            }
            rejected = await client.post(base + "/read", json=mismatched)
            assert rejected.status_code == 422 and "File identity differs" in rejected.text
            peer.metadata["object-name"] = identity["object-name"]
        peer.metadata["firmware-revision"] = "another-release"
        assert (await client.post(base + "/read", json=options)).status_code == 422
        if source_kind == "controller-file":
            peer.metadata["firmware-revision"] = identity["firmware-revision"]
            await client.post("/api/bacnet/disconnect", json={})
            changed_interface = await client.post(
                "/api/bacnet/connect",
                json={
                    "local_address": f"127.0.0.1:{port()}",
                    "instance": 23465,
                    "router": target["router"],
                    "dnet": target["dnet"],
                },
            )
            assert changed_interface.status_code == 200
            rejected = await client.post(base + "/read", json=options | {"baseline_id": None})
            assert rejected.status_code == 422 and "interface that read" in rejected.text
        assert len(field_props) == requests
        with native.store.connect() as db:
            altered = copy.deepcopy(after)
            altered["points"] = []
            db.execute(
                "UPDATE native_network_input_reports SET body=? WHERE id=?",
                (json.dumps(altered), after["id"]),
            )
        assert (await client.get(base + "/reports/" + after["id"])).status_code == 422
