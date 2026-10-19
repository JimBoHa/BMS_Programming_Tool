"""Loopback-only local application API. Field interfaces open only on explicit requests."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import time
import xml.etree.ElementTree as XML
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from .blocks import catalog
from .caf import CafArchive
from .connections import Bacnet, modbus_read, ports
from .deployment import Runtime
from .engine import Engine, run_scenario, validate
from .formats import export_program, import_program
from .models import Program, StrictModel
from .native_simulator import NativeSimulator
from .storage import Conflict, Store
from .templates import all_templates

ROOT = Path(__file__).resolve().parents[2]


class SimulationRequest(StrictModel):
    program: Program
    inputs: dict[str, Any] = Field(default_factory=dict)
    dt: float | None = None
    session: str | None = None
    steps: int = Field(default=1, ge=1, le=1000)
    clock: datetime | None = None


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


class SaveRequest(StrictModel):
    program: Program
    expected_revision: int = Field(ge=0)


class ExportRequest(StrictModel):
    program: Program
    format: str


class CafPatchRequest(StrictModel):
    changes: list[dict[str, Any]] = Field(max_length=1000)


class BacnetConnect(StrictModel):
    local_address: str
    instance: int = 4190001
    router: str | None = None
    dnet: int | None = None


class BacnetDiscover(StrictModel):
    address: str
    low: int = 0
    high: int = 4194302


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


def create_app(state_dir=None):
    store = Store(state_dir or os.environ.get("BMS_STUDIO_DATA", str(ROOT / ".state")))
    runtime = Runtime(store)
    bacnet = Bacnet(store)
    native = NativeSimulator(store)
    simulations = {}
    caf_files = {}
    session_token = secrets.token_urlsafe(32)
    control = {"running": False, "inputs": {}, "error": None}

    @asynccontextmanager
    async def lifespan(app):
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

        task = asyncio.create_task(ticks())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        bacnet.close()
        native.stop()

    app = FastAPI(title="BMS Studio local API", version="0.1.0", lifespan=lifespan)
    app.state.runtime = runtime
    app.state.store = store
    app.state.bacnet = bacnet
    app.state.native = native

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

    @app.get("/api/session")
    def session():
        return {
            "token": session_token,
            "version": "0.1.0",
            "field_network_open": bacnet.app is not None,
        }

    @app.get("/api/blocks")
    def blocks():
        return catalog()

    @app.get("/api/templates")
    def templates():
        return [p.model_dump() for p in all_templates()]

    @app.post("/api/validate")
    def validation(program: Program):
        return {"issues": [d.model_dump() for d in validate(program)]}

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
        rows = [engine.step(body.inputs, body.dt, body.clock) for _ in range(body.steps)]
        return {
            "session": id,
            "last": rows[-1],
            "history": engine.history[-300:],
            "snapshot": engine.snapshot(),
        }

    @app.post("/api/simulation/scenario")
    async def scenario(body: ScenarioRequest):
        return {"history": run_scenario(body.program, body.events, body.duration, body.dt)}

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

    @app.get("/api/bacnet/status")
    def bacnet_status():
        return bacnet.status()

    @app.post("/api/bacnet/connect")
    async def bacnet_connect(body: BacnetConnect):
        return await bacnet.connect(**body.model_dump())

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
