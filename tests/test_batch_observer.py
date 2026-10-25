import importlib.util
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from bacpypes3.apdu import ReadPropertyMultipleACK, ReadPropertyMultipleRequest
from bacpypes3.constructeddata import AnyAtomic
from bacpypes3.primitivedata import (
    BitString,
    Boolean,
    CharacterString,
    Enumerated,
    ObjectIdentifier,
    Real,
    Unsigned,
)

spec = importlib.util.spec_from_file_location(
    "batch_observer", Path(__file__).parents[1] / "scripts/observe_controller_batch.py"
)
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


@pytest.fixture
def configured(tmp_path):
    targets = []
    for index, io_count in enumerate((2, 4)):
        name = "Controller " + str(index)
        instance = 5301 + index
        verification = {
            "status": "verified",
            "controller": name,
            "new_instance": instance,
            "io_count": io_count,
        }
        proof = {
            "controller": name,
            "all_non_identity_application_bytes_preserved": True,
            "exact_native_readback": True,
            "unexplained_saved_parameter_changes": [],
        }
        for suffix, value in (("verified", verification), ("proof", proof)):
            (tmp_path / f"{index}-{suffix}.json").write_text(json.dumps(value))
        targets.append(
            {
                "controller": name,
                "new_instance": instance,
                "target": {
                    "address": "2001:" + str(index + 1),
                    "device": "device," + str(instance),
                    "router": "192.0.2.1",
                    "dnet": 2001,
                },
                "keeper": {
                    "address": "2201:" + str(index + 1),
                    "device": "device," + str(5101 + index),
                    "router": "192.0.2.1",
                    "dnet": 2201,
                },
                "keeper_name": "Keeper " + str(index),
                "io_objects": ["analog-input," + str(i + 1) for i in range(io_count)],
                "verification_file": f"{index}-verified.json",
                "preservation_file": f"{index}-proof.json",
            }
        )
    cfg = {
        "targets": targets,
        "local_address": "192.0.2.10/24:47820",
        "local_device": 4190000,
        "router_target": {"address": "192.0.2.1", "device": "device,501"},
        "duration_seconds": 12,
        "checkin_seconds": 6,
        "poll_seconds": 2,
        "controllers_per_poll": 1,
    }
    (tmp_path / "batch-settings.json").write_text(json.dumps(cfg))
    return tmp_path, cfg


class Clock:
    def __init__(self):
        self.value = 0

    def monotonic(self):
        return self.value

    async def sleep(self, delay):
        assert delay >= 0
        self.value += delay


def peer(monkeypatch, fault=None):
    clock = Clock()
    events = {"closed": False, "reads": 0, "injected": False}

    class Bacnet:
        def __init__(self, store):
            self.store = store

        async def connect(self, *args, **kwargs):
            return None

        def require(self):
            return SimpleNamespace(asap=SimpleNamespace())

        def close(self):
            events["closed"] = True

    class Details:
        def __init__(self, *args):
            pass

        @asynccontextmanager
        async def _path(self, options):
            yield {"options": options}

    async def exchange(self, session, request, expected):
        assert isinstance(request, ReadPropertyMultipleRequest)
        assert expected is ReadPropertyMultipleACK
        events["reads"] += 1
        clock.value += 0.05
        options = session["options"]
        instance = int(options.device.split(",")[1])
        block = request.listOfReadAccessSpecs[0]
        obj = str(block.objectIdentifier)
        name = (
            "Controller " + str(instance - 5301)
            if instance >= 5301
            else "Keeper " + str(instance - 5101)
            if instance >= 5101
            else "Engine"
        )
        object_id = ObjectIdentifier("device," + str(instance))
        flags = [0, 0, 0, 0]
        if fault == "wrong-id" and instance == 5301:
            object_id = ObjectIdentifier("device,5399")
        if (
            fault == "late-override"
            and clock.value > 2
            and obj == "analog-input,1"
            and not events["injected"]
        ):
            flags = [0, 0, 1, 0]
            events["injected"] = True
        values = {
            "object-identifier": object_id,
            "object-name": CharacterString(name),
            "system-status": Enumerated(0),
            "database-revision": Unsigned(1),
            "present-value": Real(1.25),
            "status-flags": BitString(flags),
            "reliability": Enumerated(0),
            "out-of-service": Boolean(False),
        }
        results = []
        for prop in block.listOfPropertyReferences:
            key = str(prop.propertyIdentifier)
            value = values[key]
            encoded = SimpleNamespace(cast_out=lambda kind, value=value: AnyAtomic(value))
            results.append(
                SimpleNamespace(
                    propertyIdentifier=prop.propertyIdentifier,
                    readResult=SimpleNamespace(propertyAccessError=None, propertyValue=encoded),
                )
            )
        return SimpleNamespace(
            listOfReadAccessResults=[
                SimpleNamespace(objectIdentifier=block.objectIdentifier, listOfResults=results)
            ]
        )

    monkeypatch.setattr(batch, "Bacnet", Bacnet)
    monkeypatch.setattr(batch, "DeviceDetails", Details)
    monkeypatch.setattr(batch.ApplicationFiles, "exchange", exchange)
    monkeypatch.setattr(batch.PropertyEvidence, "pin", lambda session, router: None)
    monkeypatch.setattr(batch, "time", clock)
    monkeypatch.setattr(batch, "asyncio", SimpleNamespace(sleep=clock.sleep))
    return clock, events


@pytest.mark.asyncio
async def test_native_ids_differing_io_and_full_clock(configured, monkeypatch):
    directory, _ = configured
    clock, events = peer(monkeypatch)
    result = await batch.observe(directory)
    assert result["phase"] == "completed" and result["stable"] is True
    assert result["elapsed_seconds"] >= 12
    assert clock.value > result["elapsed_seconds"]  # Baseline time is excluded.
    assert len(result["latest"]["0"]["io"]) == 2
    assert len(result["latest"]["1"]["io"]) == 4
    assert [row["scheduled_seconds"] for row in result["checkins"]] == [6, 12]
    assert all(row["healthy"] for row in result["checkins"])
    assert events["closed"] and events["reads"] > 20
    assert (directory / "batch-observation-status.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        await batch.observe(directory)


@pytest.mark.asyncio
async def test_wrong_native_id_stops_before_clock(configured, monkeypatch):
    directory, _ = configured
    _, events = peer(monkeypatch, "wrong-id")
    result = await batch.observe(directory)
    assert result["phase"] == "interrupted" and result["stable"] is False
    assert "started_at" not in result and result["checkins"] == []
    assert events["closed"]


@pytest.mark.asyncio
async def test_transient_override_never_becomes_a_clean_pass(configured, monkeypatch):
    directory, _ = configured
    peer(monkeypatch, "late-override")
    result = await batch.observe(directory)
    assert result["phase"] == "completed" and result["stable"] is False
    assert len(result["failures"]) == 1
    assert not result["latest"]["0"]["errors"]
    assert all(not row["healthy"] for row in result["checkins"])


def test_missing_or_stale_controller_is_not_healthy():
    latest = {"0": {"errors": []}, "1": {"errors": []}}
    assert not batch.checkpoint(latest, {"0": 10}, 2, 20, 300, [])["healthy"]
    assert not batch.checkpoint(latest, {"0": 0, "1": 20}, 2, 301, 300, [])["healthy"]
    assert batch.checkpoint(latest, {"0": 10, "1": 20}, 2, 300, 300, [])["healthy"]


@pytest.mark.parametrize(
    "issue",
    ["wrong-instance", "missing-proof", "duplicate-station", "insufficient-polling", "omitted-io"],
)
def test_unverified_or_uncoverable_batch_is_rejected(configured, issue):
    directory, cfg = configured
    if issue == "wrong-instance":
        cfg["targets"][0]["new_instance"] = 5399
    elif issue == "missing-proof":
        (directory / "0-proof.json").write_text("{}")
    elif issue == "duplicate-station":
        cfg["targets"][1]["target"] = cfg["targets"][0]["target"]
    elif issue == "insufficient-polling":
        cfg["poll_seconds"] = 6
    else:
        cfg["targets"][0]["io_objects"].pop()
    (directory / "batch-settings.json").write_text(json.dumps(cfg))
    with pytest.raises(ValueError):
        batch.settings(directory)
