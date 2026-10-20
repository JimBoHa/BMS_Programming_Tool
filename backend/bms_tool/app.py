"""Loopback-only local application API. Field interfaces open only on explicit requests."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sqlite3
import time
import xml.etree.ElementTree as XML
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, Field

from .analysis import dependencies
from .bacnet_history import BacnetHistory, BacnetHistoryRequest
from .blocks import catalog
from .caf import CafArchive
from .caf_compare import compare_cafs
from .caf_graph import CafGraph
from .caf_simulation import CafSimulationProfile
from .connections import Bacnet, modbus_read, ports
from .deployment import Runtime
from .engine import Engine, output_type, run_scenario, validate
from .field_trends import FieldTrends, FieldTrendStart
from .formats import export_program, import_program
from .jci_hardware import JciHardwareDefinition, plan_hardware_migration
from .macros import (
    create_definition,
    delete_macro_definition,
    export_macro_library,
    import_macro_library,
    inspect_macro_definition,
    instantiate_macro,
    macro_catalog,
    update_macro_definition,
)
from .models import Program, StrictModel
from .native_simulator import NativeSimulator
from .niagara import NiagaraArchive
from .observability import ObservabilityStore
from .simulation_group import SimulationGroups, SimulationWorkspace, demo_workspace
from .storage import Conflict, Store
from .temco_transfer import TemcoTransfer
from .templates import all_templates

ROOT = Path(__file__).resolve().parents[2]


class SimulationRequest(StrictModel):
    program: Program
    inputs: dict[str, Any] = Field(default_factory=dict)
    dt: float | None = None
    session: str | None = None
    steps: int = Field(default=1, ge=1, le=1000)
    clock: AwareDatetime | None = None
    forces: dict[str, Any] | None = None
    record: bool = False


class NativeStart(StrictModel):
    program: Program


class NativeStep(StrictModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    dt: float | None = Field(default=None, gt=0, le=60)
    clock: datetime | None = None


class NativePlan(StrictModel):
    operations: list[dict[str, Annotated[str, Field(max_length=256)]]] = Field(
        min_length=1, max_length=100
    )


class NativeSave(StrictModel):
    expected_revision: int = Field(ge=0)


class NativeExport(StrictModel):
    format: str = "sedona"


class ScenarioRequest(StrictModel):
    program: Program
    events: list[dict[str, Any]]
    duration: float = Field(gt=0, le=86400)
    dt: float | None = Field(default=None, gt=0, le=60)
    forces: dict[str, Any] | None = None


class SaveRequest(StrictModel):
    program: Program
    expected_revision: int = Field(ge=0)


class DependencyRequest(StrictModel):
    program: Program
    node: str


class GroupStart(StrictModel):
    definition: SimulationWorkspace
    replace: str | None = None


class GroupRequest(StrictModel):
    session: str


class GroupStep(GroupRequest):
    inputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    steps: int = Field(default=1, ge=1, le=100)
    clock: AwareDatetime | None = None


class ExportRequest(StrictModel):
    program: Program
    format: str


class CafPatchRequest(StrictModel):
    changes: list[dict[str, Any]] = Field(max_length=1000)


class CafSimulationRequest(StrictModel):
    profile: dict[str, Any]


class CafCompareRequest(StrictModel):
    before_sha: str = Field(pattern=r"^[a-f0-9]{64}$")
    after_sha: str = Field(pattern=r"^[a-f0-9]{64}$")
    offset: int = Field(default=0, ge=0, le=200000, strict=True)
    limit: int = Field(default=100, ge=1, le=500, strict=True)
    category: str | None = None
    query: str = Field(default="", max_length=200)


class HistoryCaptureRequest(StrictModel):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")


class NotificationRouteRequest(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    url_env: str | None = Field(default=None, min_length=1, max_length=128)
    sources: list[str] | None = Field(default=None, max_length=128)
    events: list[str] | None = Field(default=None, min_length=1, max_length=4)
    bearer_env: str | None = Field(default=None, min_length=1, max_length=128)
    start_after: int | None = Field(default=None, ge=0, le=2**63 - 1, strict=True)


class NotificationEnableRequest(StrictModel):
    route_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    enabled: bool = Field(strict=True)


class NotificationActionRequest(StrictModel):
    id: int = Field(ge=1, le=2**63 - 1, strict=True)
    actor: str = Field(default="operator", min_length=1, max_length=100)
    note: str = Field(min_length=1, max_length=500)


class NotificationPruneRequest(StrictModel):
    through_id: int = Field(ge=1, le=2**63 - 1, strict=True)
    limit: int = Field(default=1000, ge=1, le=1000, strict=True)


class NotificationCycleRequest(StrictModel):
    limit: int = Field(default=20, ge=1, le=20, strict=True)


class BacnetConnect(StrictModel):
    local_address: str
    instance: int = 4190001
    router: str | None = None
    dnet: int | None = None
    bbmd_address: str | None = Field(default=None, min_length=1, max_length=256)
    foreign_ttl: int = Field(default=60, ge=1, le=65535, strict=True)


class BacnetForeignDiscover(StrictModel):
    low: int = Field(default=0, ge=0, le=4194302, strict=True)
    high: int = Field(default=4194302, ge=0, le=4194302, strict=True)


class BacnetDiscover(StrictModel):
    address: str
    low: int = 0
    high: int = 4194302


class BacnetMstp(StrictModel):
    port: str = Field(min_length=1, max_length=256)
    mac: int = Field(ge=0, le=127, strict=True)
    instance: int = Field(default=4190001, ge=0, le=4194302, strict=True)
    baudrate: int = Field(default=38400, strict=True)
    max_master: int = Field(default=127, ge=0, le=127, strict=True)
    max_info_frames: int = Field(default=1, ge=1, le=255, strict=True)


class TemcoProgram(StrictModel):
    program: Program
    bindings: dict[str, str] = Field(default_factory=dict)


class TemcoVerify(TemcoProgram):
    inputs: dict[str, Any] = Field(default_factory=dict)
    scans: int = Field(default=1, ge=1, le=1000, strict=True)
    clock: AwareDatetime | None = None


class IecProgram(StrictModel):
    program: Program


class IecVerify(IecProgram):
    inputs: dict[str, Any] = Field(default_factory=dict)
    scans: int = Field(default=1, ge=1, le=1000, strict=True)
    dt: float | None = Field(default=None, gt=0, le=60, strict=True)
    clock: AwareDatetime | None = None


class IecScenario(IecProgram):
    events: list[dict[str, Any]] = Field(max_length=10000)
    duration: float = Field(gt=0, le=86400, strict=True)
    dt: float | None = Field(default=None, gt=0, le=60, strict=True)
    clock: AwareDatetime | None = None


class HardwareSelection(StrictModel):
    point_ids: list[str] = Field(min_length=1, max_length=4096)
    system: Literal["imperial", "metric"] = "imperial"


class HardwareMigration(HardwareSelection):
    old_sha: str = Field(pattern=r"^[a-f0-9]{64}$")
    new_sha: str = Field(pattern=r"^[a-f0-9]{64}$")


class TemcoTarget(StrictModel):
    address: str = Field(min_length=1, max_length=256)
    device_instance: int = Field(ge=0, le=4194302, strict=True)
    slot: int = Field(ge=0, le=15, strict=True)
    expected_model: str = Field(min_length=1, max_length=256)
    expected_firmware: str = Field(min_length=1, max_length=256)


class TemcoReplace(TemcoTarget):
    source: str = Field(min_length=1, max_length=1024 * 1024)
    resume: bool = Field(default=True, strict=True)


class TemcoRestore(TemcoTarget):
    backup_id: str = Field(min_length=1, max_length=128)
    resume: bool = Field(default=True, strict=True)


class BacnetRead(StrictModel):
    address: str
    object_id: str
    property_id: str = "present-value"
    array_index: int | None = None


class BacnetWrite(StrictModel):
    address: str
    object_id: str
    value: Any
    priority: int = 16


class TokenRequest(StrictModel):
    token: str


class RuntimePlan(StrictModel):
    program: Program
    inputs: dict[str, Any] = Field(default_factory=dict)


class RuntimeRollback(StrictModel):
    backup_id: str
    expected_generation: int


class RuntimeControl(StrictModel):
    running: bool
    inputs: dict[str, Any] = Field(default_factory=dict)


class ModbusRead(StrictModel):
    transport: str = "tcp"
    address: str
    unit: int = 1
    register_address: int = Field(default=0, alias="register")
    count: int = 1
    table: str = "holding"
    port: int = 502
    baud: int = 38400
    parity: str = "N"


class AlarmAcknowledgement(StrictModel):
    alarm_id: int = Field(ge=1, strict=True)
    note: str = Field(min_length=1, max_length=1000)
    actor: str = Field(default="operator", min_length=1, max_length=120)


class ObservationSource(StrictModel):
    source: str = Field(min_length=1, max_length=200)


class FieldTrendStop(StrictModel):
    id: str = Field(min_length=1, max_length=64)


class ObservationEnd(ObservationSource):
    note: str = Field(min_length=1, max_length=1000)
    actor: str = Field(default="operator", min_length=1, max_length=120)


class MacroProgram(StrictModel):
    program: Program


class MacroSelection(MacroProgram):
    selected_ids: list[str] = Field(min_length=1, max_length=2000)
    name: str = Field(min_length=1, max_length=200)


class MacroReference(MacroProgram):
    definition: str = Field(min_length=1, max_length=80)


class MacroInstance(MacroReference):
    x: float = 0.0
    y: float = 0.0


class MacroImport(MacroProgram):
    bundle: dict[str, Any]


class MacroUpdate(MacroReference):
    replacement: Program


def create_app(state_dir=None):
    store = Store(state_dir or os.environ.get("BMS_STUDIO_DATA", str(ROOT / ".state")))
    runtime = Runtime(store)
    bacnet = Bacnet(store)
    native = NativeSimulator(store)
    groups = SimulationGroups()
    observations = ObservabilityStore(store.directory)
    field_trends = FieldTrends(bacnet, store.directory, audit_store=store)
    temco_transfer = TemcoTransfer(bacnet, store)
    history = BacnetHistory(bacnet, store)
    notifications = None
    simulations = {}
    caf_files = {}
    niagara_files = {}
    hardware_files = {}
    session_token = secrets.token_urlsafe(32)
    control = {"running": False, "inputs": {}, "error": None}

    @asynccontextmanager
    async def lifespan(app):
        nonlocal notifications
        from .notification_outbox import NotificationOutbox

        app.state.notification_worker_error = None
        app.state.notification_startup_error = None
        try:
            notifications = NotificationOutbox(store.directory / "notifications", observations)
        except (ValueError, OSError, sqlite3.Error) as exc:
            notifications = None
            app.state.notification_startup_error = "Alarm delivery unavailable: " + str(exc)
        app.state.notifications = notifications

        async def notification_ticks():
            while True:
                await asyncio.sleep(1)
                if notifications is None:
                    continue
                try:
                    async with asyncio.timeout(30):
                        await notifications.cycle(limit=20)
                    app.state.notification_worker_error = None
                except Exception as exc:
                    app.state.notification_worker_error = (
                        "Delivery pass failed: " + type(exc).__name__
                    )

        async def ticks():
            while True:
                await asyncio.sleep(runtime.engine.program.scan_seconds if runtime.engine else 1)
                if control["running"] and runtime.engine:
                    try:
                        runtime.engine.step(control["inputs"])
                        control["error"] = None
                    except ValueError as exc:
                        control["running"] = False
                        control["error"] = str(exc)
                        store.record("runtime.scan.failed", {"error": str(exc)})

        tasks = [asyncio.create_task(ticks()), asyncio.create_task(notification_ticks())]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                if notifications is not None:
                    await notifications.close()
            finally:
                try:
                    await field_trends.close()
                finally:
                    try:
                        bacnet.close()
                    finally:
                        native.stop()

    app = FastAPI(title="BMS Studio local API", version="0.1.0", lifespan=lifespan)
    app.state.runtime = runtime
    app.state.store = store
    app.state.bacnet = bacnet
    app.state.native = native
    app.state.field_trends = field_trends
    app.state.temco_transfer = temco_transfer
    app.state.bacnet_history = history
    app.state.notifications = None

    @app.middleware("http")
    async def local_requests(request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", "testserver"):
            return JSONResponse(
                {"detail": "This application accepts loopback hostnames only."}, 403
            )
        origin = request.headers.get("origin")
        if origin and origin not in (
            str(request.base_url).rstrip("/"),
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ):
            return JSONResponse({"detail": "Cross-origin requests are forbidden."}, 403)
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and request.headers.get("x-studio-token") != session_token
        ):
            return JSONResponse({"detail": "A valid local session token is required."}, 403)
        length = request.headers.get("content-length")
        if length and int(length) > 9 * 1024 * 1024:
            return JSONResponse({"detail": "Request exceeds 9 MiB."}, 413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({"detail": str(exc)}, 409 if isinstance(exc, Conflict) else 422)

    @app.exception_handler(asyncio.TimeoutError)
    async def timeout_error(request, exc):
        return JSONResponse(
            {
                "detail": "Device/network request timed out. A timed-out write may require explicit readback/relinquish."
            },
            504,
        )

    @app.exception_handler(OSError)
    async def os_error(request, exc):
        return JSONResponse({"detail": str(exc)}, 503)

    @app.exception_handler(sqlite3.Error)
    async def storage_error(request, exc):
        return JSONResponse({"detail": "Local storage operation failed: " + str(exc)}, 503)

    @app.get("/api/session")
    def session():
        return {
            "token": session_token,
            "version": "0.1.0",
            "field_network_open": bacnet.status()["connected"],
        }

    @app.get("/api/blocks")
    def blocks():
        return catalog()

    @app.get("/api/templates")
    def templates():
        return [p.model_dump() for p in all_templates()]

    @app.get("/api/observations/status")
    def observation_status():
        return observations.status()

    @app.get("/api/field-trends/status")
    def field_trend_status():
        return field_trends.status()

    @app.get("/api/field-trends/sources")
    def field_trend_sources():
        return field_trends.store.list_sources()

    @app.get("/api/field-trends/samples")
    def field_trend_samples(
        source: str | None = None,
        signal: str | None = None,
        start: AwareDatetime | None = None,
        end: AwareDatetime | None = None,
        after: int = 0,
        limit: int = 100,
    ):
        return field_trends.store.trends(
            source=source, signal=signal, start=start, end=end, after=after, limit=limit
        )

    @app.get("/api/field-trends/events")
    def field_trend_events(source: str | None = None, after: int = 0, limit: int = 100):
        return field_trends.events(source=source, after=after, limit=limit)

    @app.post("/api/field-trends/start")
    async def field_trend_start(body: FieldTrendStart):
        return await field_trends.start(**body.model_dump())

    @app.post("/api/field-trends/stop")
    async def field_trend_stop(body: FieldTrendStop):
        return await field_trends.stop(body.id)

    @app.post("/api/field-trends/retire")
    async def field_trend_retire(body: ObservationSource):
        return await field_trends.retire_source(body.source)

    @app.get("/api/observations/sources")
    def observation_sources():
        return observations.list_sources()

    def notification_service():
        if notifications is None:
            raise ValueError(
                getattr(app.state, "notification_startup_error", None)
                or "Alarm delivery service has not started."
            )
        return notifications

    @app.get("/api/notifications/status")
    def notification_status():
        if notifications is None:
            return {
                "available": False,
                "active_routes": 0,
                "enabled_routes": [],
                "latest_alarm_event_sequence": 0,
                "worker_error": getattr(app.state, "notification_startup_error", None)
                or "Alarm delivery service has not started.",
            }
        return {
            **notification_service().status(),
            "available": True,
            "worker_error": app.state.notification_worker_error,
        }

    @app.get("/api/notifications/routes")
    def notification_routes():
        return notification_service().routes() if notifications is not None else []

    @app.post("/api/notifications/routes")
    def notification_route_create(body: NotificationRouteRequest):
        return notification_service().create_route(**body.model_dump())

    @app.post("/api/notifications/routes/enable")
    def notification_route_enable(body: NotificationEnableRequest):
        return notification_service().enable_route(body.route_id, body.enabled)

    @app.get("/api/notifications/deliveries")
    def notification_deliveries(
        route_id: str | None = None, state: str | None = None, after: int = 0, limit: int = 100
    ):
        if notifications is None:
            return {"rows": [], "total": 0, "next_after": None}
        return notification_service().deliveries(
            route_id=route_id, state=state, after=after, limit=limit
        )

    @app.get("/api/notifications/deliveries/{id}")
    def notification_delivery(id: int):
        return notification_service().delivery(id)

    @app.post("/api/notifications/retry")
    def notification_retry(body: NotificationActionRequest):
        return notification_service().retry(body.id, body.note, actor=body.actor)

    @app.post("/api/notifications/discard")
    def notification_discard(body: NotificationActionRequest):
        return notification_service().discard(body.id, body.note, actor=body.actor)

    @app.post("/api/notifications/prune")
    def notification_prune(body: NotificationPruneRequest):
        return notification_service().prune_completed(**body.model_dump())

    @app.post("/api/notifications/cycle")
    async def notification_cycle(body: NotificationCycleRequest):
        try:
            async with asyncio.timeout(30):
                result = await notification_service().cycle(**body.model_dump())
            app.state.notification_worker_error = None
            return result
        except TimeoutError:
            return JSONResponse(
                {
                    "detail": "Delivery pass timed out. Completed and uncertain results remain in delivery history."
                },
                504,
            )

    @app.get("/api/observations/trends")
    def observation_trends(
        source: str | None = None,
        signal: str | None = None,
        start: AwareDatetime | None = None,
        end: AwareDatetime | None = None,
        after: int = 0,
        limit: int = 100,
    ):
        return observations.trends(
            source=source, signal=signal, start=start, end=end, after=after, limit=limit
        )

    @app.get("/api/observations/alarms")
    def observation_alarms(
        source: str | None = None,
        active: bool | None = None,
        unacknowledged: bool | None = None,
        limit: int = 100,
    ):
        return observations.alarms(
            source=source, active=active, unacknowledged=unacknowledged, limit=limit
        )

    @app.get("/api/observations/events")
    def observation_events(
        source: str | None = None, alarm_id: int | None = None, after: int = 0, limit: int = 100
    ):
        return observations.alarm_events(source=source, alarm_id=alarm_id, after=after, limit=limit)

    @app.post("/api/observations/acknowledge")
    def observation_acknowledge(body: AlarmAcknowledgement):
        store.record(
            "simulation.alarm.acknowledgement.requested",
            {"alarm_id": body.alarm_id, "actor": body.actor, "note": body.note},
        )
        result = observations.acknowledge(body.alarm_id, body.note, actor=body.actor)
        try:
            store.record(
                "simulation.alarm.acknowledged",
                {"alarm_id": body.alarm_id, "actor": body.actor, "note": body.note},
            )
        except (OSError, sqlite3.Error) as exc:
            result["audit_error"] = f"Acknowledgment committed; audit completion failed: {exc}"
        return result

    @app.post("/api/observations/retire")
    def observation_retire(body: ObservationSource):
        store.record("simulation.observations.retirement.requested", {"source": body.source})
        result = observations.retire_source(body.source)
        try:
            store.record("simulation.observations.retired", {"source": body.source})
        except (OSError, sqlite3.Error) as exc:
            result["audit_error"] = f"Retirement committed; audit completion failed: {exc}"
        return result

    @app.post("/api/observations/end")
    def observation_end(body: ObservationEnd):
        store.record("simulation.observations.end.requested", body.model_dump())
        result = observations.end_source(body.source, body.note, actor=body.actor)
        try:
            store.record("simulation.observations.ended", body.model_dump())
        except (OSError, sqlite3.Error) as exc:
            result["audit_error"] = f"Source ended; audit completion failed: {exc}"
        return result

    @app.post("/api/validate")
    def validation(program: Program):
        return {"issues": [d.model_dump() for d in validate(program)]}

    @app.post("/api/dependencies")
    def trace_dependencies(body: DependencyRequest):
        return dependencies(body.program, body.node)

    @app.post("/api/macros/catalog")
    def macros_catalog(body: MacroProgram):
        return {"definitions": macro_catalog(body.program)}

    @app.post("/api/macros/create")
    def macros_create(body: MacroSelection):
        return create_definition(body.program, body.selected_ids, body.name)

    @app.post("/api/macros/instantiate")
    def macros_instantiate(body: MacroInstance):
        return instantiate_macro(body.program, body.definition, body.x, body.y)

    @app.post("/api/macros/definition")
    def macros_definition(body: MacroReference):
        return inspect_macro_definition(body.program, body.definition)

    @app.post("/api/macros/delete")
    def macros_delete(body: MacroReference):
        return delete_macro_definition(body.program, body.definition)

    @app.post("/api/macros/export")
    def macros_export(body: MacroReference):
        return export_macro_library(body.program, body.definition)

    @app.post("/api/macros/import")
    def macros_import(body: MacroImport):
        return import_macro_library(body.program, body.bundle)

    @app.post("/api/macros/update")
    def macros_update(body: MacroUpdate):
        return update_macro_definition(body.program, body.definition, body.replacement)

    @app.get("/api/groups/demo")
    def group_demo():
        return demo_workspace()

    @app.get("/api/groups")
    def group_list():
        return groups.list()

    @app.post("/api/groups/start")
    def group_start(body: GroupStart):
        return groups.start(body.definition, body.replace)

    @app.get("/api/groups/{session}")
    def group_status(session: str):
        return groups.status(session)

    @app.post("/api/groups/step")
    def group_step(body: GroupStep):
        if body.clock is not None and body.steps != 1:
            raise ValueError("An explicit clock applies to one group cycle.")
        group = groups.get(body.session)
        for _ in range(body.steps):
            group.step(body.inputs, clock=body.clock)
        return groups.status(body.session)

    @app.post("/api/groups/reset")
    def group_reset(body: GroupRequest):
        groups.get(body.session).reset()
        return groups.status(body.session)

    @app.post("/api/groups/close")
    def group_close(body: GroupRequest):
        groups.close(body.session)
        return {"closed": True}

    @app.post("/api/groups/export")
    def group_export(body: GroupRequest):
        return Response(groups.export(body.session), media_type="application/json")

    @app.post("/api/groups/import")
    async def group_import(file: Annotated[UploadFile, File()], replace: str | None = None):
        content = await file.read(8 * 1024 * 1024 + 1)
        return groups.import_file(content, replace)

    @app.get("/api/projects")
    def projects():
        return store.projects()

    @app.post("/api/projects")
    def save(body: SaveRequest):
        return store.save(body.program, body.expected_revision)

    @app.get("/api/projects/{id}/versions")
    def versions(id: str):
        return store.versions(id)

    @app.get("/api/projects/{id}")
    def project(id: str, revision: int | None = None):
        return store.load(id, revision)

    @app.post("/api/import")
    async def import_file(file: Annotated[UploadFile, File()]):
        content = await file.read(8 * 1024 * 1024 + 1)
        try:
            return import_program(content, file.filename or "")
        except (zipfile.BadZipFile, XML.ParseError, KeyError, TypeError) as exc:
            raise ValueError("Malformed interchange file: " + type(exc).__name__) from exc

    @app.post("/api/export")
    def export_file(body: ExportRequest):
        content, mime, extension = export_program(body.program, body.format)
        return Response(
            content,
            media_type=mime,
            headers={
                "Content-Disposition": f'attachment; filename="{body.program.id}.{extension}"'
            },
        )

    @app.get("/api/native/status")
    def native_status():
        return native.status()

    @app.post("/api/native/start")
    def native_start(body: NativeStart):
        return native.start(body.program)

    @app.post("/api/native/stop")
    def native_stop():
        native.stop()
        return native.status()

    @app.post("/api/native/step")
    def native_step(body: NativeStep):
        return native.step(body.inputs, body.dt, body.clock)

    @app.get("/api/native/inventory")
    def native_inventory():
        return native.inspect()

    @app.post("/api/native/save")
    def native_save(body: NativeSave):
        return native.save(body.expected_revision)

    @app.post("/api/native/export")
    def native_export(body: NativeExport):
        if body.format not in ("sedona", "sedona-sax", "sedona-sab", "json"):
            raise ValueError("Export a native Sedona bundle, SAX, SAB or complete JSON project.")
        program = native.snapshot_program()
        content, mime, extension = export_program(program, body.format)
        return Response(
            content,
            media_type=mime,
            headers={"Content-Disposition": f'attachment; filename="{program.id}.{extension}"'},
        )

    @app.post("/api/native/plan")
    def native_plan(body: NativePlan):
        return native.plan(body.operations)

    @app.post("/api/native/apply")
    def native_apply(body: TokenRequest):
        return native.apply(body.token)

    @app.post("/api/native/rollback")
    def native_rollback(body: RuntimeRollback):
        return native.rollback(body.backup_id, body.expected_generation)

    @app.post("/api/simulation/step")
    async def step(body: SimulationRequest):
        now = time.monotonic()
        for id in [k for k, v in simulations.items() if now - v["touched"] > 3600]:
            del simulations[id]
        if body.session:
            record = simulations.get(body.session)
            if record is None:
                raise ValueError("Simulation session expired. Reset simulation.")
            if record["engine"].program.digest() != body.program.digest():
                raise ValueError(
                    "Program changed. Reset simulation before running the edited graph."
                )
            id = body.session
        else:
            if len(simulations) >= 25:
                raise ValueError(
                    "Simulation session limit reached. Wait for expiration or restart the app."
                )
            id = secrets.token_urlsafe(16)
            record = {"engine": Engine(body.program), "touched": now}
            simulations[id] = record
        engine = record["engine"]
        record["touched"] = now
        if body.clock is not None and body.steps != 1:
            raise ValueError("An explicit clock applies to one scan; use single-step mode.")
        rows = []
        scan_error = None
        recording_errors = []
        source = f"simulation/{body.program.id}/{id}"
        for _ in range(body.steps):
            try:
                row = engine.step(body.inputs, body.dt, body.clock, forces=body.forces)
            except ValueError as exc:
                if not rows:
                    raise
                scan_error = str(exc)
                break
            rows.append(row)
            if body.record and not recording_errors:
                try:
                    observations.record_scan(
                        source,
                        row["clock"],
                        row["values"],
                        {
                            n.id: {"active": row["values"][n.id], "message": n.label or n.id}
                            for n in engine.graph.nodes
                            if n.kind == "Alarm"
                        },
                        units={
                            n.id: n.unit if output_type(n) == "number" else ""
                            for n in engine.graph.nodes
                        },
                    )
                except (ValueError, OSError, sqlite3.Error) as exc:
                    # Execution already succeeded. Recording is a separate service;
                    # never imply an executed scan was rolled back by a disk error.
                    recording_errors.append(str(exc))
        return {
            "session": id,
            "last": rows[-1],
            "history": engine.history[-300:],
            "snapshot": engine.snapshot(),
            "recording_source": source if body.record else None,
            "recording_error": "; ".join(recording_errors) or None,
            "scan_error": scan_error,
            "completed_steps": len(rows),
        }

    @app.post("/api/simulation/scenario")
    async def scenario(body: ScenarioRequest):
        return {
            "history": run_scenario(
                body.program, body.events, body.duration, body.dt, forces=body.forces
            )
        }

    @app.post("/api/caf")
    async def upload_caf(file: Annotated[UploadFile, File()]):
        caf = CafArchive(await file.read(8 * 1024 * 1024 + 1))
        if len(caf_files) >= 30 and caf.hash not in caf_files:
            raise ValueError("CAF workspace limit reached; restart the app to clear it.")
        caf_files[caf.hash] = caf
        return caf.summary()

    def get_caf(id):
        if id not in caf_files:
            raise ValueError("Open the CAF file first.")
        return caf_files[id]

    @app.post("/api/caf/compare")
    def caf_compare(body: CafCompareRequest):
        return compare_cafs(
            get_caf(body.before_sha),
            get_caf(body.after_sha),
            offset=body.offset,
            limit=body.limit,
            category=body.category,
            query=body.query,
        )

    @app.get("/api/caf/{id}/objects")
    def caf_objects(id: str, q: str = "", offset: int = 0, limit: int = 200):
        rows = get_caf(id).inventory(q)
        return {
            "objects": rows[max(0, offset) : max(0, offset) + min(500, max(1, limit))],
            "total": len(rows),
        }

    @app.get("/api/caf/{id}/properties")
    def caf_properties(id: str, ref: str):
        return get_caf(id).properties(ref)

    @app.get("/api/caf/{id}/simulation")
    def caf_simulation(id: str):
        return CafSimulationProfile(get_caf(id)).summary()

    @app.get("/api/caf/{id}/simulation/profile")
    def caf_simulation_profile(id: str):
        return CafSimulationProfile(get_caf(id)).export_profile()

    @app.post("/api/caf/{id}/simulation")
    def caf_simulation_export(id: str, body: CafSimulationRequest):
        content, changes = CafSimulationProfile(get_caf(id)).apply(body.profile)
        store.record(
            "caf.simulation.export",
            {"source_sha256": id, "changed_records": len(changes), "native_validation": "pending"},
        )
        return Response(
            content,
            media_type="application/octet-stream",
            headers={"Content-Disposition": 'attachment; filename="simulation-copy.caf"'},
        )

    @app.post("/api/caf/{id}/export")
    def caf_export(id: str, body: CafPatchRequest):
        content, changes = get_caf(id).patch(body.changes)
        store.record(
            "caf.export",
            {"original_sha256": id, "changes": changes, "native_validation": "pending"},
        )
        return Response(
            content,
            media_type="application/octet-stream",
            headers={"Content-Disposition": 'attachment; filename="edited-copy.caf"'},
        )

    @app.get("/api/ports")
    def serial_ports():
        return ports()

    @app.get("/api/caf/{id}/graphs")
    def caf_graphs(id: str):
        return CafGraph(get_caf(id)).diagrams()

    @app.get("/api/caf/{id}/graph")
    def caf_graph(id: str, ref: str):
        return CafGraph(get_caf(id)).diagram(ref)

    @app.post("/api/caf/{id}/rewire")
    def caf_rewire(id: str, body: CafPatchRequest):
        content, report = CafGraph(get_caf(id)).rewire_sources(body.changes)
        store.record(
            "caf.native.rewire.export",
            {
                "source_sha256": id,
                "changes": report,
                "scope": "Offline observed schema; vendor compiler and controller acceptance unverified",
            },
        )
        return Response(
            content,
            media_type="application/octet-stream",
            headers={"Content-Disposition": 'attachment; filename="rewired-copy.caf"'},
        )

    @app.post("/api/caf/{id}/connect")
    def caf_connect(id: str, body: CafPatchRequest):
        content, report = CafGraph(get_caf(id)).add_connections(body.changes)
        store.record(
            "caf.native.connection.export",
            {
                "source_sha256": id,
                "changes": report,
                "scope": "Offline observed native connection schema; vendor compiler and controller acceptance unverified",
            },
        )
        return Response(
            content,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="connected-copy.caf"',
            },
        )

    @app.get("/api/niagara/profile")
    def niagara_profile():
        from .niagara import DIFFERENCES, EXTENDED_DIFFERENCES, SUPPORTED

        return {
            "format": "Niagara BOG",
            "native_types": sorted(SUPPORTED),
            "differences": DIFFERENCES + EXTENDED_DIFFERENCES,
            "native_runtime_verified": False,
        }

    @app.post("/api/niagara/open")
    async def niagara_open(file: Annotated[UploadFile, File()]):
        archive = NiagaraArchive(await file.read(8 * 1024 * 1024 + 1))

        def archive_bytes(item):
            return len(item.original) + sum(len(member) for member in item.members.values())

        while (
            archive.hash not in niagara_files
            and niagara_files
            and (
                len(niagara_files) >= 16
                or sum(archive_bytes(item) for item in niagara_files.values())
                + archive_bytes(archive)
                > 64 * 1024 * 1024
            )
        ):
            del niagara_files[next(iter(niagara_files))]
        niagara_files[archive.hash] = archive
        return archive.summary()

    def get_niagara(id):
        if id not in niagara_files:
            raise ValueError(
                "BOG archive is not open in this server session. Open the original again."
            )
        return niagara_files[id]

    @app.get("/api/niagara/{id}")
    def niagara_archive(id: str):
        return get_niagara(id).summary()

    @app.post("/api/niagara/{id}/export")
    def niagara_export(id: str):
        archive = get_niagara(id)
        return Response(
            archive.export(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="original-copy.bog"',
            },
        )

    @app.post("/api/jci/hardware/open")
    async def hardware_open(file: Annotated[UploadFile, File()]):
        definition = JciHardwareDefinition(await file.read(8 * 1024 * 1024 + 1))
        while (
            definition.hash not in hardware_files
            and hardware_files
            and (
                len(hardware_files) >= 16
                or sum(len(item.original) for item in hardware_files.values())
                + len(definition.original)
                > 64 * 1024 * 1024
            )
        ):
            del hardware_files[next(iter(hardware_files))]
        hardware_files[definition.hash] = definition
        return definition.summary()

    def get_hardware(id):
        if id not in hardware_files:
            raise ValueError("Hardware definition is not open. Open the original XML again.")
        return hardware_files[id]

    @app.post("/api/jci/hardware/migration")
    def hardware_migration(body: HardwareMigration):
        return plan_hardware_migration(
            get_hardware(body.old_sha),
            get_hardware(body.new_sha),
            body.point_ids,
            body.system,
        )

    @app.get("/api/jci/hardware/{id}")
    def hardware_summary(id: str, system: Literal["imperial", "metric"] = "imperial"):
        return get_hardware(id).summary(system)

    @app.post("/api/jci/hardware/{id}/selection")
    def hardware_selection(id: str, body: HardwareSelection):
        return get_hardware(id).selection(body.point_ids, body.system)

    @app.post("/api/jci/hardware/{id}/export")
    def hardware_export(id: str):
        return Response(
            get_hardware(id).export(),
            media_type="application/xml",
            headers={"Content-Disposition": 'attachment; filename="original-hardware.xml"'},
        )

    @app.get("/api/iec/status")
    def iec_status():
        from .iec import profile

        return profile()

    @app.post("/api/iec/compile")
    async def iec_compile(body: IecProgram):
        from .iec import compile_program

        return await asyncio.to_thread(compile_program, body.program)

    @app.post("/api/iec/verify")
    async def iec_verify(body: IecVerify):
        from .iec import verify_program

        return await asyncio.to_thread(
            verify_program,
            body.program,
            body.inputs,
            scans=body.scans,
            dt=body.dt,
            clock=body.clock,
        )

    @app.post("/api/iec/scenario")
    async def iec_scenario(body: IecScenario):
        from .iec import verify_scenario

        return await asyncio.to_thread(
            verify_scenario,
            body.program,
            body.events,
            body.duration,
            dt=body.dt,
            clock=body.clock,
        )

    @app.get("/api/bacnet/status")
    def bacnet_status():
        return bacnet.status()

    @app.get("/api/bacnet/history/status")
    def bacnet_history_status():
        return history.status()

    @app.post("/api/bacnet/history/read")
    async def bacnet_history_read(body: BacnetHistoryRequest):
        return await history.read(**body.model_dump())

    @app.post("/api/bacnet/history/save")
    def bacnet_history_save(body: HistoryCaptureRequest):
        return history.save(body.id)

    @app.get("/api/bacnet/history/captures")
    def bacnet_history_captures():
        return history.captures()

    @app.get("/api/bacnet/history/captures/{id}")
    def bacnet_history_capture(id: str):
        return history.capture(id)

    @app.post("/api/bacnet/connect")
    async def bacnet_connect(body: BacnetConnect):
        return await bacnet.connect(**body.model_dump())

    @app.post("/api/bacnet/discover-foreign")
    async def bacnet_discover_foreign(body: BacnetForeignDiscover):
        return await bacnet.discover_foreign(**body.model_dump())

    @app.post("/api/bacnet/connect-mstp")
    async def bacnet_connect_mstp(body: BacnetMstp):
        return await bacnet.connect_mstp(**body.model_dump())

    @app.post("/api/bacnet/disconnect")
    async def bacnet_disconnect():
        return await bacnet.disconnect()

    @app.get("/api/temco/status")
    def temco_status():
        from .temco import native_status

        return native_status()

    @app.post("/api/temco/compile")
    async def temco_compile(body: TemcoProgram):
        import base64

        from .temco import compile_program

        result = await asyncio.to_thread(compile_program, body.program, bindings=body.bindings)
        result["bytecode_base64"] = base64.b64encode(result.pop("bytecode")).decode("ascii")
        return result

    @app.post("/api/temco/verify")
    async def temco_verify(body: TemcoVerify):
        from .temco import verify_program

        return await asyncio.to_thread(
            verify_program,
            body.program,
            body.inputs,
            bindings=body.bindings,
            scans=body.scans,
            clock=body.clock,
        )

    @app.get("/api/temco/transfer/status")
    def temco_transfer_status():
        return temco_transfer.status()

    @app.get("/api/temco/transfer/backups")
    def temco_transfer_backups():
        return temco_transfer.backups()

    @app.get("/api/temco/transfer/backups/{id}")
    def temco_transfer_backup(id: str):
        return temco_transfer.backup(id)

    @app.post("/api/temco/transfer/inspect")
    async def temco_transfer_inspect(body: TemcoTarget):
        return await temco_transfer.inspect(**body.model_dump())

    @app.post("/api/temco/transfer/plan")
    async def temco_transfer_plan(body: TemcoReplace):
        return await temco_transfer.plan_replace(**body.model_dump())

    @app.post("/api/temco/transfer/restore-plan")
    async def temco_transfer_restore(body: TemcoRestore):
        return await temco_transfer.plan_restore(**body.model_dump())

    @app.post("/api/temco/transfer/apply")
    async def temco_transfer_apply(body: TokenRequest):
        return await temco_transfer.apply(body.token)

    @app.post("/api/bacnet/discover")
    async def discover(body: BacnetDiscover):
        return await bacnet.discover(**body.model_dump())

    @app.post("/api/bacnet/read")
    async def read(body: BacnetRead):
        return await bacnet.read(**body.model_dump())

    @app.post("/api/bacnet/objects")
    async def objects(body: BacnetRead):
        return await bacnet.objects(body.address, body.object_id)

    @app.post("/api/bacnet/write-plan")
    async def write_plan(body: BacnetWrite):
        return await bacnet.plan_write(**body.model_dump())

    @app.post("/api/bacnet/write-apply")
    async def write_apply(body: TokenRequest):
        return await bacnet.apply_write(body.token)

    @app.post("/api/bacnet/release")
    async def release(body: TokenRequest):
        return await bacnet.release(body.token)

    @app.post("/api/modbus/read")
    async def modbus(body: ModbusRead):
        return await asyncio.to_thread(modbus_read, **body.model_dump(by_alias=True))

    @app.get("/api/runtime")
    async def runtime_status():
        return {**runtime.status(), "control": control}

    @app.post("/api/runtime/plan")
    async def runtime_plan(body: RuntimePlan):
        return runtime.plan(body.program, body.inputs)

    @app.post("/api/runtime/apply")
    async def runtime_apply(body: TokenRequest):
        return runtime.apply(body.token)

    @app.post("/api/runtime/rollback")
    async def runtime_rollback(body: RuntimeRollback):
        return runtime.rollback(body.backup_id, body.expected_generation)

    @app.post("/api/runtime/control")
    async def runtime_control(body: RuntimeControl):
        if body.running and not runtime.engine:
            raise ValueError("Deploy a program to the sandbox runtime first.")
        control.update(body.model_dump())
        return control

    @app.get("/api/audit")
    def audit():
        return store.audit()

    @app.get("/api/capabilities")
    def capabilities():
        return json.loads((ROOT / "docs" / "capabilities.json").read_text())

    @app.get("/api/references")
    def references():
        file = ROOT / "docs" / "references.json"
        return json.loads(file.read_text()) if file.exists() else []

    @app.get("/api/requirements")
    def requirements():
        return json.loads((ROOT / "docs/requirements.json").read_text())

    @app.get("/api/library/{collection}/{document_id}")
    def local_manual(collection: str, document_id: str):
        folder = {
            "jci": ROOT.parent / "Manual_Library",
            "multivendor": ROOT.parent / "Reference_Library",
        }.get(collection)
        if folder is None or not (folder / "catalog.json").exists():
            raise ValueError("Local manual collection is unavailable in this checkout.")
        records = json.loads((folder / "catalog.json").read_text())
        record = next(
            (
                r
                for r in records
                if r.get("id") == document_id and r.get("path", "").lower().endswith(".pdf")
            ),
            None,
        )
        if record is None:
            raise ValueError("Local PDF is not in the reference catalog.")
        path = (folder / record["path"]).resolve()
        if folder.resolve() not in path.parents or not path.is_file():
            raise ValueError("Catalog PDF is missing or outside the collection.")
        return FileResponse(path, media_type="application/pdf")

    dist = ROOT / "web" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    else:

        @app.get("/")
        def missing_build():
            return Response(
                "Build web assets with npm run build in web/, or use Vite development server on 127.0.0.1:5173.",
                media_type="text/plain",
            )

    return app
