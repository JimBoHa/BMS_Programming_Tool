"""Round-trip generic nested inline drawings and exercise local review/export."""

import json
import os
import sys
from argparse import Namespace

import pytest
from bacpypes3.primitivedata import Enumerated
from bms_tool.__main__ import main
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.native_inline_activity_drawing import ActivityDrawing, Port
from bms_tool.native_inline_activity_plan import plan_activities
from bms_tool.native_inline_draft import local_draft
from bms_tool.native_inline_monitor import record
from bms_tool.native_inline_sequence_62 import LegacyInlineSequenceCompiler
from bms_tool.native_inputs import archive, encoded, replace_properties

from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_inline_sequence import authored_source


def drawing_source(model="FX-PCV1630-0"):
    files = authored_source(model=model)
    app = MoiIdentity(files[3])
    raw = [app.data[r["offset"] : r["end_offset"]] for r in app.records]
    # The minimal flat-sequence fixture intentionally omits the two existing
    # producer ports. A nested drawing must take its type from actual records.
    for label, attr, num in [("DA-T", 8000, 9000), ("Heat demand", 800, 9001)]:
        (host,) = [
            r
            for r in app.records
            if app.reader.scalar(r, 2390) == label and r["class_id"] in (536, 556)
        ]
        ref = app.reader.scalar(host, 32527)
        raw.append(
            record(
                527,
                num,
                2,
                f"{ref}.2_{num}",
                {3365: encoded(Enumerated(attr)), 3670: encoded(Enumerated(233))},
            )
        )
    return {**files, 3: archive(app, raw)}


def compiler(model="FX-PCV1630-0"):
    files = drawing_source(model=model)
    donor = authored_source(catalog=True, model=model, wide=True)[3]
    program = LegacyInlineSequenceCompiler(files, donor, 200)
    program.body()
    return program


@pytest.mark.parametrize("model", ["FX-PCV1630-0", "MS-VMA1630-0"])
@pytest.mark.parametrize("shadow", [False, True])
def test_grouped_program_reopens_with_original_points_and_connected_edges(model, shadow):
    build = compiler(model)
    flat, baseline = build.export(shadow=shadow)
    result, report = build.export(shadow=shadow, grouped=True)
    drawing = report["activity_layout"]
    root = baseline["root_ref"]
    original, grouped = MoiIdentity(flat), MoiIdentity(result)
    old = original.reader.diagram(root, retained_activity_refs=True)
    new = grouped.reader.diagram(root, retained_activity_refs=True)
    assert drawing["signal_connections_traced"] == len(old["connections"])
    assert drawing["flat_sha256"] == baseline["candidate_sha256"] == sha(flat)
    assert drawing["flattened_schedule_verified"] and drawing["largest_activity_members"] <= 40
    assert drawing["activities_added"] >= 5 and drawing["boundary_records_added"] > 0
    assert report["root_members"] == len(new["blocks"]) < len(old["blocks"])
    assert (
        len(report["added_objects"]) == len(set(report["added_objects"])) == report["added_records"]
    )
    assert report["candidate_sha256"] == sha(result)
    assert report["new_avs"] == baseline["new_avs"]
    assert report["old_wires_replaced"] == (0 if shadow else 2)
    for r in original.records:
        if r["class_id"] in (239, 241, 251):
            ref = original.reader.scalar(r, 32527)
            assert grouped.reader.records[ref]["sha256"] == r["sha256"]
    assert not report["field_execution_verified"] and not report["production_transfer_qualified"]
    assert {b["name"] for b in new["blocks"]} >= {"VLV-LOCKOUT-CFM", "MAX-DA-T"}


def test_wrong_port_assignment_and_missing_native_member_rejected():
    build = compiler()
    flat, report = build.export(shadow=True)
    drawing = ActivityDrawing(build.application, flat, report)
    candidate, _ = drawing.encode()
    app = MoiIdentity(candidate)
    port = next(key for key in drawing.identifiers if isinstance(key, Port) and key.output)
    name = str(drawing.identifiers[port])
    rec = next(r for r in app.records if app.reader.scalar(r, 75) == name)
    bad = archive(
        app,
        [
            replace_properties(app, r, {3365: encoded(Enumerated(drawing.attributes[port] + 511))})
            if r["offset"] == rec["offset"]
            else app.data[r["offset"] : r["end_offset"]]
            for r in app.records
        ],
    )
    with pytest.raises(ValueError, match="type or assignment"):
        drawing.verify(MoiIdentity(bad))
    with pytest.raises(ValueError, match="unaccounted"):
        plan_activities(build.application, MoiIdentity(flat), {**report, "added_objects": []})


def test_cli_requires_unchanged_review_before_writing_new_local_file(tmp_path, monkeypatch, capsys):
    files = drawing_source()
    paths = [tmp_path / name for name in ("application", "static", "dynamic", "library")]
    backup = [files[3], files[11], files[12], authored_source(catalog=True, wide=True)[3]]
    for path, data in zip(paths, backup, strict=True):
        path.write_bytes(data)
    cli = ["bms-tool", "inline-reheat-draft", "--first-instance", "200"]
    flags = ["application", "static", "dynamic", "prototype"]
    for label, path in zip(flags, paths, strict=True):
        cli.extend(["--" + label, str(path)])
    monkeypatch.setattr(sys, "argv", cli)
    main()
    reviewed = json.loads(capsys.readouterr().out)
    assert not reviewed["controller_queries"] and not reviewed["local_copy_written"]
    assert reviewed["purpose"] == "observe" and reviewed["layout"] == "activities"
    output = tmp_path / "drawing.moi"
    opts = Namespace(
        **dict(zip(flags, paths, strict=True)),
        first_instance=200,
        layout="activities",
        purpose="control",
        output=output,
        review_sha256=reviewed["review_sha256"],
    )
    with pytest.raises(ValueError, match="Review the current"):
        local_draft(opts)
    assert not output.exists()
    monkeypatch.setattr(
        sys, "argv", cli + ["--output", str(output), "--review-sha256", reviewed["review_sha256"]]
    )
    main()
    assert json.loads(capsys.readouterr().out)["local_copy_written"]
    assert sha(output.read_bytes()) == reviewed["compilation"]["candidate_sha256"]
    with pytest.raises(FileExistsError):
        main()
    output.unlink()

    def fail_publish(*args):
        raise OSError("storage unavailable")

    monkeypatch.setattr(os, "link", fail_publish)
    with pytest.raises(OSError, match="storage unavailable"):
        main()
    assert set(tmp_path.iterdir()) == set(paths)
    assert [p.read_bytes() for p in paths] == backup


def test_undeclared_original_output_port_refuses_nested_draft_and_flat_program_still_works():
    source = authored_source()
    program = LegacyInlineSequenceCompiler(source, authored_source(catalog=True, wide=True)[3], 200)
    program.body()
    flat, report = program.export(shadow=True)
    assert report["candidate_sha256"] == sha(flat)
    with pytest.raises(ValueError, match="unique typed native port"):
        program.export(shadow=True, grouped=True)


async def test_retained_draft_http_rechecks_target_source_and_seal_with_interface_closed(
    native_link, tmp_path
):
    import httpx
    from bms_tool.app import create_app
    from bms_tool.native_backup_records import NativeBackupRecords

    from .test_native_inline_monitor import observation_peer

    peer, _, _, service, target = native_link
    observation_peer(peer, "")
    peer.files = authored_source(catalog=True, wide=True)
    donor = await service.capture(**target, operation_id="capture-primitives")
    peer.files = drawing_source()
    cap = await service.capture(**target, operation_id="capture-application")
    await service.bacnet.disconnect()
    before = list(peer.events)
    selector = {"capture_id": cap["id"], "snapshot_sha256": cap["snapshot_evidence_sha256"]}
    archive = NativeBackupRecords(service.storage).source(selector)
    assert archive["inline_draft_profile"] == "native-inline-local-program-draft/1"
    assert archive["inline_edge_sampling"] is True
    options = {
        **target,
        **selector,
        "prototype_capture_id": donor["id"],
        "prototype_sha256": donor["snapshot_evidence_sha256"],
        "operation_id": "review-offline-copy",
        "purpose": "control",
        "layout": "activities",
        "first_instance": 200,
    }
    app = create_app(tmp_path)
    base = "/api/bacnet/controller/native-application/inline-sequence/draft"
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        client.headers["X-Studio-Token"] = (await client.get("/api/session")).json()["token"]
        r = await client.post(base + "/review", json=options)
        assert r.status_code == 200, r.text
        report = r.json()
        assert all(report["target"][k] == v for k, v in target.items())
        assert report["capture_id"] == cap["id"] and report["controller_queries"] is False
        assert (
            report["compilation"]["old_wires_replaced"] == 2
            and report["production_transfer_qualified"] is False
        )
        export = {**options, "review_sha256": report["review_sha256"]}
        for change in (
            {"sampling": "clock-edge"},
            {"layout": "flat"},
            {"purpose": "observe"},
            {"first_instance": 30000},
            {"device": "device,5085"},
            {"snapshot_sha256": "c" * 64},
            {"prototype_sha256": "d" * 64},
        ):
            refused = await client.post(base + "/export", json={**export, **change})
            assert refused.status_code == 422, refused.text
            assert (
                "reviewed local draft" in refused.json()["detail"]
                or "exact target and verified captures" in refused.json()["detail"]
            )
        copied = await client.post(base + "/export", json=export)
        assert (
            copied.status_code == 200
            and copied.headers["content-type"] == "application/octet-stream"
        )
        assert sha(copied.content) == report["compilation"]["candidate_sha256"]
        edge_options = {**options, "sampling": "clock-edge"}
        edge = (await client.post(base + "/review", json=edge_options)).raise_for_status().json()
        assert edge["sampling"] == "clock-edge" and edge["review_sha256"] != report["review_sha256"]
        edge_file = await client.post(
            base + "/export", json={**edge_options, "review_sha256": edge["review_sha256"]}
        )
        assert edge_file.status_code == 200
        assert (
            sha(edge_file.content) == edge["compilation"]["candidate_sha256"] != sha(copied.content)
        )
        assert edge["compilation"]["new_avs"] == report["compilation"]["new_avs"]
        assert (
            await client.post(base + "/review", json={**options, "purpose": "unknown"})
        ).status_code == 422
    assert peer.events == before
