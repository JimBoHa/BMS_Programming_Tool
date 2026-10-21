"""Browser-facing hardware workbench: offline artifacts and real UDP archive reads."""

import asyncio
import copy
import gzip

import httpx
import pytest
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier
from bms_tool import hardware_workbench
from bms_tool.app import create_app
from bms_tool.hardware_survey import analyze_archive
from bms_tool.hardware_workbench import canonical

from .test_bacnet_files import link as link
from .test_bacnet_files import port
from .test_hardware_survey import authored_archive, native_record, survey_from_archive


def offline_report():
    archive = analyze_archive(authored_archive())
    report = survey_from_archive(archive)
    objects = ["device,123", "binary-input,55", "analog-input,56"]
    report.update(
        target={"address": "127.0.0.1:47809", "device": "device,123", "router": None, "dnet": None},
        status="complete",
    )
    report["inventory"].update(total=len(objects), read=len(objects), objects=objects)
    return report


async def session(client):
    return {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}


async def wait_job(client, key):
    for _ in range(400):
        response = await client.get(f"/api/bacnet/hardware/jobs/{key}")
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] not in ("queued", "running"):
            return job
        await asyncio.sleep(0.02)
    raise AssertionError("Hardware test job did not finish")


async def test_offline_import_archive_correlation_plans_exports_and_restart(tmp_path):
    app = create_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = await session(client)
            base = "/api/bacnet/hardware"
            assert (await client.get(base + "/status")).json()["reports"] == []
            rejected = await client.post(
                base + "/archive", files={"file": ("fixture.moi", authored_archive())}
            )
            assert rejected.status_code == 403
            archive = await client.post(
                base + "/archive",
                files={"file": ("fixture.moi", authored_archive())},
                headers=headers,
            )
            assert archive.status_code == 200, archive.text
            archive = archive.json()
            raw = await client.get(base + f"/archives/{archive['id']}/export?format=source")
            assert raw.content == authored_archive()
            response = await client.post(
                base + "/import-report",
                files={"file": ("survey.json", canonical(offline_report()))},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            imported = response.json()
            assert imported["imported"] and not imported["native_apply_supported"]
            enriched = await client.post(
                base + "/enrich",
                json={"report_id": imported["id"], "archive_id": archive["id"]},
                headers=headers,
            )
            assert enriched.status_code == 200, enriched.text
            enriched = enriched.json()
            assert enriched["archive_comparison"]["configured_models_applied"]
            assert enriched["imported"]
            move = {
                "report_id": enriched["id"],
                "source_object": "binary-input,55",
                "destination_sa_mac": 7,
                "destination_slot": 16,
            }
            plan = (await client.post(base + "/relocation", json=move, headers=headers)).json()
            assert plan["status"] == "review-required" and plan["controller_writes"] is False
            channels = [
                {
                    "name": "Temperature",
                    "sa_mac": 4,
                    "slot": 2,
                    "signal_low": 0,
                    "signal_high": 5,
                    "engineering_low": -40,
                    "engineering_high": 160,
                    "units": "degF",
                },
                {
                    "name": "Humidity",
                    "sa_mac": 4,
                    "slot": 4,
                    "signal_low": 0,
                    "signal_high": 5,
                    "engineering_low": 0,
                    "engineering_high": 100,
                    "units": "%RH",
                },
            ]
            payload = {"report_id": enriched["id"], "channels": channels}
            assert (
                await client.post(base + "/sensor-plan", json=payload, headers=headers)
            ).status_code == 422
            payload["relocation"] = {
                key: value for key, value in move.items() if key != "report_id"
            }
            response = await client.post(base + "/sensor-plan", json=payload, headers=headers)
            assert response.status_code == 200, response.text
            sensor = response.json()
            assert sensor["native_apply_supported"] is False
            assert sensor["channels"][0]["checks"][1]["engineering_value"] == 60
            assert sensor["channels"][1]["checks"][1]["engineering_value"] == 50
            assert sensor["channels"][1]["conditional_on_relocation"]
            payload["relocation"]["destination_slot"] = 17
            assert (
                await client.post(base + "/sensor-plan", json=payload, headers=headers)
            ).status_code == 422
            exported = await client.get(base + f"/reports/{enriched['id']}/export?format=csv")
            assert exported.status_code == 200 and b"Alarm" in exported.content
            assert "text/csv" in exported.headers["content-type"]
            assert (await client.get(base + f"/reports/{enriched['id']}/export")).json() == enriched
            assert app.state.bacnet.app is None and not app.state.bacnet.commands
    reopened = create_app(tmp_path)
    async with reopened.router.lifespan_context(reopened):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=reopened), base_url="http://testserver"
        ) as client:
            status = (await client.get("/api/bacnet/hardware/status")).json()
            assert len(status["reports"]) == 2 and len(status["archives"]) == 1
            assert reopened.state.bacnet.app is None


async def test_reject_malformed_imports_and_keep_unverified_candidates_unusable(tmp_path):
    app = create_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = await session(client)
            base = "/api/bacnet/hardware"
            for raw in (b"{}", b'{"x": NaN}', b"[]", b"{broken"):
                response = await client.post(
                    base + "/import-report", files={"file": ("invalid.json", raw)}, headers=headers
                )
                assert response.status_code == 422
            invalid = offline_report()
            invalid["inputs"].append(copy.deepcopy(invalid["inputs"][0]))
            assert (
                await client.post(
                    base + "/import-report",
                    files={"file": ("duplicate.json", canonical(invalid))},
                    headers=headers,
                )
            ).status_code == 422
            partial = offline_report()
            partial["inventory"]["complete"] = False
            partial["candidates"] = [
                {"sa_mac": 4, "slot": 4, "terminal_type": "UI", "status": "candidate"}
            ]
            response = await client.post(
                base + "/import-report",
                files={"file": ("partial.json", canonical(partial))},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            report = response.json()
            payload = {
                "report_id": report["id"],
                "channels": [
                    {
                        "name": "RH",
                        "sa_mac": 4,
                        "slot": 4,
                        "engineering_low": 0,
                        "engineering_high": 100,
                        "units": "%RH",
                    }
                ],
            }
            assert (
                await client.post(base + "/sensor-plan", json=payload, headers=headers)
            ).status_code == 422


async def test_real_udp_survey_archive_copy_and_no_native_writes(link, tmp_path):
    peer, _, _, target = link
    peer.payload = gzip.compress(
        b"\0\0MOI\0"
        + native_record(
            194,
            4190150,
            [
                (75, ObjectIdentifier("device,4190150")),
                (70, CharacterString("Authored File Peer")),
                (2390, CharacterString("Independent file peer")),
                (32527, CharacterString("fixture")),
            ],
        )
    )
    peer.objectName.pop(str(peer.stream.objectName))
    peer.stream.objectName = "fixture/Archive"
    peer.objectName["fixture/Archive"] = peer.stream
    peer.stream.fileType = ".moi"
    peer.stream.fileSize = len(peer.payload)
    app = create_app(tmp_path / "web-workbench")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = await session(client)
            base = "/api/bacnet/hardware"
            before = await client.post(base + "/survey", json=target, headers=headers)
            assert before.status_code == 422
            await client.post(
                "/api/bacnet/connect",
                json={"local_address": f"127.0.0.1:{port()}"},
                headers=headers,
            )
            started = await client.post(
                base + "/survey",
                json=target | {"property_timeout": 0.2, "timeout_seconds": 5},
                headers=headers,
            )
            assert started.status_code == 200, started.text
            job = await wait_job(client, started.json()["id"])
            assert job["status"] == "complete", job
            report = job["report"]
            assert "file,31" in report["inventory"]["objects"]
            started = await client.post(
                base + "/read-archive", json={"report_id": report["id"]}, headers=headers
            )
            assert started.status_code == 200, started.text
            job = await wait_job(client, started.json()["id"])
            assert job["status"] == "complete", job
            assert job["archive"]["origin"]["complete"]
            assert job["archive"]["origin"]["controller_writes"] is False
            source = await client.get(base + f"/archives/{job['archive_id']}/export?format=source")
            assert source.content == peer.payload
            assert peer.atomic_requests
            assert not app.state.bacnet.commands and not app.state.bacnet.lock.locked()
            assert not app.state.bacnet.app.asap.clientTransactions
            assert set(peer.all_requests) <= {"ReadPropertyRequest", "AtomicReadFileRequest"}


async def test_survey_job_cancel_retains_partial_and_retires_owned_requests(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    entered = asyncio.Event()

    async def hold(body, progress=None):
        report = offline_report()
        report["inventory"]["complete"] = False
        report["inputs_complete"] = False
        progress(report)
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(app.state.hardware_workbench.surveys, "survey", hold)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = await session(client)
            await client.post(
                "/api/bacnet/connect",
                json={"local_address": f"127.0.0.1:{port()}"},
                headers=headers,
            )
            base = "/api/bacnet/hardware"
            started = await client.post(
                base + "/survey", json=offline_report()["target"], headers=headers
            )
            await asyncio.wait_for(entered.wait(), 1)
            second = await client.post(
                base + "/survey", json=offline_report()["target"], headers=headers
            )
            assert second.status_code == 422
            cancelled = await client.post(
                base + f"/jobs/{started.json()['id']}/cancel", json={}, headers=headers
            )
            assert cancelled.status_code == 200, cancelled.text
            job = cancelled.json()
            assert job["status"] == "cancelled" and not job["report"]["inventory"]["complete"]
            assert not any(
                row["status"] == "candidate" for row in job["report"].get("candidates", [])
            )
            assert not app.state.bacnet.commands


async def test_cancel_before_task_starts_is_terminal_and_durable(tmp_path):
    app = create_app(tmp_path)
    workbench = app.state.hardware_workbench
    await app.state.bacnet.connect(f"127.0.0.1:{port()}")
    try:
        job = workbench.start("survey", offline_report()["target"])
        result = await workbench.cancel(job["id"])
        assert result["status"] == "cancelled"
        assert workbench._load("job", job["id"])["status"] == "cancelled"
        assert not app.state.bacnet.app.asap.clientTransactions
    finally:
        await workbench.close()
        app.state.bacnet.close()


@pytest.mark.parametrize(
    "mode", ["wrong-offset", "early-eof", "changed-metadata", "changed-membership", "cancel"]
)
async def test_archive_read_guards_and_cancellation_never_save_false_complete(link, tmp_path, mode):
    peer, _, _, target = link
    peer.payload = gzip.compress(
        b"\0\0MOI\0"
        + native_record(
            194,
            4190150,
            [
                (75, ObjectIdentifier("device,4190150")),
                (70, CharacterString("Authored File Peer")),
                (2390, CharacterString("Independent file peer")),
                (32527, CharacterString("fixture")),
            ],
        )
    )
    peer.objectName.pop(str(peer.stream.objectName))
    peer.stream.objectName = "fixture/Archive"
    peer.objectName["fixture/Archive"] = peer.stream
    peer.stream.fileType = ".moi"
    peer.stream.fileSize = len(peer.payload)
    app = create_app(tmp_path / "guarded-web-archive")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = await session(client)
            base = "/api/bacnet/hardware"
            await client.post(
                "/api/bacnet/connect",
                json={"local_address": f"127.0.0.1:{port()}"},
                headers=headers,
            )
            started = (
                await client.post(
                    base + "/survey",
                    json=target | {"property_timeout": 0.2, "timeout_seconds": 5},
                    headers=headers,
                )
            ).json()
            report_job = await wait_job(client, started["id"])
            assert report_job["status"] == "complete", report_job
            if mode == "wrong-offset":
                peer.mutation = lambda reply: setattr(
                    reply.accessMethod.streamAccess, "fileStartPosition", 1
                )
            elif mode == "early-eof":
                peer.mutation = lambda reply: setattr(reply, "endOfFile", True)
            elif mode == "changed-metadata":
                peer.callback = lambda: setattr(peer.stream, "fileSize", len(peer.payload) + 1)
            elif mode == "changed-membership":

                def reorder():
                    peer.callback = None
                    peer.delete_object(peer.stream)
                    peer.add_object(peer.stream)

                peer.callback = reorder
            else:
                peer.drop = True
            started = await client.post(
                base + "/read-archive", json={"report_id": report_job["report_id"]}, headers=headers
            )
            assert started.status_code == 200, started.text
            key = started.json()["id"]
            if mode == "cancel":
                for _ in range(100):
                    if peer.atomic_requests:
                        break
                    await asyncio.sleep(0.01)
                assert peer.atomic_requests
                cancelled = await client.post(
                    base + f"/jobs/{key}/cancel", json={}, headers=headers
                )
                assert cancelled.json()["status"] == "cancelled"
            job = await wait_job(client, key)
            assert job["status"] == ("cancelled" if mode == "cancel" else "error"), job
            assert not (await client.get(base + "/status")).json()["archives"]
            assert not app.state.bacnet.lock.locked()
            assert not app.state.bacnet.commands
            assert not app.state.bacnet.app.asap.clientTransactions
            assert set(peer.all_requests) <= {"ReadPropertyRequest", "AtomicReadFileRequest"}


def test_replacing_evidence_counts_only_the_resulting_storage(tmp_path, monkeypatch):
    workbench = create_app(tmp_path).state.hardware_workbench
    key = "a" * 32
    workbench._write("job", key, {"status": "running"})
    before = workbench._path("job", key).stat().st_size
    # Enough for the resulting file, but not both complete versions at once.
    monkeypatch.setattr(hardware_workbench, "MAX_STORAGE", before + 20)
    workbench._write("job", key, {"status": "completed"})
    assert workbench._load("job", key)["status"] == "completed"


async def test_failed_job_persistence_does_not_create_a_phantom_job(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    workbench = app.state.hardware_workbench
    monkeypatch.setattr(workbench.bacnet, "require", lambda: object())
    monkeypatch.setattr(hardware_workbench, "MAX_STORAGE", 1)
    with pytest.raises(ValueError, match="storage budget"):
        workbench.start("survey", offline_report()["target"])
    assert workbench.jobs == {} and workbench.tasks == {}


def test_failed_archive_commit_removes_exact_source_and_pending_files(tmp_path, monkeypatch):
    workbench = create_app(tmp_path).state.hardware_workbench

    def failed_commit(*args):
        raise OSError("Authored disk failure")

    monkeypatch.setattr(workbench, "_write", failed_commit)
    with pytest.raises(OSError, match="Authored disk failure"):
        workbench.import_archive(authored_archive(), "fixture.moi")
    assert list(workbench.directory.iterdir()) == []
