"""Source-specific terminal witnesses, old complete reports and immutable local analysis."""

import copy
import struct

import pytest
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Unsigned
from bms_tool.app import create_app
from bms_tool.moi_effective_terminals import EffectiveTerminalCopies
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.moi_terminal_copies import MoiTerminalCopies
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_inputs import NativeInputCompiler
from bms_tool.native_terminal_capabilities import PROFILE, ROWS, terminal_capabilities
from fastapi.testclient import TestClient

from .test_controller_application import encoded, native_record
from .test_moi_connection_copies import frames, packed
from .test_moi_terminal_copies import authored, selected_edit
from .test_moi_terminal_output_namespace import with_output
from .test_native_connection_copies import filesystem
from .test_native_terminal_copies import setup


def source(tmp_path, **options):
    files = options.get("files") or authored(compressed=True)
    native = MoiIdentity(files[3]).summary()
    options.setdefault(
        "identity",
        {"object-name": native["name"], "model-name": native["model"], "vendor-identifier": 5},
    )
    storage, _, files, query = setup(tmp_path, **options)
    records = NativeBackupRecords(storage)
    return storage, records, files, {k: query[k] for k in ["capture_id", "snapshot_sha256"]}


def analysis(records, request):
    return records.capabilities(request | {"capability_profile": PROFILE})


def assert_witness(storage, request, body, basis):
    snapshot, files = storage.load(request["capture_id"])
    w = body["qualification"][basis + "_terminal"]
    assert w and w["destination_slot"] in w["free_slots"]
    assert w["destination_slot"] != w["old_slot"]
    assert not w["field_transfer_enabled"] and not w["physical_terminal_or_wiring_verified"]
    if basis == "analog":
        c = NativeInputCompiler(files)
        output, proof = c.compile(
            {
                "action": "terminal",
                "object_instance": int(w["object"].split(",")[1]),
                "slot": w["destination_slot"],
                "configuration_sha256": w["configuration_sha256"],
            }
        )
        actual = proof["terminal_compilation"]
    else:
        c = (
            MoiTerminalCopies(files[3])
            if basis == "archive"
            else EffectiveTerminalCopies(snapshot, files).effective
        )
        output, actual = c.compile(
            **{
                k: w[k]
                for k in [
                    "source_sha256",
                    "ref",
                    "record_sha256",
                    "slot_property_sha256",
                    "device_type_property_sha256",
                    "old_slot",
                    "destination_slot",
                ]
            }
        )
    assert sha(output) == w["output_sha256"]
    assert actual["compilation_sha256"] == w["compilation_sha256"]
    assert actual["identities_modes_graph_and_record_framing_preserved"]


@pytest.mark.parametrize("binary", [False, True])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("wide", [False, True])
@pytest.mark.parametrize("model", ["M4-CVM03050-0", "FX-PCV1630-0", "MS-VMA1630-0"])
def test_actual_candidates_compile_with_exact_old_reports_and_no_retained_changes(
    tmp_path, binary, compressed, wide, model
):
    storage, records, files, request = source(
        tmp_path, files=authored(binary=binary, compressed=compressed, wide=wide, model=model)
    )
    before = filesystem(storage.directory)
    old = {
        n: records.capabilities(
            request | {"capability_profile": f"native-backup-operation-capabilities/{n}"}
        )
        for n in [11, 12, 13, 14]
    }
    body = analysis(records, request)
    assert len(body["operations"]) == 30 and len({r["id"] for r in body["operations"]}) == 30
    projected = copy.deepcopy(body)
    projected["capability_profile"] = old[14]["capability_profile"]
    projected["operations"] = [r for r in projected["operations"] if r["id"] not in ROWS]
    for basis in ["archive", "effective", "analog"]:
        del projected["qualification"][basis + "_terminal"]
        del projected["qualification"][basis + "_terminal_error"]
    assert projected == old[14] and records.capabilities(request) == old[12]
    assert [len(old[n]["operations"]) for n in old] == [22, 24, 25, 27]
    assert_witness(storage, request, body, "archive")
    assert_witness(storage, request, body, "effective")
    statuses = {r["id"]: r["status"] for r in body["operations"]}
    assert statuses[ROWS[0]] == statuses[ROWS[1]] == "source-qualified"
    assert statuses[ROWS[2]] == ("unsupported-source" if binary else "preflight-required")
    if not binary:
        assert_witness(storage, request, body, "analog")
    assert body["can_apply"] is body["current_identity_verified"] is False
    assert body["read_only"] and not body["controller_queries"] and not body["field_actions"]
    assert filesystem(storage.directory) == before and not storage.receipts()
    assert files == storage.load(request["capture_id"])[1]


@pytest.mark.parametrize(
    "case",
    [
        "unknown-saved",
        "unverified",
        "identity",
        "serial",
        "bbmd",
        "no-free",
        "host",
        "output",
        "unknown-model",
        "missing-config",
    ],
)
def test_specific_structure_identity_transport_and_availability_are_separate(tmp_path, case):
    files = authored(compressed=False)
    metadata = {}
    if case == "unknown-saved":
        files[11], files[12] = b"Unknown directory", b"Opaque values"
    elif case == "unverified":
        metadata["source_identity_matches"] = False
    elif case == "identity":
        metadata["identity"] = {
            "object-name": "Different controller",
            "model-name": "M4-CVM03050-0",
            "vendor-identifier": 5,
        }
    elif case == "serial":
        metadata["connector_config"] = {"transport": "mstp", "serial_port": "owned-unopened"}
    elif case == "bbmd":
        metadata["connector_config"] = {
            "local_address": "127.0.0.1:47819",
            "bbmd_address": "127.0.0.2:47819",
        }
    elif case == "host":
        files[3] = selected_edit(files[3], 3645, encoded(Unsigned(0)))
    elif case == "output":
        files = with_output(files)
    elif case == "unknown-model":
        files = authored(model="Unknown controller", internal=False)
        metadata["identity"] = {
            "object-name": "Authored controller",
            "model-name": "Unknown controller",
            "vendor-identifier": 5,
        }
    elif case == "missing-config":
        files[3] = selected_edit(files[3], 1293, encoded(CharacterString("Unknown")))
    elif case == "no-free":
        app = MoiIdentity(files[3])
        rows = list(frames(app.data))
        for slot in [2, 3]:
            raw = native_record(
                242,
                100 + slot,
                [
                    (32527, encoded(CharacterString(f"controller/3_{100 + slot}"))),
                    (75, encoded(ObjectIdentifier((3, 100 + slot)))),
                    (31, encoded(CharacterString(f"UI IN{slot}"))),
                    (519, encoded(Unsigned(slot))),
                ],
            )
            rows.append((2, raw))
        header = bytearray(app.data[:14])
        struct.pack_into("<I", header, 10, len(rows))
        files[3] = packed(bytes(header), rows)
    storage, records, _, request = source(tmp_path, files=files, **metadata)
    before = filesystem(storage.directory)
    body = analysis(records, request)
    q = body["qualification"]
    statuses = [r["status"] for r in body["operations"] if r["id"] in ROWS]
    if case in ["unverified", "identity"]:
        assert statuses == ["source-qualified", "unsupported-source", "source-mismatch"]
    elif case in ["serial", "bbmd"]:
        assert statuses == ["source-qualified", "source-qualified", "transport-unavailable"]
        assert q["analog_terminal"] is not None
    elif case == "unknown-saved":
        assert statuses == ["source-qualified", "unsupported-source", "unsupported-source"]
    elif case == "output":
        assert statuses == ["unsupported-source", "unsupported-source", "preflight-required"]
        assert_witness(storage, request, body, "analog")
    elif case == "missing-config":
        assert statuses == ["source-qualified", "source-qualified", "unsupported-source"]
    else:
        assert statuses == ["unsupported-source"] * 3
    assert filesystem(storage.directory) == before and not storage.receipts()


def test_later_usable_analog_is_found_when_first_configuration_is_unknown(tmp_path):
    files = authored(compressed=False)
    app = MoiIdentity(files[3])
    first = next(r for r in app.records if r["class_id"] == 240 and app.reader.scalar(r, 519) == 1)
    changes = {
        32527: encoded(CharacterString("controller/0_102")),
        75: encoded(ObjectIdentifier((0, 102))),
        31: encoded(CharacterString("UI IN2")),
        519: encoded(Unsigned(2)),
    }
    props = [
        (pid, changes.get(pid, app.data[p["value_start_offset"] : p["value_end_offset"] - 1]))
        for pid, p in first["properties"].items()
    ]
    second = native_record(240, 102, props)
    rows = frames(selected_edit(files[3], 1293, encoded(CharacterString("Unknown")))) + [
        (2, second)
    ]
    header = bytearray(app.data[:14])
    struct.pack_into("<I", header, 10, len(rows))
    files[3] = packed(bytes(header), rows)
    storage, records, _, request = source(tmp_path, files=files)
    body = analysis(records, request)
    witness = body["qualification"]["analog_terminal"]
    assert (
        witness["object"] == "analog-input,102"
        and witness["old_slot"] == 2
        and witness["destination_slot"] == 3
    )
    assert_witness(storage, request, body, "analog")


def test_strict_explicit_http_analysis_stays_local_and_source_bound(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    _, records, _, request = source(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Local terminal analysis attempted a field path or retained intent")

    for name in ["require", "_read", "connect", "disconnect", "release"]:
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    monkeypatch.setattr(app.state.native_applications.storage, "intent", forbidden)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        query = request | {"capability_profile": PROFILE}
        before = filesystem(records.storage.directory)
        response = client.post(
            "/api/bacnet/controller/native-application/inspection/capabilities",
            json=query,
            headers=headers,
        )
        assert response.status_code == 200 and response.json() == analysis(records, request)
        assert client.get("/api/session").json()["field_network_open"] is False
        for extra in [
            {"can_apply": True},
            {"capability_profile": "native-backup-operation-capabilities/999"},
            {"snapshot_sha256": "0" * 64},
        ]:
            assert client.post(
                "/api/bacnet/controller/native-application/inspection/capabilities",
                json=query | extra,
                headers=headers,
            ).status_code in [400, 422]
        assert filesystem(records.storage.directory) == before
    with pytest.raises(ValueError):
        terminal_capabilities({}, {}, {}, capability_profile="unknown")
