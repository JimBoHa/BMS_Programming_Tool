"""Read-only wall-clock observation of individually verified instance changes.

Input is a private batch-settings.json; no site inventory or credentials ship here.
"""

import asyncio
import json
import math
import os
import sys
import time
from pathlib import Path

from bacpypes3.apdu import ReadPropertyMultipleACK, ReadPropertyMultipleRequest
from bacpypes3.basetypes import PropertyReference, ReadAccessSpecification
from bacpypes3.constructeddata import AnyAtomic
from bms_tool.application_files import ApplicationFiles
from bms_tool.application_store import encoded, private_write, utc
from bms_tool.bacnet_values import json_value
from bms_tool.connections import Bacnet
from bms_tool.device_details import DeviceDetails, DeviceDetailsRequest
from bms_tool.property_evidence import PropertyEvidence
from bms_tool.storage import Store


def check_device(values, name, instance):
    # AnyAtomic ObjectIdentifier.get_value() is encoded as [object type, instance].
    if (
        values.get("object-identifier") != [8, instance]
        or values.get("object-name") != name
        or values.get("system-status") != 0
    ):
        raise ValueError("Controller identity or operational status differs.")


def check_io(values):
    if (
        values.get("status-flags") != [0, 0, 0, 0]
        or values.get("reliability") != 0
        or values.get("out-of-service") is not False
    ):
        raise ValueError("Physical I/O is faulted, overridden, in alarm or out of service.")


def checkpoint(latest, sampled_at, count, now, freshness, failures):
    expected = {str(index) for index in range(count)}
    ages = {key: now - value for key, value in sampled_at.items()}
    stale = [key for key, age in ages.items() if age > freshness]
    complete = set(latest) == expected and set(ages) == expected
    healthy = (
        complete and not stale and not failures and all(not v["errors"] for v in latest.values())
    )
    return {
        "healthy": healthy,
        "controllers": len(latest),
        "stale": stale,
        "complete": complete,
        "max_sample_age_seconds": round(max(ages.values(), default=0), 3),
    }


def settings(directory):
    cfg = json.loads((directory / "batch-settings.json").read_text())
    targets = cfg["targets"]
    if not 1 <= len(targets) <= 256:
        raise ValueError("A batch needs one to 256 explicitly selected targets.")
    seen = set()
    for row in targets:
        route = DeviceDetailsRequest(**row["target"])
        key = (route.router, route.dnet, route.address)
        if key in seen or route.device != "device," + str(row["new_instance"]):
            raise ValueError("Duplicate physical station or mismatched approved instance.")
        seen.add(key)
        verified = json.loads((directory / row["verification_file"]).read_text())
        proof = json.loads((directory / row["preservation_file"]).read_text())
        if (
            verified.get("status") != "verified"
            or verified.get("controller") != row["controller"]
            or verified.get("new_instance") != row["new_instance"]
            or proof.get("controller") != row["controller"]
            or proof.get("all_non_identity_application_bytes_preserved") is not True
            or proof.get("exact_native_readback") is not True
            or proof.get("unexplained_saved_parameter_changes") != []
        ):
            raise ValueError(
                "A selected controller lacks matching verification/preservation evidence."
            )
        if (
            not isinstance(row["io_objects"], list)
            or len(set(row["io_objects"])) != len(row["io_objects"])
            or len(row["io_objects"]) != verified.get("io_count")
        ):
            raise ValueError("Use this controller's complete discovered physical I/O list.")
        DeviceDetailsRequest(**row["keeper"])
    duration = cfg.get("duration_seconds", 3600)
    interval = cfg.get("checkin_seconds", 300)
    polling = cfg.get("poll_seconds", 60)
    group = cfg.get("controllers_per_poll", 7)
    if (
        any(type(v) is not int or v < 1 for v in (duration, interval, polling, group))
        or duration % interval
        or interval % polling
        or math.ceil(len(targets) / group) * polling > interval
    ):
        raise ValueError(
            "Polling must cover the entire batch within each complete checkpoint interval."
        )
    return cfg, duration, interval, polling, group


async def observe(directory):
    cfg, duration, interval, polling, group = settings(directory)
    fd = os.open(
        directory / "batch-observation-once.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
    )
    os.close(fd)
    bacnet = Bacnet(Store(directory / "batch-observation-state"))
    targets = cfg["targets"]
    result = {
        "phase": "baseline",
        "controller_program_writes": False,
        "backup_restore_commands": False,
        "failures": [],
        "latest": {},
        "checkins": [],
    }
    sampled_at = {}
    log = directory / "batch-observation-samples.jsonl"
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    state = directory / "batch-observation-status.json"
    try:
        first = targets[0]["target"]
        await bacnet.connect(
            cfg["local_address"], cfg["local_device"], router=first["router"], dnet=first["dnet"]
        )
        bacnet.require().asap.apduTimeout = 6000
        path = DeviceDetails(bacnet, bacnet.store)
        # Reuse the owned reply validator. This observer constructs only RPM reads.
        exchange = ApplicationFiles(path, writable_files={3}, timeout=5, gap=0.05)

        async def read(target, obj, properties):
            async with path._path(DeviceDetailsRequest(**target)) as session:
                PropertyEvidence.pin(session, target.get("router"))
                request = ReadPropertyMultipleRequest(
                    listOfReadAccessSpecs=[
                        ReadAccessSpecification(
                            objectIdentifier=obj,
                            listOfPropertyReferences=[
                                PropertyReference(propertyIdentifier=p) for p in properties
                            ],
                        )
                    ]
                )
                reply = await exchange.exchange(session, request, ReadPropertyMultipleACK)
                if len(reply.listOfReadAccessResults) != 1:
                    raise ValueError("Unexpected RPM object count.")
                block = reply.listOfReadAccessResults[0]
                if str(block.objectIdentifier) != obj:
                    raise ValueError("RPM object echo differs.")
                values = {}
                for item in block.listOfResults:
                    if item.readResult.propertyAccessError is not None:
                        raise ValueError("RPM property access error.")
                    key = str(item.propertyIdentifier)
                    if key in values:
                        raise ValueError("Duplicate RPM property result.")
                    values[key] = json_value(
                        item.readResult.propertyValue.cast_out(AnyAtomic).get_value()
                    )
                if set(values) != set(properties):
                    raise ValueError("RPM property selection differs.")
                return values

        async def sample(index):
            row = targets[index]
            sample = {"at": utc(), "controller": row["controller"], "io": {}, "errors": []}
            try:
                target = row["target"]
                sample["device"] = await read(
                    target,
                    target["device"],
                    ["object-identifier", "object-name", "system-status", "database-revision"],
                )
                check_device(sample["device"], row["controller"], row["new_instance"])
                keeper = row["keeper"]
                sample["keeper"] = await read(
                    keeper, keeper["device"], ["object-name", "system-status"]
                )
                if sample["keeper"] != {"object-name": row["keeper_name"], "system-status": 0}:
                    raise ValueError("Keeper identity or operational status differs.")
                for obj in row["io_objects"]:
                    value = await read(
                        target,
                        obj,
                        [
                            "object-name",
                            "present-value",
                            "status-flags",
                            "reliability",
                            "out-of-service",
                        ],
                    )
                    sample["io"][obj] = value
                    check_io(value)
            except Exception as exc:
                sample["errors"].append(str(exc))
                result["failures"].append(
                    {"at": utc(), "controller": row["controller"], "error": str(exc)}
                )
            key = str(index)
            result["latest"][key] = sample
            sampled_at[key] = time.monotonic()
            with log.open("a") as stream:
                stream.write(json.dumps(sample) + "\n")
            private_write(state, encoded(result))
            return not sample["errors"]

        async def engine():
            target = cfg["router_target"]
            value = await read(
                target, target["device"], ["object-name", "system-status", "database-revision"]
            )
            if value["system-status"] != 0:
                raise ValueError("Supervisory engine is not operational.")
            result["engine"] = {"at": utc(), "values": value}

        for index in range(len(targets)):
            if not await sample(index):
                raise ValueError("Full-batch baseline failed before the observation clock started.")
        await engine()
        started = time.monotonic()
        result.update(phase="observing", started_at=utc(), duration_seconds=duration)
        private_write(
            directory / "batch-observation-once.json",
            encoded({"started_at": result["started_at"], "duration_seconds": duration}),
        )
        private_write(state, encoded(result))
        print("BATCH_WATCH_STARTED", result["started_at"], "controllers", len(targets), flush=True)
        groups = math.ceil(len(targets) / group)
        for tick in range(1, duration // polling + 1):
            await asyncio.sleep(max(0, tick * polling - (time.monotonic() - started)))
            try:
                await engine()
            except Exception as exc:
                result["failures"].append({"at": utc(), "stage": "engine", "error": str(exc)})
            result["elapsed_seconds"] = round(time.monotonic() - started, 3)
            if tick * polling % interval == 0:
                check = checkpoint(
                    result["latest"],
                    sampled_at,
                    len(targets),
                    time.monotonic(),
                    interval,
                    result["failures"],
                )
                check.update(
                    at=utc(),
                    minute=tick * polling // 60,
                    scheduled_seconds=tick * polling,
                    elapsed_seconds=round(time.monotonic() - started, 3),
                )
                if not check["healthy"] and not result["failures"]:
                    result["failures"].append(
                        {
                            "at": utc(),
                            "stage": "checkpoint",
                            "error": "Incomplete or stale batch samples.",
                        }
                    )
                result["checkins"].append(check)
                print("BATCH_CHECK_IN", check["minute"], "healthy", check["healthy"], flush=True)
            if tick * polling == duration:
                break
            start = ((tick - 1) % groups) * group
            for index in range(start, min(start + group, len(targets))):
                await sample(index)
            private_write(state, encoded(result))
        result.update(
            phase="completed",
            finished_at=utc(),
            stable=not result["failures"],
            elapsed_seconds=round(time.monotonic() - started, 3),
        )
    except BaseException as exc:
        result.update(phase="interrupted", stable=False, error=str(exc), finished_at=utc())
    finally:
        bacnet.close()
        private_write(state, encoded(result))
    return result


if __name__ == "__main__":
    outcome = asyncio.run(observe(Path(sys.argv[1])))
    print("BATCH_WATCH_RESULT", outcome["phase"], "stable", outcome.get("stable"))
    raise SystemExit(0 if outcome.get("stable") else 1)
