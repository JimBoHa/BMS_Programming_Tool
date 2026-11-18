"""Parent-scoped JCI SA-port communication diagnostics, one MAC at a time.

The native MSTP Manager diagnostic writes only Comtest Dest (1036) on 307,2,
then reads Test Status (30033). This is NOT a read-only BACnet transaction:
it changes a transient diagnostic selector, never the configured sensor MAC,
application, outputs, statistics latch, firmware or backup/restore state.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime

from bacpypes3.apdu import SimpleAckPDU, WritePropertyRequest
from bacpypes3.primitivedata import Boolean, CharacterString, Enumerated, ObjectIdentifier, Unsigned
from pydantic import Field, model_validator

from .application_files import ApplicationFiles
from .device_details import DeviceDetails, DeviceDetailsRequest
from .models import StrictModel
from .property_evidence import PropertyEvidence, ReadBudget

PROFILE = "jci-sa-port-communication-probe/1"
BUS = "307,2"
DESTINATION = 1036
TEST_STATUS = 30033
PENDING = 65535
MAX_ADDRESSES = 16
SCOPE = (
    "Runs the selected controller's SA-port communication test separately for each MAC. "
    "Only its temporary diagnostic destination changes and is restored to zero. "
    "A success is the controller's communication-test result, not a sensor identity, "
    "temperature reading, wiring inspection or exhaustive device inventory. "
    "A failure or timeout does not prove that a device is physically absent."
)


def utc():
    return datetime.now(UTC).isoformat()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class ProbeRequest(DeviceDetailsRequest):
    mac_low: int = Field(default=199, ge=1, le=254, strict=True)
    mac_high: int = Field(default=206, ge=1, le=254, strict=True)

    @model_validator(mode="after")
    def bounded_addresses(self):
        if not 0 <= self.mac_high - self.mac_low < MAX_ADDRESSES:
            raise ValueError("Choose an increasing page of at most 16 SA-bus addresses.")
        return self


class ProbeRun(StrictModel):
    token: str = Field(pattern=r"^[a-f0-9]{32}$")
    review_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    diagnostic_test_confirmed: bool = Field(default=False, strict=True)


class ProbeRecovery(StrictModel):
    restore_diagnostic_destination_confirmed: bool = Field(default=False, strict=True)


class _TypedProperty:
    """Explicit protocol types, without registering global vendor schemas."""

    def __init__(self, datatype):
        self.datatype = datatype

    def get_property_type(self, _):
        return self.datatype


class SaBusProbe:
    def __init__(
        self,
        bacnet,
        store,
        *,
        poll_seconds=0.5,
        test_seconds=7,
        settle_seconds=2,
        activity_guard=None,
    ):
        self.bacnet, self.store = bacnet, store
        self.path = DeviceDetails(bacnet, store)
        self.reader = PropertyEvidence(self.path)
        self.exchange = ApplicationFiles(self.path, writable_files={3}, timeout=1.5)
        self.poll_seconds, self.test_seconds, self.settle_seconds = (
            poll_seconds,
            test_seconds,
            settle_seconds,
        )
        self.plans, self.tasks, self.cancellations = {}, {}, set()
        self.activity_guard = activity_guard
        with store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS sa_bus_probes "
                "(id TEXT PRIMARY KEY, document TEXT NOT NULL, summary TEXT NOT NULL, "
                "pending INTEGER NOT NULL)"
            )

    def status(self):
        return {
            "profile": PROFILE,
            "scope": SCOPE,
            "connected": self.bacnet.status()["connected"],
            "read_only": False,
            "writes_operational_configuration": False,
            "diagnostic_object": BUS,
            "diagnostic_property": DESTINATION,
            "max_addresses": MAX_ADDRESSES,
            "auto_poll": False,
            "recovery_required": self._pending(),
        }

    def _save(self, report):
        summary = {
            k: report[k]
            for k in (
                "id",
                "state",
                "started_at",
                "finished_at",
                "recovery_required",
                "restoration",
            )
        }
        summary.update(target=report["plan"]["target"], identity=report["plan"]["identity"])
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO sa_bus_probes(id,document,summary,pending) VALUES(?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET document=excluded.document, "
                "summary=excluded.summary,pending=excluded.pending",
                (report["id"], encoded(report), encoded(summary), int(report["recovery_required"])),
            )

    def report(self, id):
        with self.store.connect() as db:
            row = db.execute("SELECT document FROM sa_bus_probes WHERE id=?", (id,)).fetchone()
        if row is None:
            raise ValueError("SA-bus probe report not found.")
        report = json.loads(row[0])
        if report["state"] in ("running", "cancelling") and id not in self.tasks:
            report.update(
                state="interrupted", error="Process ended; inspect the retained diagnostic intent."
            )
        return report

    def reports(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT summary FROM sa_bus_probes ORDER BY rowid DESC LIMIT 100")
            return [json.loads(r[0]) for r in rows]

    def _pending(self):
        with self.store.connect() as db:
            return [r[0] for r in db.execute("SELECT id FROM sa_bus_probes WHERE pending=1")]

    def _available(self):
        if self.activity_guard:
            self.activity_guard()
        if any(not t.done() for t in self.tasks.values()):
            raise ValueError(
                "An SA-bus probe is already running. Cancel it or wait for restoration."
            )
        if self._pending():
            raise ValueError(
                "Restore or resolve the retained SA diagnostic intent before another probe."
            )

    async def _read(self, session, budget, obj, prop, datatype, evidence):
        native, row = await self.reader.read(
            session, budget, obj, str(prop), _TypedProperty(datatype), timeout=1.5
        )
        evidence.append(row)
        if row["status"] != "ok":
            raise ValueError(f"SA diagnostic read {obj}/{prop}: {row.get('error', row['status'])}")
        return native

    async def _identity(self, session, budget, options, evidence):
        values = {}
        for prop, datatype in (
            ("object-identifier", ObjectIdentifier),
            ("vendor-identifier", Unsigned),
            ("object-name", CharacterString),
            ("model-name", CharacterString),
            ("firmware-revision", CharacterString),
            ("database-revision", Unsigned),
        ):
            value = await self._read(session, budget, options.device, prop, datatype, evidence)
            values[prop] = int(value) if isinstance(value, int) else str(value)
        if values["object-identifier"] != options.device or values["vendor-identifier"] != 5:
            raise ValueError("Station identity/vendor does not match the selected JCI controller.")
        return values

    async def _port(self, session, budget, evidence):
        port = {}
        for key, prop, datatype in (
            ("name", 2390, CharacterString),
            ("network", 875, Unsigned),
            ("mac", 2858, Unsigned),
            ("enabled", 673, Boolean),
            ("out_of_service", 81, Boolean),
            ("port_status", 2866, Enumerated),
            ("destination", DESTINATION, Unsigned),
            ("test_status", TEST_STATUS, Unsigned),
        ):
            value = await self._read(session, budget, BUS, prop, datatype, evidence)
            port[key] = (
                bool(value)
                if datatype is Boolean
                else (int(value) if datatype in (Unsigned, Enumerated) else str(value))
            )
        if not (
            port["network"] == 65000
            and port["mac"] == 0
            and port["enabled"]
            and not port["out_of_service"]
            and port["port_status"] == 1
        ):
            raise ValueError(
                "The controller does not expose the qualified active native SA-port profile."
            )
        return port

    async def review(self, **body):
        self._available()
        options = ProbeRequest(**body)
        evidence, budget = [], ReadBudget(max_requests=64)
        async with asyncio.timeout(30):
            async with self.path._path(options) as session:
                self.reader.pin(session, options.router)
                identity = await self._identity(session, budget, options, evidence)
                port = await self._port(session, budget, evidence)
                if await self._identity(session, budget, options, evidence) != identity:
                    raise ValueError("Controller identity/configuration changed during review.")
                if port["destination"] != 0 or port["test_status"] == PENDING:
                    raise ValueError(
                        "SA diagnostic destination is in use; do not interrupt another tool."
                    )
                interface = copy.deepcopy(session["config"])
        now = time.monotonic()
        self.plans = {k: v for k, v in self.plans.items() if v["deadline"] > now}
        if len(self.plans) >= 32:
            raise ValueError(
                "Too many pending SA diagnostic reviews; allow older reviews to expire."
            )
        plan = {
            "profile": PROFILE,
            "scope": SCOPE,
            "target": options.model_dump(),
            "identity": identity,
            "port": port,
            "interface": interface,
            "created_at": utc(),
            "expires_in_seconds": 120,
            "original_destination": 0,
            "evidence": evidence,
        }
        digest = hashlib.sha256(encoded(plan).encode()).hexdigest()
        token = secrets.token_hex(16)
        self.plans[token] = {"plan": plan, "sha256": digest, "deadline": now + 120}
        return {**plan, "token": token, "review_sha256": digest}

    async def start(self, **body):
        request = ProbeRun(**body)
        if not request.diagnostic_test_confirmed:
            raise ValueError("Confirm the temporary SA-port diagnostic action.")
        self._available()
        retained = self.plans.pop(request.token, None)
        if (
            retained is None
            or retained["deadline"] <= time.monotonic()
            or retained["sha256"] != request.review_sha256
        ):
            raise ValueError(
                "SA diagnostic review is missing, stale or already used. Review again."
            )
        plan = retained["plan"]
        if self.bacnet.config != plan["interface"]:
            raise ValueError(
                "Interface changed after review. Review the selected controller again."
            )
        id = secrets.token_hex(16)
        self.tasks = {k: task for k, task in self.tasks.items() if not task.done()}
        report = {
            "id": id,
            "profile": PROFILE,
            "scope": SCOPE,
            "state": "running",
            "plan": plan,
            "started_at": utc(),
            "finished_at": None,
            "recovery_required": False,
            "last_owned_destination": None,
            "restoration": "not_needed",
            "error": None,
            "evidence": [],
            "rows": [
                {"mac": mac, "status": "not_tested", "code": None}
                for mac in range(plan["target"]["mac_low"], plan["target"]["mac_high"] + 1)
            ],
        }
        self._save(report)
        self.tasks[id] = asyncio.create_task(self._run(report))
        return copy.deepcopy(report)

    async def _write_destination(self, session, report, mac):
        self.reader.guard(session)
        request = WritePropertyRequest(
            objectIdentifier=ObjectIdentifier(BUS),
            propertyIdentifier=DESTINATION,
            propertyValue=Unsigned(mac),
        )

        def dispatched(_):
            # Intent is durable BEFORE the one-attempt dispatch, including ACK loss.
            report.update(
                recovery_required=True,
                last_owned_destination=mac,
                restoration="required",
                diagnostic_dispatch_at=utc(),
            )
            self._save(report)

        await self.exchange.exchange(session, request, SimpleAckPDU, before_send=dispatched)
        report["evidence"].append({"write_destination": mac, **session["last_application_wire"]})
        self._save(report)

    async def _restore(self, session, budget, options, report):
        if not report["recovery_required"]:
            return
        evidence = report["evidence"]
        identity = await self._identity(session, budget, options, evidence)
        if identity != report["plan"]["identity"]:
            raise ValueError(
                "Controller identity/configuration changed; automatic restoration refused."
            )
        actual = int(await self._read(session, budget, BUS, DESTINATION, Unsigned, evidence))
        if actual not in (0, report["last_owned_destination"]):
            raise ValueError(
                "Another diagnostic owner changed the destination; restoration refused."
            )
        if actual != 0:
            await self._write_destination(session, report, 0)
            actual = int(await self._read(session, budget, BUS, DESTINATION, Unsigned, evidence))
        if actual != 0:
            raise ValueError("Original diagnostic destination could not be verified.")
        report.update(recovery_required=False, restoration="verified", restored_at=utc())
        self._save(report)

    async def _probe(self, session, budget, options, report, row):
        evidence = report["evidence"]
        if await self._identity(session, budget, options, evidence) != report["plan"]["identity"]:
            raise ValueError("Controller identity/configuration changed during the probe.")
        actual = int(await self._read(session, budget, BUS, DESTINATION, Unsigned, evidence))
        if actual != (report["last_owned_destination"] or 0):
            raise ValueError("SA diagnostic destination ownership changed; stopping the probe.")
        row.update(status="testing", started_at=utc(), observed_pending=False)
        self._save(report)
        await self._write_destination(session, report, row["mac"])
        started = time.monotonic()
        while time.monotonic() - started < self.test_seconds:
            await asyncio.sleep(self.poll_seconds)
            destination = int(
                await self._read(session, budget, BUS, DESTINATION, Unsigned, evidence)
            )
            if destination != row["mac"]:
                raise ValueError(
                    "SA diagnostic destination changed during the test; result discarded."
                )
            code = int(await self._read(session, budget, BUS, TEST_STATUS, Unsigned, evidence))
            if not 0 <= code <= 65535:
                raise ValueError("SA diagnostic status is outside the qualified uint16 profile.")
            row.update(code=code, observed_pending=row["observed_pending"] or code == PENDING)
            if code != PENDING and time.monotonic() - started >= self.settle_seconds:
                row.update(
                    status="success_reported" if code == 0 else "diagnostic_error",
                    finished_at=utc(),
                )
                self._save(report)
                return
        row.update(status="test_timeout", finished_at=utc())
        self._save(report)
        # Do not select another address while the controller's test is still pending.
        raise ValueError(
            "SA diagnostic did not finish in its bounded window; remaining MACs were not tested."
        )

    async def _run(self, report):
        options = ProbeRequest(**report["plan"]["target"])
        budget = ReadBudget(max_requests=2048, max_bytes=8 * 1024 * 1024)
        try:
            async with asyncio.timeout(180):
                async with self.path._path(options) as session:
                    self.reader.pin(session, options.router)
                    try:
                        if self.activity_guard:
                            self.activity_guard()
                        if session["config"] != report["plan"]["interface"]:
                            raise ValueError("Interface changed since review.")
                        identity = await self._identity(
                            session, budget, options, report["evidence"]
                        )
                        port = await self._port(session, budget, report["evidence"])
                        if identity != report["plan"]["identity"] or port != report["plan"]["port"]:
                            raise ValueError(
                                "Controller or SA diagnostic state changed since review."
                            )
                        for row in report["rows"]:
                            if report["id"] in self.cancellations:
                                report["state"] = "cancelled"
                                break
                            await self._probe(session, budget, options, report, row)
                        else:
                            report["state"] = "complete"
                    except (Exception, asyncio.CancelledError) as exc:
                        report["operation_error"] = str(exc)[:1000] or type(exc).__name__
                        raise
                    finally:
                        # Retire the current transaction, then restore inside the owned route/lock.
                        cleanup = asyncio.create_task(
                            self._restore(session, budget, options, report)
                        )
                        try:
                            await asyncio.shield(cleanup)
                        except asyncio.CancelledError:
                            await cleanup
                            raise
                        except Exception as exc:
                            report["restoration_error"] = str(exc)[:1000] or type(exc).__name__
                            report["restoration"] = "unverified"
                            raise
        except asyncio.CancelledError:
            report.update(state="cancelled", error="Probe cancelled; inspect restoration status.")
        except Exception as exc:
            report.update(state="incomplete", error=str(exc)[:1000] or type(exc).__name__)
        finally:
            for row in report["rows"]:
                if row["status"] == "testing":
                    row.update(status="uncertain", finished_at=utc())
            report.update(finished_at=utc(), budget=budget.snapshot())
            self._save(report)
            self.cancellations.discard(report["id"])

    def cancel(self, id):
        report = self.report(id)
        task = self.tasks.get(id)
        if task is not None and not task.done():
            self.cancellations.add(id)
            # The worker owns the document. Do not overwrite newer evidence here.
        return report

    async def recover(self, id, **body):
        request = ProbeRecovery(**body)
        if not request.restore_diagnostic_destination_confirmed:
            raise ValueError("Confirm restoring the retained diagnostic destination.")
        if any(not t.done() for t in self.tasks.values()):
            raise ValueError("Wait for the active probe to finish restoration.")
        report = self.report(id)
        if not report["recovery_required"]:
            raise ValueError("This report does not require diagnostic restoration.")
        if self.bacnet.config != report["plan"]["interface"]:
            raise ValueError("Reopen the original interface before diagnostic recovery.")
        options = ProbeRequest(**report["plan"]["target"])
        async with asyncio.timeout(25):
            async with self.path._path(options) as session:
                self.reader.pin(session, options.router)
                await self._restore(session, ReadBudget(max_requests=32), options, report)
        return report

    async def close(self):
        pending = [task for task in self.tasks.values() if not task.done()]
        for id, task in self.tasks.items():
            if not task.done():
                self.cancellations.add(id)
        if pending:
            try:
                await asyncio.wait_for(asyncio.gather(*pending), 20)
            except TimeoutError:
                pass


def sa_bus_probe_router(service):
    from fastapi import APIRouter

    router = APIRouter(prefix="/api/bacnet/controller/sa-bus-probe")

    @router.get("/status")
    def status():
        return service.status()

    @router.post("/review")
    async def review(body: ProbeRequest):
        return await service.review(**body.model_dump())

    @router.post("/run")
    async def run(body: ProbeRun):
        return await service.start(**body.model_dump())

    @router.get("/reports")
    def reports():
        return service.reports()

    @router.get("/reports/{id}")
    def report(id: str):
        return service.report(id)

    @router.post("/reports/{id}/cancel")
    async def cancel(id: str):
        return service.cancel(id)

    @router.post("/reports/{id}/recover")
    async def recover(id: str, body: ProbeRecovery):
        return await service.recover(id, **body.model_dump())

    return router
