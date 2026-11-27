"""Dedicated local contacts alongside independently configured universal inputs."""

import gzip
import struct

import pytest
from bacpypes3.primitivedata import CharacterString, Enumerated, ObjectIdentifier, Unsigned
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity
from bms_tool.native_inputs import NativeInputCompiler, verify_input_preservation
from fastapi.testclient import TestClient

from .test_controller_application import encoded, native_record
from .test_native_inputs import allocation, config, source


def dedicated(slot=7, instance=711, *, cid=242, **values):
    props = {
        31: CharacterString(values.get("label", f"BI IN{slot}")),
        75: values.get("object_id", ObjectIdentifier((3, instance))),
        519: values.get("terminal", Unsigned(slot)),
        32527: CharacterString(values.get("ref", f"controller/3_{instance}")),
        65001: CharacterString("Preserve this unrelated field"),
    }
    props.update(values.get("extra", {}))
    return native_record(cid, instance, [(pid, encoded(val)) for pid, val in props.items()])


def fixture(*extra, model="FX-PCG2611-0", compressed=False):
    files = source(model=model, existing=True, internal=False)
    raw = bytearray(files[3])
    count = struct.unpack_from("<I", raw, 10)[0]
    struct.pack_into("<I", raw, 10, count + len(extra))
    for record in extra:
        raw.extend(struct.pack("<H", len(record) + 2) + record)
    return {**files, 3: gzip.compress(raw, mtime=0) if compressed else bytes(raw)}


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("action", ["allocate", "mode"])
def test_local_contacts_survive_universal_current_edit(compressed, action):
    files = fixture(dedicated(), dedicated(8, 712), compressed=compressed)
    compiler = NativeInputCompiler(files)
    state = compiler.source()
    assert state["available_slots"] == [2, 3, 4, 5, 6]
    assert [row["object_id"] for row in state["inputs"]] == ["analog-input,101"]
    edit = allocation(slot=2)
    if action == "mode":
        edit = {
            "action": "mode",
            "object_instance": 101,
            "slot": 1,
            "configuration_sha256": state["inputs"][0]["configuration_sha256"],
        }
    edit["configuration"] = {**config(), "mode": "current", "input_low": 4, "input_high": 20}
    output, report = compiler.compile(edit)
    assert report["stored_configuration"]["setup"] == 2
    assert report["stored_configuration"]["field_units"] == 2
    observed = MoiIdentity(output)
    for ref in ("controller/3_711", "controller/3_712"):
        assert observed.reader.records[ref]["sha256"] == compiler.app.reader.records[ref]["sha256"]
    assert verify_input_preservation(files, {**files, 3: output}, edit)[
        "other_configuration_preserved"
    ]
    with pytest.raises(ValueError, match="universal-input terminal"):
        compiler.compile(allocation(slot=7))


@pytest.mark.parametrize(
    "records,model",
    [
        ([dedicated(6)], "FX-PCG2611-0"),
        ([dedicated(label="BI IN8")], "FX-PCG2611-0"),
        ([dedicated(cid=240)], "FX-PCG2611-0"),
        ([dedicated(terminal=Enumerated(7))], "FX-PCG2611-0"),
        ([dedicated(object_id=ObjectIdentifier((0, 711)))], "FX-PCG2611-0"),
        ([dedicated(object_id=ObjectIdentifier((3, 799)))], "FX-PCG2611-0"),
        ([dedicated(ref="controller/0_711")], "FX-PCG2611-0"),
        ([dedicated(extra={2577: CharacterString("other")})], "FX-PCG2611-0"),
        ([dedicated(extra={3645: Unsigned(0)})], "FX-PCG2611-0"),
        ([dedicated(), dedicated(instance=712)], "FX-PCG2611-0"),
        (
            [
                dedicated(),
                native_record(598, 44, [(32527, encoded(CharacterString("controller/module")))]),
            ],
            "FX-PCG2611-0",
        ),
        ([dedicated()], "M4-CVM03050-0"),
    ],
)
def test_other_models_assignments_and_host_evidence_still_refuse(records, model):
    with pytest.raises(
        ValueError, match="Unknown local hardware assignment|conflicting local terminal"
    ):
        NativeInputCompiler(fixture(*records, model=model))


def test_operator_can_review_and_export_with_both_dedicated_contacts_present(tmp_path):
    files = fixture(dedicated(), dedicated(8, 712))
    identity = MoiIdentity(files[3]).summary()
    device = f"device,{identity['instance']}"
    app = create_app(tmp_path)
    storage = app.state.native_applications.storage
    capture = storage.save(
        {
            "target": {"address": "127.0.0.1:47999", "router": None, "dnet": None},
            "device": device,
            "identity": {
                "device": device,
                "object-name": identity["name"],
                "model-name": identity["model"],
            },
            "source_identity_matches": True,
            "connector_config": {},
        },
        files,
    )
    query = {"capture_id": capture["id"], "snapshot_sha256": capture["evidence_sha256"]}
    path = "/api/bacnet/controller/native-application/input"
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        info = client.post(path + "/source", json=query, headers=headers).raise_for_status().json()
        assert info["available_slots"] == [2, 3, 4, 5, 6]
        body = {**query, "edit": allocation(slot=2)}
        preview = (
            client.post(path + "/copy/preview", json=body, headers=headers)
            .raise_for_status()
            .json()
        )
        assert preview["controller_queries"] is preview["controller_writes"] is False
        reviewed = {**body, "expected_review_sha256": preview["review_sha256"]}
        exported = client.post(
            path + "/copy/export", json=reviewed, headers=headers
        ).raise_for_status()
        assert verify_input_preservation(files, {**files, 3: exported.content}, body["edit"])[
            "other_configuration_preserved"
        ]
        changed = {**reviewed, "edit": allocation(slot=3)}
        assert client.post(path + "/copy/export", json=changed, headers=headers).status_code == 422
        assert client.get("/api/session").json()["field_network_open"] is False
        assert storage.load(capture["id"])[1] == files
        assert not storage.receipts()
