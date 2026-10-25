"""Read-only, wall-clock sixty-minute observation of the single approved pilot."""

import asyncio
import json
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

D = Path(sys.argv[1])
CFG = json.loads((D / "settings.json").read_text())
IO = CFG["io_objects"]


async def main():
    if json.loads((D / "verified-change.json").read_text())["status"] != "verified":
        raise ValueError("Pilot not verified")
    fd = os.open(D / "observation-once.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    b = Bacnet(Store(D / "observation-state"))
    await b.connect(
        json.loads((D / "interface-before.json").read_text())["config"]["local_address"].rsplit(
            ":", 1
        )[0]
        + ":47820",
        4190092,
        router=CFG["target"]["router"],
        dnet=CFG["target"]["dnet"],
    )
    b.require().asap.apduTimeout = 6000
    path = DeviceDetails(b, b.store)
    files = ApplicationFiles(path, writable_files={3}, timeout=5, gap=0.05)
    private_write(D / "observation-samples.jsonl", b"")
    private_write(D / "observation-checkins.jsonl", b"")
    result = {
        "controller": CFG["controller"],
        "route": CFG["target"],
        "old_instance": int(CFG["target"]["device"].split(",")[1]),
        "new_instance": CFG["new_instance"],
        "controller_program_writes": False,
        "backup_restore_commands": False,
        "samples": 0,
        "failures": [],
        "checkins": [],
    }

    async def object_read(target, obj, props):
        async with path._path(DeviceDetailsRequest(**target)) as s:
            PropertyEvidence.pin(s, target.get("router"))
            q = ReadPropertyMultipleRequest(
                listOfReadAccessSpecs=[
                    ReadAccessSpecification(
                        objectIdentifier=obj,
                        listOfPropertyReferences=[
                            PropertyReference(propertyIdentifier=p) for p in props
                        ],
                    )
                ]
            )
            a = await files.exchange(s, q, ReadPropertyMultipleACK)
            if len(a.listOfReadAccessResults) != 1:
                raise ValueError("Unexpected RPM object count")
            block = a.listOfReadAccessResults[0]
            if str(block.objectIdentifier) != obj:
                raise ValueError("RPM object echo mismatch")
            values = {}
            for p in block.listOfResults:
                if p.readResult.propertyAccessError is not None:
                    raise ValueError(
                        str(p.propertyIdentifier) + ": " + str(p.readResult.propertyAccessError)
                    )
                v = p.readResult.propertyValue.cast_out(AnyAtomic).get_value()
                values[str(p.propertyIdentifier)] = json_value(v)
            if set(values) != set(props):
                raise ValueError("RPM property echo mismatch")
            return values

    target = {**CFG["target"], "device": "device," + str(CFG["new_instance"])}
    keeper = CFG["keeper"]
    router = CFG["router_target"]
    started = None
    next_check = 300
    try:
        for number in range(100):
            if started is not None and time.monotonic() - started > 3660:
                break
            sample = {"time": utc(), "number": number, "io": {}, "errors": []}
            try:
                sample["device"] = await object_read(
                    target,
                    target["device"],
                    ["object-identifier", "object-name", "system-status", "database-revision"],
                )
                if (
                    sample["device"]["object-name"] != CFG["controller"]
                    or sample["device"]["system-status"] != 0
                ):
                    raise ValueError("Pilot identity/status failed")
                sample["keeper"] = await object_read(
                    keeper, keeper["device"], ["object-name", "system-status"]
                )
                if sample["keeper"] != {"object-name": CFG["keeper_name"], "system-status": 0}:
                    raise ValueError("Keeper identity/status failed")
                sample["router"] = await object_read(
                    router, router["device"], ["object-name", "system-status"]
                )
                if sample["router"]["system-status"] != 0:
                    raise ValueError("A2 NAE status failed")
                for obj in IO:
                    props = [
                        "object-name",
                        "present-value",
                        "status-flags",
                        "reliability",
                        "out-of-service",
                    ]
                    value = await object_read(target, obj, props)
                    sample["io"][obj] = value
                    if (
                        value["status-flags"] != [0, 0, 0, 0]
                        or value["reliability"] != 0
                        or value["out-of-service"] is not False
                    ):
                        raise ValueError("I/O fault/override: " + obj)
            except Exception as exc:
                sample["errors"].append(str(exc))
                result["failures"].append({"time": sample["time"], "error": str(exc)})
            if started is None:
                if sample["errors"]:
                    raise ValueError("Observation baseline failed: " + str(sample["errors"]))
                started = time.monotonic()
                result["started_at"] = utc()
                result["baseline"] = sample
                private_write(
                    D / "observation-once.json",
                    encoded(
                        {
                            "started_at": result["started_at"],
                            "duration_seconds": 3600,
                            "controller": CFG["controller"],
                            "instance": CFG["new_instance"],
                        }
                    ),
                )
                print(
                    "Observation started",
                    result["started_at"],
                    "all discovered physical I/O healthy; keeper and NAE operational.",
                    flush=True,
                )
            elapsed = time.monotonic() - started
            sample["elapsed_seconds"] = round(elapsed, 3)
            with (D / "observation-samples.jsonl").open("a") as out:
                out.write(json.dumps(sample) + "\n")
            result["samples"] += 1
            result["last_sample"] = sample
            result["elapsed_seconds"] = round(elapsed, 3)
            if elapsed >= next_check:
                check = {
                    "at": utc(),
                    "minute": next_check // 60,
                    "elapsed_seconds": round(elapsed, 3),
                    "healthy": not sample["errors"],
                    "failures_so_far": len(result["failures"]),
                    "device": sample.get("device"),
                    "io": sample["io"],
                }
                result["checkins"].append(check)
                with (D / "observation-checkins.jsonl").open("a") as out:
                    out.write(json.dumps(check) + "\n")
                print(
                    "CHECK-IN",
                    check["minute"],
                    "minutes; healthy=",
                    check["healthy"],
                    "failures=",
                    check["failures_so_far"],
                    flush=True,
                )
                next_check += 300
            private_write(D / "observation-status.json", encoded(result))
            if elapsed >= 3600:
                result.update(finished_at=utc(), status="completed", stable=not result["failures"])
                break
            await asyncio.sleep(max(0, min((number + 1) * 60, 3600) - (time.monotonic() - started)))
    except BaseException as exc:
        result.update(status="interrupted", error=str(exc), finished_at=utc())
        print("OBSERVATION INTERRUPTED", str(exc), flush=True)
    finally:
        private_write(D / "observation-status.json", encoded(result))
        b.close()
        print("Observation result", result.get("status"), result.get("stable"), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
