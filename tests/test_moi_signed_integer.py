"""Independent literal Integer application tags; reading never grants a write."""

import gzip
import hashlib
import struct

import pytest
from bacpypes3.primitivedata import CharacterString
from bms_tool.moi_application import MoiApplication
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.moi_signal_defaults import MoiSignalDefaults

from .test_controller_application import encoded, native_record
from .test_moi_parameters import parameters_source
from .test_moi_signal_defaults import source as real_source
from .test_native_records_api import records_client as records_client  # noqa: F401

CASES = [
    ("3100", 0),
    ("31ff", -1),
    ("317f", 127),
    ("3180", -128),
    ("320080", 128),
    ("32ff7f", -129),
    ("33008000", 32768),
    ("33ff7fff", -32769),
    ("3400800000", 8388608),
    ("34ff7fffff", -8388609),
    ("347fffffff", 2147483647),
    ("3480000000", -2147483648),
]


def signed_source(raw, *, compressed=False):
    record = native_record(
        194,
        5136,
        [
            (32527, encoded(CharacterString("controller/signed"))),
            (2390, encoded(CharacterString("Authored signed settings"))),
            (65000, raw),
        ],
    )
    data = struct.pack("<6sHHI", b"\x02\x00MOI\x00", 194, 1, 1)
    data += struct.pack("<H", len(record) + 2) + record
    return gzip.compress(data, mtime=0) if compressed else data


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("raw_hex,expected", CASES)
def test_signed_scalar_widths_sign_boundaries_and_exact_byte_evidence(
    raw_hex, expected, compressed
):
    raw = bytes.fromhex(raw_hex)
    data = signed_source(raw, compressed=compressed)
    app = MoiApplication(data)
    record = app.record_inventory()["records"][0]
    properties = app.record_details(record["id"])["properties"]
    prop = next(row for row in properties if row["id"] == 65000)
    assert prop["scalar"] == {"datatype": "Integer", "value": expected}
    assert type(prop["scalar"]["value"]) is int
    assert app.scalar(app.records["controller/signed"], 65000) == expected
    assert prop["encoded_sha256"] == hashlib.sha256(raw + b"\x2f").hexdigest()
    assert app.data[prop["value_start_offset"] : prop["value_end_offset"]] == raw + b"\x2f"
    assert app.data == (gzip.decompress(data) if compressed else data)
    assert not app.summary()["capabilities"]["logic_write"]


@pytest.mark.parametrize(
    "raw_hex", ["30", "35050000000001", "35088000000000000000", "31ff3101", "3e31013f"]
)
def test_unrecognized_widths_and_structures_remain_opaque_with_original_hashes(raw_hex):
    raw = bytes.fromhex(raw_hex)
    app = MoiApplication(signed_source(raw))
    prop = app.records["controller/signed"]["properties"][65000]
    assert prop["scalar"] is None
    assert prop["encoded_sha256"] == hashlib.sha256(raw + b"\x2f").hexdigest()
    assert app.data[prop["value_start_offset"] : prop["value_end_offset"]] == raw + b"\x2f"


def test_saved_parameter_merge_exposes_archive_and_saved_signed_values_without_changing_the_codec():
    archive, static, dynamic = parameters_source()
    before = MoiApplication(archive)
    compiled, report = ParameterApplication(archive, static, dynamic).compile()
    after = MoiApplication(compiled)
    assert before.scalar(before.records["controller"], 902) == -1
    assert after.scalar(after.records["controller"], 902) == -300
    assert after.records["controller"]["properties"][902]["scalar"]["datatype"] == "Integer"
    assert report["matched_parameters"] == 7


def test_reading_signed_fields_does_not_promote_them_into_real_default_edits():
    raw = gzip.decompress(real_source(compressed=True))
    replacement = raw.replace(b"\x44\x41\xbc\x00\x00", b"\x34\xff\xff\xfe\xd4", 1)
    assert replacement != raw
    reader = MoiApplication(replacement)
    assert reader.scalar(reader.records["site/575_1.2_10"], 3113) == -300
    editor = MoiSignalDefaults(replacement)
    assert editor.capabilities()["candidate_count"] == 1
    assert "site/575_1.2_10" not in editor.candidates
    assert "site/575_1.2_11" in editor.candidates


def test_production_record_api_returns_signed_integer_and_retains_local_read_scope(
    records_client, monkeypatch
):
    client, headers, body, app = records_client
    data = signed_source(bytes.fromhex("32fed4"), compressed=True)
    old, _ = app.state.controller_application.files.capture_data(body["capture_id"])
    receipt = old | {"sha256": hashlib.sha256(data).hexdigest()}
    monkeypatch.setattr(
        app.state.controller_application.files, "capture_data", lambda _: (receipt, data)
    )
    prefix = "/api/bacnet/controller/application"
    rows = client.post(prefix + "/records", headers=headers, json=body).json()
    response = client.post(
        prefix + "/record",
        headers=headers,
        json=body | {"record_id": rows["records"][0]["id"], "query": "65000"},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["properties"][0]["scalar"] == {"datatype": "Integer", "value": -300}
    assert result["sha256"] == receipt["sha256"]
    assert result["read_only"] and not result["field_actions"]
    assert not client.get("/api/session").json()["field_network_open"]
