"""Loopback-only local application API. Field interfaces open only on explicit requests."""

from __future__ import annotations

import asyncio
import hashlib
import json
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

from .accumulator_prescale import PrescaleReviews, prescale_router
from .activities import activity_router
from .analysis import dependencies
from .bacnet_cov import BacnetCov, CovAction, CovStart
from .bacnet_event_ack import EventAckApply, EventAcknowledgements, EventAckPreview
from .bacnet_event_log import EventLogHistory, EventLogHistoryRequest
from .bacnet_events import EventCancelRequest, EventInventory, EventInventoryRequest
from .bacnet_files import BacnetFiles
from .bacnet_history import BacnetHistory, BacnetHistoryRequest
from .bacnet_history_multiple import MultipleHistory, MultipleHistoryCancel, MultipleHistoryRequest
from .bbmd_admin import BbmdAdmin, BbmdAdminApply, BbmdAdminPreview, BbmdAdminRestore
from .bbmd_tables import BbmdCancel, BbmdInspection, BbmdTables
from .blocks import catalog
from .bus_preflight import bus_preflight_router
from .caf import CafArchive
from .caf_compare import compare_cafs
from .caf_graph import CafGraph
from .caf_hardware import CafHardwareBindings, HardwareExportRequest, HardwareMoveRequest
from .caf_scenarios import CafInputScenarios, CafScenarioStore
from .caf_simulation import CafSimulationProfile
from .cancelable_pulse_template import cancelable_pulse_template_router
from .conformance import ConformancePlans, conformance_router
from .connections import Bacnet, modbus_read, ports
from .conversion_preview import conversion_preview
from .cov_observations import CovObservations
from .deployment import Runtime
from .device_details import DeviceDetails, DeviceDetailsRequest
from .engine import Engine, output_type, run_scenario, validate
from .enum_mapping import (
    EnumMappingExport,
    EnumMappingRequest,
    export_review,
    import_plan,
    review_enum_mapping,
)
from .equipment_wizard import wizard_router
from .event_reception import EventListenAction, EventListenStart, EventReception
from .field_trends import FieldTrends, FieldTrendStart
from .formats import export_program, import_program
from .hardware_workbench import HardwareWorkbench, hardware_router
from .heat_pump import heat_pump_router
from .hydronic_io import HydronicPlanner, hydronic_router
from .ip_discovery import IpDiscovery, IpScanRequest
from .jci_hardware import JciHardwareDefinition, plan_hardware_migration
from .jci_preflight import PreflightRequest, inventory_template, preflight
from .jci_release_rules import catalog as release_rule_catalog
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
from .madd_mz_ahu import madd_mz_ahu_router
from .masd_ahu import masd_ahu_router
from .models import Program, StrictModel
from .native_schedule_library import (
    MAX_ARCHIVE_BYTES,
    CaptureAction,
    NativeScheduleLibrary,
    WeeklyDayDraft,
)
from .native_schedule_write import (
    NativeWeeklyDayWrites,
    WeeklyWriteApply,
    WeeklyWriteCancel,
    WeeklyWritePreview,
    WeeklyWriteReconcile,
)
from .native_schedule_write import (
    encoded as native_write_json,
)
from .native_simulator import NativeSimulator
from .network_number_plan import network_plan_router
from .niagara import NiagaraArchive
from .observability import ObservabilityStore
from .operation_power import OperationPower
from .physical_capacity import capacity_router
from .plant_signals import PlantSignals, plant_signal_router
from .point_status import PointStatus, PointStatusCancel, PointStatusExport, PointStatusRequest
from .program_source import SourceMode, source_response
from .read_phase_trace import MAX_BYTES as READ_TRACE_MAX_BYTES
from .read_phase_trace import capture as capture_read_trace
from .read_phase_trace import freeze as freeze_read_trace
from .read_phase_trace import unavailable as unavailable_read_trace
from .resources import public_document, state_directory, web_directory
from .routed_discovery import (
    ProbeTrunkRequest,
    RoutedDiscovery,
    RoutedScanRequest,
    RouterBindingsRequest,
    RouterNetworksRequest,
    RouterProbeRequest,
)
from .schedule_coordination import schedule_coordination_router
from .schedule_inventory import (
    ScheduleAction,
    ScheduleExport,
    ScheduleInventory,
    ScheduleReadRequest,
)
from .sensor_supply import SupplyPlans, supply_router
from .series_fan_vav import series_fan_vav_router
from .simulation_group import SimulationGroups, SimulationWorkspace, demo_workspace
from .storage import Conflict, Store
from .sum8_macro_template import sum8_macro_template_router
from .temco_transfer import TemcoTransfer
from .templates import all_templates
from .truth_tables import TruthTables, truth_table_router
from .unit_ventilator_cycle3 import unit_ventilator_cycle3_router
from .zone_setpoints import zone_setpoint_router

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
    operation_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class SimulationRetire(StrictModel):
    session: str = Field(strict=True, pattern=r"^[A-Za-z0-9_-]{20,64}$")
    retirement_token: str = Field(strict=True, pattern=r"^[A-Za-z0-9_-]{32,64}$")
    creation_operation_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


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


class ConversionPreviewRequest(StrictModel):
    program: Program


class CafPatchRequest(StrictModel):
    changes: list[dict[str, Any]] = Field(max_length=1000)


class CafSimulationRequest(StrictModel):
    profile: dict[str, Any]


class CafLocalScenarioRequest(StrictModel):
    scenario: dict[str, Any]


class CafLocalScenarioSave(CafLocalScenarioRequest):
    id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    expected_revision: int = Field(ge=0, strict=True)


class CafLocalScenarioFrame(CafLocalScenarioRequest):
    time: float = Field(ge=0, le=86400, strict=True)


class CafLocalScenarioDelete(StrictModel):
    expected_revision: int = Field(ge=1, strict=True)


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


class BacnetObjects(BacnetRead):
    offset: int = Field(default=0, ge=0, le=20000, strict=True)
    limit: int = Field(default=100, ge=1, le=200, strict=True)
    timeout_seconds: float = Field(default=15.0, ge=1, le=30, strict=True)


class BacnetFileInspect(StrictModel):
    address: str = Field(min_length=1, max_length=256)
    device: str = Field(min_length=1, max_length=80)


class BacnetFileRead(StrictModel):
    inspection_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    object_id: str = Field(min_length=1, max_length=80)
    metadata_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


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


def create_app(state_dir=None, *, operation_power=None):
    store = Store(state_dir or state_directory())
    conformance = ConformancePlans(store)
    runtime = Runtime(store)
    bacnet = Bacnet(store)
    native = NativeSimulator(store)
    groups = SimulationGroups()
    observations = ObservabilityStore(store.directory)
    field_trends = FieldTrends(bacnet, store.directory, audit_store=store)
    cov_recordings = CovObservations(field_trends.store)
    cov = BacnetCov(bacnet, store, recorder=cov_recordings)
    power = operation_power if operation_power is not None else OperationPower()
    temco_transfer = TemcoTransfer(bacnet, store, operation_power=power)
    history = BacnetHistory(bacnet, store)
    multiple_history = MultipleHistory(bacnet, store)
    event_log = EventLogHistory(bacnet, store)
    routed = RoutedDiscovery(bacnet, store)
    ip_discovery = IpDiscovery(bacnet, store)
    bbmd_tables = BbmdTables(bacnet, store)
    bbmd_admin_error = None
    try:
        bbmd_admin = BbmdAdmin(bacnet, bbmd_tables, store.directory)
    except (ValueError, OSError, sqlite3.Error) as exc:
        bbmd_admin = None
        bbmd_admin_error = "BBMD administration unavailable: " + str(exc)[:1000]
    device_details = DeviceDetails(bacnet, store)
    schedule_inventory = ScheduleInventory(bacnet, store)
    schedule_library = NativeScheduleLibrary(store.directory, schedule_inventory)
    schedule_writes = NativeWeeklyDayWrites(bacnet, store, schedule_library)
    point_status = PointStatus(bacnet, store)
    event_inventory = EventInventory(bacnet, store)
    event_ack = EventAcknowledgements(bacnet, store, event_inventory)
    event_reception = EventReception(bacnet, store)
    files = BacnetFiles(bacnet, store)
    hardware_workbench = HardwareWorkbench(bacnet, store, files)
    supply_plans = SupplyPlans(store, hardware_workbench)
    notifications = None
    simulations = {}
    caf_files = {}
    caf_scenarios = CafScenarioStore(store)
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
            app.state.power_shutdown = await power.close()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await schedule_writes.close()
            try:
                try:
                    try:
                        await point_status.close()
                    finally:
                        await schedule_inventory.close()
                finally:
                    if bbmd_admin is not None:
                        await bbmd_admin.close()
            finally:
                try:
                    await bbmd_tables.close()
                finally:
                    try:
                        if notifications is not None:
                            await notifications.close()
                    finally:
                        try:
                            await field_trends.close()
                        finally:
                            try:
                                await hardware_workbench.close()
                            finally:
                                try:
                                    try:
                                        await event_reception.close()
                                    finally:
                                        await cov.close()
                                finally:
                                    try:
                                        await event_ack.close()
                                    finally:
                                        try:
                                            await event_inventory.close()
                                        finally:
                                            try:
                                                await event_log.close()
                                            finally:
                                                try:
                                                    await multiple_history.close()
                                                finally:
                                                    try:
                                                        bacnet.close()
                                                    finally:
                                                        native.stop()

    app = FastAPI(title="BMS Studio local API", version="0.1.0", lifespan=lifespan)
    app.state.runtime = runtime
    app.state.store = store
    app.state.bacnet = bacnet
    app.state.bacnet_cov = cov
    app.state.native = native
    app.state.field_trends = field_trends
    app.state.temco_transfer = temco_transfer
    app.state.operation_power = power
    app.state.bacnet_history = history
    app.state.multiple_history = multiple_history
    app.state.event_log = event_log
    app.state.routed_discovery = routed
    app.state.ip_discovery = ip_discovery
    app.state.bbmd_tables = bbmd_tables
    app.state.bbmd_admin = bbmd_admin
    app.state.bbmd_admin_startup_error = bbmd_admin_error
    app.state.device_details = device_details
    app.state.schedule_inventory = schedule_inventory
    app.state.schedule_library = schedule_library
    app.state.point_status = point_status
    app.state.plant_signals = PlantSignals(store)
    app.include_router(plant_signal_router(app.state.plant_signals))
    app.state.hydronic_io = HydronicPlanner(app.state.plant_signals, hardware_workbench)
    app.include_router(hydronic_router(app.state.hydronic_io))
    app.state.prescale_reviews = PrescaleReviews(point_status)
    app.include_router(prescale_router(app.state.prescale_reviews))
    app.state.event_inventory = event_inventory
    app.state.event_ack = event_ack
    app.state.schedule_writes = schedule_writes
    app.state.event_reception = event_reception
    app.state.bacnet_files = files
    app.state.hardware_workbench = hardware_workbench
    app.state.notifications = None
    app.include_router(hardware_router(hardware_workbench))
    app.include_router(capacity_router(hardware_workbench))
    app.include_router(supply_router(supply_plans))
    app.state.truth_tables = TruthTables()
    app.include_router(truth_table_router(app.state.truth_tables))
    app.include_router(network_plan_router())
    app.include_router(bus_preflight_router())
    app.include_router(conformance_router(conformance))
    app.include_router(wizard_router())
    app.include_router(schedule_coordination_router())
    app.include_router(heat_pump_router())
    app.include_router(masd_ahu_router())
    app.include_router(madd_mz_ahu_router())
    app.include_router(zone_setpoint_router())
    app.include_router(series_fan_vav_router())
    app.include_router(unit_ventilator_cycle3_router())
    app.include_router(sum8_macro_template_router())
    app.include_router(cancelable_pulse_template_router())
    app.include_router(activity_router())

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
    def blocks(source_transport: SourceMode = False):
        return source_response(catalog(), source_transport, kind="blocks")

    @app.get("/api/templates")
    def templates(source_transport: SourceMode = False):
        return source_response([p.model_dump() for p in all_templates()], source_transport)

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
    def macros_create(body: MacroSelection, source_transport: SourceMode = False):
        return source_response(
            create_definition(body.program, body.selected_ids, body.name), source_transport
        )

    @app.post("/api/macros/instantiate")
    def macros_instantiate(body: MacroInstance, source_transport: SourceMode = False):
        return source_response(
            instantiate_macro(body.program, body.definition, body.x, body.y), source_transport
        )

    @app.post("/api/macros/definition")
    def macros_definition(body: MacroReference, source_transport: SourceMode = False):
        return source_response(
            inspect_macro_definition(body.program, body.definition), source_transport
        )

    @app.post("/api/macros/delete")
    def macros_delete(body: MacroReference, source_transport: SourceMode = False):
        return source_response(
            delete_macro_definition(body.program, body.definition), source_transport
        )

    @app.post("/api/macros/export")
    def macros_export(body: MacroReference, source_transport: SourceMode = False):
        return source_response(
            export_macro_library(body.program, body.definition), source_transport
        )

    @app.post("/api/macros/import")
    def macros_import(body: MacroImport, source_transport: SourceMode = False):
        return source_response(import_macro_library(body.program, body.bundle), source_transport)

    @app.post("/api/macros/update")
    def macros_update(body: MacroUpdate, source_transport: SourceMode = False):
        return source_response(
            update_macro_definition(body.program, body.definition, body.replacement),
            source_transport,
        )

    @app.get("/api/groups/demo")
    def group_demo(source_transport: SourceMode = False):
        return source_response(demo_workspace(), source_transport)

    @app.get("/api/groups")
    def group_list():
        return groups.list()

    @app.post("/api/groups/start")
    def group_start(body: GroupStart, source_transport: SourceMode = False):
        return source_response(groups.start(body.definition, body.replace), source_transport)

    @app.get("/api/groups/{session}")
    def group_status(session: str, source_transport: SourceMode = False):
        return source_response(groups.status(session), source_transport)

    @app.post("/api/groups/step")
    def group_step(body: GroupStep, source_transport: SourceMode = False):
        if body.clock is not None and body.steps != 1:
            raise ValueError("An explicit clock applies to one group cycle.")
        group = groups.get(body.session)
        for _ in range(body.steps):
            group.step(body.inputs, clock=body.clock)
        return source_response(groups.status(body.session), source_transport)

    @app.post("/api/groups/reset")
    def group_reset(body: GroupRequest, source_transport: SourceMode = False):
        groups.get(body.session).reset()
        return source_response(groups.status(body.session), source_transport)

    @app.post("/api/groups/close")
    def group_close(body: GroupRequest):
        groups.close(body.session)
        return {"closed": True}

    @app.post("/api/groups/export")
    def group_export(body: GroupRequest):
        return Response(groups.export(body.session), media_type="application/json")

    @app.post("/api/groups/import")
    async def group_import(
        file: Annotated[UploadFile, File()],
        replace: str | None = None,
        source_transport: SourceMode = False,
    ):
        content = await file.read(8 * 1024 * 1024 + 1)
        return source_response(groups.import_file(content, replace), source_transport)

    @app.get("/api/projects")
    def projects():
        return store.projects()

    @app.post("/api/projects")
    def save(body: SaveRequest, source_transport: SourceMode = False):
        return source_response(store.save(body.program, body.expected_revision), source_transport)

    @app.get("/api/projects/{id}/versions")
    def versions(id: str):
        return store.versions(id)

    @app.get("/api/projects/{id}")
    def project(id: str, revision: int | None = None, source_transport: SourceMode = False):
        return source_response(store.load(id, revision), source_transport)

    @app.post("/api/import")
    async def import_file(
        file: Annotated[UploadFile, File()], source_transport: SourceMode = False
    ):
        content = await file.read(8 * 1024 * 1024 + 1)
        try:
            return source_response(import_program(content, file.filename or ""), source_transport)
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

    @app.post("/api/conversion/preview")
    def preview_conversion(body: ConversionPreviewRequest):
        return conversion_preview(body.program)

    @app.get("/api/native/status")
    def native_status(source_transport: SourceMode = False):
        return source_response(native.status(), source_transport)

    @app.post("/api/native/start")
    def native_start(body: NativeStart, source_transport: SourceMode = False):
        return source_response(native.start(body.program), source_transport)

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
    def native_save(body: NativeSave, source_transport: SourceMode = False):
        return source_response(native.save(body.expected_revision), source_transport)

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

    def expire_simulation_sessions():
        now = time.monotonic()
        for id in [k for k, v in simulations.items() if now - v["touched"] > 3600]:
            del simulations[id]
        return now

    @app.get("/api/simulation/sessions/status")
    async def simulation_session_status():
        expire_simulation_sessions()
        return {"cached_sessions": len(simulations), "limit": 25, "idle_expiry_seconds": 3600}

    @app.post("/api/simulation/retire")
    async def retire_simulation(body: SimulationRetire):
        expire_simulation_sessions()
        record = simulations.get(body.session)
        if record is not None:
            if (
                not secrets.compare_digest(record["retirement_token"], body.retirement_token)
                or record["creation_operation_id"] != body.creation_operation_id
            ):
                raise ValueError("Simulation retirement ownership does not match this session.")
            del simulations[body.session]
        return {
            "session": body.session,
            "retired": record is not None,
            "recorded_evidence_unchanged": True,
            "scope": "Only the volatile calculation session is removed. Recorded history and alarm lifecycle are unchanged; admitted scans are not rolled back.",
        }

    @app.post("/api/simulation/step")
    async def step(body: SimulationRequest):
        if body.clock is not None and body.steps != 1:
            raise ValueError("An explicit clock applies to one scan; use single-step mode.")
        created = not body.session
        now = expire_simulation_sessions()
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
            record = {
                "engine": Engine(body.program),
                "touched": now,
                "retirement_token": secrets.token_urlsafe(24),
                "creation_operation_id": body.operation_id,
            }
            simulations[id] = record
        engine = record["engine"]
        record["touched"] = now
        rows = []
        scan_error = None
        recording_errors = []
        source = f"simulation/{body.program.id}/{id}"
        for _ in range(body.steps):
            try:
                row = engine.step(body.inputs, body.dt, body.clock, forces=body.forces)
            except ValueError as exc:
                if not rows:
                    # No scan or observation committed for this new, undisclosed session.
                    if created:
                        simulations.pop(id, None)
                    if body.operation_id is None:
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
            "session": None if created and not rows else id,
            "retirement_token": None if created and not rows else record["retirement_token"],
            "session_creation_operation_id": record["creation_operation_id"],
            "last": rows[-1] if rows else None,
            "history": engine.history[-300:],
            "snapshot": engine.snapshot(),
            "recording_source": source if body.record and not (created and not rows) else None,
            "recording_error": "; ".join(recording_errors) or None,
            "scan_error": scan_error,
            "completed_steps": len(rows),
            "requested_steps": body.steps,
            "operation_id": body.operation_id,
            "applied_dt": engine.program.scan_seconds if body.dt is None else body.dt,
            "program_id": engine.program.id,
            "program_revision": engine.program.revision,
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

    @app.get("/api/jci/preflight/release-rules")
    def preflight_release_rules():
        return release_rule_catalog()

    @app.get("/api/jci/preflight/template")
    def preflight_template():
        return inventory_template()

    @app.get("/api/caf/{id}/preflight")
    def caf_preflight_inspect(id: str):
        return preflight(get_caf(id), PreflightRequest())

    @app.post("/api/caf/{id}/preflight")
    def caf_preflight(id: str, body: PreflightRequest):
        hardware = get_hardware(body.hardware_sha256.lower()) if body.hardware_sha256 else None
        return preflight(get_caf(id), body, hardware)

    @app.post("/api/caf/{id}/preflight/export")
    def caf_preflight_export(id: str, body: PreflightRequest):
        hardware = get_hardware(body.hardware_sha256.lower()) if body.hardware_sha256 else None
        return Response(
            json.dumps(preflight(get_caf(id), body, hardware), indent=2, ensure_ascii=True),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="jci-target-readiness.json"'},
        )

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

    @app.get("/api/caf/{id}/hardware")
    def caf_hardware(id: str):
        return CafHardwareBindings(get_caf(id)).summary()

    @app.post("/api/caf/{id}/hardware/preview")
    def caf_hardware_preview(id: str, body: HardwareMoveRequest):
        return CafHardwareBindings(get_caf(id)).preview(body)

    @app.post("/api/caf/{id}/hardware/export")
    def caf_hardware_export(id: str, body: HardwareExportRequest):
        content, plan = CafHardwareBindings(get_caf(id)).export(body)
        store.record(
            "caf.hardware.export",
            {
                "source_sha256": id,
                "output_sha256": hashlib.sha256(content).hexdigest(),
                "plan": plan,
                "native_validation": "pending",
            },
        )
        return Response(
            content,
            media_type="application/octet-stream",
            headers={"Content-Disposition": 'attachment; filename="hardware-copy.caf"'},
        )

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

    @app.get("/api/caf/{id}/local-scenarios")
    def caf_local_scenarios(id: str):
        adapter = CafInputScenarios(get_caf(id))
        return {
            "contract": adapter.contract(),
            "template": adapter.template(),
            "saved": caf_scenarios.list(adapter),
        }

    @app.post("/api/caf/{id}/local-scenarios/validate")
    def caf_local_scenario_validate(id: str, body: CafLocalScenarioRequest):
        return {"scenario": CafInputScenarios(get_caf(id)).validate(body.scenario)}

    @app.post("/api/caf/{id}/local-scenarios/preview")
    def caf_local_scenario_preview(id: str, body: CafLocalScenarioRequest):
        return CafInputScenarios(get_caf(id)).preview(body.scenario)

    @app.post("/api/caf/{id}/local-scenarios/startup-profile")
    def caf_local_scenario_startup(id: str, body: CafLocalScenarioFrame):
        return {"profile": CafInputScenarios(get_caf(id)).startup_profile(body.scenario, body.time)}

    @app.post("/api/caf/{id}/local-scenarios/save")
    def caf_local_scenario_save(id: str, body: CafLocalScenarioSave):
        return caf_scenarios.save(
            CafInputScenarios(get_caf(id)), body.scenario, body.id, body.expected_revision
        )

    @app.get("/api/caf/{id}/local-scenarios/{scenario_id}")
    def caf_local_scenario_load(id: str, scenario_id: str):
        return caf_scenarios.load(CafInputScenarios(get_caf(id)), scenario_id)

    @app.delete("/api/caf/{id}/local-scenarios/{scenario_id}")
    def caf_local_scenario_delete(id: str, scenario_id: str, body: CafLocalScenarioDelete):
        return caf_scenarios.delete(
            CafInputScenarios(get_caf(id)), scenario_id, body.expected_revision
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

    @app.get("/api/bacnet/cov/status")
    async def cov_status():
        return cov.status()

    @app.get("/api/bacnet/event-reception/status")
    async def event_listen_status():
        return event_reception.status()

    @app.get("/api/bacnet/event-reception/sessions/{id}")
    async def event_listen_detail(id: str):
        return event_reception.detail(id)

    @app.post("/api/bacnet/event-reception/start")
    async def event_listen_start(body: EventListenStart):
        return await event_reception.start(**body.model_dump())

    @app.post("/api/bacnet/event-reception/stop")
    async def event_listen_stop(body: EventListenAction):
        return await event_reception.stop(body.id)

    @app.post("/api/bacnet/event-reception/save")
    async def event_listen_save(body: EventListenAction):
        return await event_reception.save(body.id)

    @app.get("/api/bacnet/event-reception/snapshots")
    def event_listen_snapshots():
        return event_reception.snapshots()

    @app.get("/api/bacnet/event-reception/snapshots/{id}")
    def event_listen_snapshot(id: str):
        return event_reception.saved(id)

    @app.get("/api/bacnet/cov/jobs/{id}")
    async def cov_detail(id: str):
        return cov.detail(id)

    @app.get("/api/bacnet/cov/recordings")
    def cov_saved_recordings():
        return cov_recordings.recordings()

    @app.get("/api/bacnet/cov/recordings/{id}/events")
    def cov_saved_events(id: str, after: int = 0, limit: int = 100):
        return cov_recordings.events(id, after=after, limit=limit)

    @app.get("/api/bacnet/cov/recordings/{id}/page")
    def cov_saved_page(id: str, after: int = 0, limit: int = 100):
        return cov_recordings.page(id, after=after, limit=limit)

    @app.post("/api/bacnet/cov/start")
    async def cov_start(body: CovStart):
        return await cov.start(**body.model_dump())

    @app.post("/api/bacnet/cov/renew")
    async def cov_renew(body: CovAction):
        return await cov.renew(body.id)

    @app.post("/api/bacnet/cov/stop")
    async def cov_stop(body: CovAction):
        return await cov.stop(body.id)

    @app.get("/api/bacnet/routed-profile")
    def bacnet_routed_profile():
        return routed.status()

    @app.get("/api/bacnet/ip-scan-profile")
    def bacnet_ip_scan_profile():
        return ip_discovery.status()

    @app.post("/api/bacnet/scan-ip")
    async def bacnet_scan_ip(body: IpScanRequest):
        return await ip_discovery.scan(**body.model_dump())

    @app.get("/api/bacnet/device-details/profile")
    def bacnet_device_details_profile():
        return device_details.status()

    @app.post("/api/bacnet/device-details")
    async def bacnet_device_details(body: DeviceDetailsRequest):
        return await device_details.read(**body.model_dump())

    @app.post("/api/enum-mapping/review")
    async def enum_mapping_review(body: EnumMappingRequest):
        return review_enum_mapping(body)

    @app.post("/api/enum-mapping/export")
    async def enum_mapping_export(body: EnumMappingExport):
        return Response(
            json.dumps(export_review(body), sort_keys=True, separators=(",", ":"), allow_nan=False),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="enum-mapping-review.json"'},
        )

    @app.post("/api/enum-mapping/plan-export")
    async def enum_mapping_plan_export(body: EnumMappingExport):
        return Response(
            json.dumps(
                export_review(body)["source_plan"],
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="enum-mapping-plan.json"'},
        )

    @app.post("/api/enum-mapping/import")
    async def enum_mapping_import(file: UploadFile):
        return import_plan(await file.read(2 * 1024 * 1024 + 1))

    @app.get("/api/bacnet/point-status/profile")
    async def bacnet_point_status_profile():
        return point_status.status()

    @app.get("/api/bacnet/point-status/reports/{id}")
    async def bacnet_point_status_detail(id: str):
        return point_status.detail(id)

    @app.post("/api/bacnet/point-status/read")
    async def bacnet_point_status_read(body: PointStatusRequest):
        return await point_status.read(**body.model_dump())

    @app.post("/api/bacnet/point-status/read-diagnostics")
    async def bacnet_point_status_read_diagnostics(body: PointStatusRequest):
        # The native operation/cache/limits are unchanged. Diagnostic data never
        # enters the core report or its evidence seal.
        with capture_read_trace() as collector:
            report = await point_status.read(**body.model_dump())
        core = await bacnet_point_status_export(PointStatusExport(id=report["id"]))
        try:
            core_bytes = core.body
            document = {
                "format": "bms.native-read-diagnostic-envelope/1",
                "core_report_id": report["id"],
                "core_report_json": core_bytes.decode("utf-8"),
                "core_report_sha256": hashlib.sha256(core_bytes).hexdigest(),
                "trace_profile": "studio-readproperty-phase-trace/1",
                "trace": freeze_read_trace(collector),
            }
            response = JSONResponse(document)
            # JSON quoting can double core bytes; this is an independent wrapper
            # bound, never permission to truncate or re-seal the core report.
            wrapper_limit = 4 * 1024 * 1024 + READ_TRACE_MAX_BYTES + 4096
            if len(response.body) > wrapper_limit:
                document["trace"] = unavailable_read_trace("Diagnostic wrapper capacity reached.")
                response = JSONResponse(document)
            if len(response.body) <= wrapper_limit:
                return response
        except BaseException:
            pass
        # A diagnostic-only failure returns the original core Response. The UI
        # treats it as core evidence with diagnostics unavailable, never retries.
        core.headers["X-Studio-Diagnostics"] = "unavailable"
        return core

    @app.post("/api/bacnet/point-status/cancel")
    async def bacnet_point_status_cancel(body: PointStatusCancel):
        return point_status.cancel(body.operation_id)

    @app.post("/api/bacnet/point-status/export")
    async def bacnet_point_status_export(body: PointStatusExport):
        return Response(
            json.dumps(
                point_status.detail(body.id), sort_keys=True, separators=(",", ":"), allow_nan=False
            ),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="point-status-{body.id}.json"'},
        )

    @app.get("/api/bacnet/schedules/profile")
    async def bacnet_schedules_profile():
        return schedule_inventory.status()

    @app.get("/api/bacnet/schedules/reports/{id}")
    async def bacnet_schedule_detail(id: str):
        return schedule_inventory.detail(id)

    @app.post("/api/bacnet/schedules/read")
    async def bacnet_schedules_read(body: ScheduleReadRequest):
        return await schedule_inventory.read(**body.model_dump())

    @app.post("/api/bacnet/schedules/cancel")
    async def bacnet_schedules_cancel(body: ScheduleAction):
        return schedule_inventory.cancel(body.operation_id)

    @app.post("/api/bacnet/schedules/export")
    async def bacnet_schedules_export(body: ScheduleExport):
        report = schedule_inventory.detail(body.id)
        # Export exact server JSON. Client parse/stringify would lose -0.0 and
        # integral float spelling, invalidating the evidence-body hash.
        return Response(
            json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="bacnet-schedules-{body.id}.json"'
            },
        )

    @app.get("/api/bacnet/schedules/library/profile")
    def bacnet_schedule_library_profile():
        return schedule_library.status()

    @app.get("/api/bacnet/schedules/library/captures/{id}")
    def bacnet_schedule_capture(id: str):
        return schedule_library.detail(id)

    @app.post("/api/bacnet/schedules/library/save")
    def bacnet_schedule_capture_save(body: ScheduleExport):
        return schedule_library.save(body.id)

    @app.post("/api/bacnet/schedules/library/import")
    async def bacnet_schedule_capture_import(file: UploadFile):
        return await asyncio.to_thread(
            schedule_library.import_capture, await file.read(MAX_ARCHIVE_BYTES + 1)
        )

    @app.post("/api/bacnet/schedules/library/export")
    def bacnet_schedule_capture_export(body: CaptureAction):
        return Response(
            schedule_library.archive(body.id),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="native-schedule-capture-{body.id}.json"'
            },
        )

    @app.post("/api/bacnet/schedules/library/source-export")
    def bacnet_schedule_source_export(body: CaptureAction):
        return Response(
            schedule_library.source(body.id),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="native-schedule-source-{body.id}.json"'
            },
        )

    @app.post("/api/bacnet/schedules/library/drafts/review")
    def bacnet_schedule_draft_review(body: WeeklyDayDraft):
        return schedule_library.review(**body.model_dump())

    @app.post("/api/bacnet/schedules/library/drafts/export")
    def bacnet_schedule_draft_export(body: CaptureAction):
        return Response(
            schedule_library.export_review(body.id),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="native-schedule-day-draft-{body.id}.json"'
            },
        )

    @app.post("/api/bacnet/schedules/library/drafts/import")
    async def bacnet_schedule_draft_import(file: UploadFile):
        return await asyncio.to_thread(
            schedule_library.import_review, await file.read(256 * 1024 + 1)
        )

    @app.get("/api/bacnet/schedules/writes/profile")
    def bacnet_schedule_write_profile():
        return schedule_writes.status()

    @app.post("/api/bacnet/schedules/writes/preview")
    async def bacnet_schedule_write_preview(body: WeeklyWritePreview):
        return Response(
            native_write_json(await schedule_writes.preview(**body.model_dump())),
            media_type="application/json",
        )

    @app.post("/api/bacnet/schedules/writes/apply")
    async def bacnet_schedule_write_apply(body: WeeklyWriteApply):
        return Response(
            await schedule_writes.apply(**body.model_dump()), media_type="application/json"
        )

    @app.post("/api/bacnet/schedules/writes/cancel")
    async def bacnet_schedule_write_cancel(body: WeeklyWriteCancel):
        return schedule_writes.cancel(body.operation_id)

    @app.get("/api/bacnet/schedules/writes/receipts/{id}")
    def bacnet_schedule_write_receipt(id: str):
        return Response(
            schedule_writes.journal.receipt(id),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="native-weekly-write-{id}.json"'
            },
        )

    @app.post("/api/bacnet/schedules/writes/reconcile")
    async def bacnet_schedule_write_reconcile(body: WeeklyWriteReconcile):
        return Response(
            await schedule_writes.reconcile(**body.model_dump()), media_type="application/json"
        )

    @app.get("/api/bacnet/events/profile")
    def bacnet_events_profile():
        return event_inventory.status()

    @app.post("/api/bacnet/events/read")
    async def bacnet_events_read(body: EventInventoryRequest):
        return await event_inventory.read(**body.model_dump())

    @app.post("/api/bacnet/events/cancel")
    async def bacnet_events_cancel(body: EventCancelRequest):
        return event_inventory.cancel(body.operation_id)

    @app.get("/api/bacnet/events/ack/profile")
    def bacnet_event_ack_profile():
        return event_ack.status()

    @app.post("/api/bacnet/events/ack/preview")
    async def bacnet_event_ack_preview(body: EventAckPreview):
        return await event_ack.preview(**body.model_dump())

    @app.post("/api/bacnet/events/ack/apply")
    async def bacnet_event_ack_apply(body: EventAckApply):
        return await event_ack.apply(**body.model_dump())

    @app.post("/api/bacnet/events/ack/cancel")
    async def bacnet_event_ack_cancel(body: EventCancelRequest):
        return event_ack.cancel(body.operation_id)

    @app.get("/api/bacnet/events/ack/receipts/{identifier}")
    def bacnet_event_ack_receipt(identifier: str):
        return event_ack.receipt(identifier)

    @app.post("/api/bacnet/router-networks")
    async def bacnet_router_networks(body: RouterNetworksRequest):
        return await routed.networks(**body.model_dump())

    @app.post("/api/bacnet/router-bindings")
    async def bacnet_router_bindings(body: RouterBindingsRequest):
        return await routed.bindings(**body.model_dump())

    @app.post("/api/bacnet/scan-trunk")
    async def bacnet_scan_trunk(body: RoutedScanRequest):
        return await routed.scan(**body.model_dump())

    @app.post("/api/bacnet/probe-controller")
    async def bacnet_probe_controller(body: RouterProbeRequest):
        return await routed.probe(**body.model_dump())

    @app.post("/api/bacnet/probe-trunk")
    async def bacnet_probe_trunk(body: ProbeTrunkRequest):
        return await routed.probe_range(**body.model_dump())

    @app.get("/api/bacnet/files/status")
    def bacnet_files_status():
        return files.status()

    @app.post("/api/bacnet/files/inspect")
    async def bacnet_files_inspect(body: BacnetFileInspect):
        return await files.inspect_config(**body.model_dump())

    @app.post("/api/bacnet/files/read")
    async def bacnet_files_read(body: BacnetFileRead):
        return await files.read_raw_file(**body.model_dump())

    @app.get("/api/bacnet/files/captures")
    def bacnet_file_captures():
        return files.captures()

    @app.get("/api/bacnet/files/captures/{id}")
    def bacnet_file_capture(id: str):
        return files.capture(id)

    @app.get("/api/bacnet/files/captures/{id}/export")
    def bacnet_file_export(id: str):
        content, name, content_type = files.export(id)
        return Response(
            content,
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

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

    @app.get("/api/bacnet/history-multiple/status")
    def bacnet_multiple_history_status():
        return multiple_history.status()

    @app.post("/api/bacnet/history-multiple/read")
    async def bacnet_multiple_history_read(body: MultipleHistoryRequest):
        return await multiple_history.read(**body.model_dump())

    @app.post("/api/bacnet/history-multiple/cancel")
    async def bacnet_multiple_history_cancel(body: MultipleHistoryCancel):
        return multiple_history.cancel(body.operation_id)

    @app.post("/api/bacnet/history-multiple/save")
    def bacnet_multiple_history_save(body: HistoryCaptureRequest):
        return multiple_history.save(body.id)

    @app.get("/api/bacnet/history-multiple/captures/{id}")
    def bacnet_multiple_history_capture(id: str):
        return multiple_history.capture(id)

    @app.get("/api/bacnet/event-log/status")
    def bacnet_event_log_status():
        return event_log.status()

    @app.post("/api/bacnet/event-log/read")
    async def bacnet_event_log_read(body: EventLogHistoryRequest):
        return await event_log.read(**body.model_dump())

    @app.post("/api/bacnet/event-log/cancel")
    async def bacnet_event_log_cancel(body: MultipleHistoryCancel):
        return event_log.cancel(body.operation_id)

    @app.post("/api/bacnet/event-log/save")
    def bacnet_event_log_save(body: HistoryCaptureRequest):
        return event_log.save(body.id)

    @app.get("/api/bacnet/event-log/captures/{id}")
    def bacnet_event_log_capture(id: str):
        return event_log.capture(id)

    @app.post("/api/bacnet/connect")
    async def bacnet_connect(body: BacnetConnect):
        await schedule_writes.close()
        await event_ack.close()
        await event_inventory.close()
        await event_log.close()
        await multiple_history.close()
        return await bacnet.connect(**body.model_dump())

    def bbmd_admin_service():
        if bbmd_admin is None:
            raise ValueError(bbmd_admin_error or "BBMD administration unavailable.")
        return bbmd_admin

    @app.get("/api/bacnet/bbmd-admin/status")
    async def bbmd_admin_status():
        if bbmd_admin is None:
            return {"available": False, "reason": bbmd_admin_error, "active": []}
        return bbmd_admin.status()

    @app.get("/api/bacnet/bbmd-admin/history")
    async def bbmd_admin_history():
        return await bbmd_admin_service().saved_history()

    @app.get("/api/bacnet/bbmd-admin/receipts/{id}")
    async def bbmd_admin_receipt(id: str):
        return await bbmd_admin_service().saved_detail(id)

    @app.post("/api/bacnet/bbmd-admin/preview")
    async def bbmd_admin_preview(body: BbmdAdminPreview):
        return await bbmd_admin_service().preview(**body.model_dump())

    @app.post("/api/bacnet/bbmd-admin/apply")
    async def bbmd_admin_apply(body: BbmdAdminApply):
        return await bbmd_admin_service().apply(**body.model_dump())

    @app.post("/api/bacnet/bbmd-admin/cancel")
    async def bbmd_admin_cancel(body: BbmdCancel):
        return await bbmd_admin_service().cancel(body.id)

    @app.post("/api/bacnet/bbmd-admin/restore-preview")
    async def bbmd_admin_restore_preview(body: BbmdAdminRestore):
        return await bbmd_admin_service().restore_preview(body.id, body.timeout_seconds)

    @app.get("/api/bacnet/bbmd-tables/status")
    async def bbmd_table_status():
        return bbmd_tables.status()

    @app.get("/api/bacnet/bbmd-tables/jobs/{id}")
    async def bbmd_table_detail(id: str):
        return bbmd_tables.detail(id)

    @app.post("/api/bacnet/bbmd-tables/start")
    async def bbmd_table_start(body: BbmdInspection):
        return bbmd_tables.start(**body.model_dump())

    @app.post("/api/bacnet/bbmd-tables/cancel")
    async def bbmd_table_cancel(body: BbmdCancel):
        return await bbmd_tables.cancel(body.id)

    @app.post("/api/bacnet/discover-foreign")
    async def bacnet_discover_foreign(body: BacnetForeignDiscover):
        return await bacnet.discover_foreign(**body.model_dump())

    @app.post("/api/bacnet/connect-mstp")
    async def bacnet_connect_mstp(body: BacnetMstp):
        await schedule_writes.close()
        await event_ack.close()
        await event_inventory.close()
        await event_log.close()
        await multiple_history.close()
        return await bacnet.connect_mstp(**body.model_dump())

    @app.post("/api/bacnet/disconnect")
    async def bacnet_disconnect():
        await schedule_writes.close()
        await event_ack.close()
        await event_inventory.close()
        await event_log.close()
        await multiple_history.close()
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

    @app.get("/api/operation-power")
    def operation_power_status():
        return power.status()

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
    async def objects(body: BacnetObjects):
        return await bacnet.objects(
            body.address, body.object_id, body.offset, body.limit, body.timeout_seconds
        )

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
        return public_document("capabilities.json")

    @app.get("/api/references")
    def references():
        return public_document("references.json")

    @app.get("/api/requirements")
    def requirements():
        return public_document("requirements.json")

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

    dist = web_directory()
    if dist is not None:
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    else:

        @app.get("/")
        def missing_build():
            return Response(
                "Build web assets with npm run build in web/, or use Vite development server on 127.0.0.1:5173.",
                media_type="text/plain",
            )

    return app
