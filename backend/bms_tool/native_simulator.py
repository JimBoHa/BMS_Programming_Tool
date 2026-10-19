"""Managed, loopback-only native Sedona controller simulation and online changes."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import secrets
import socket
import subprocess
import threading
import time
from datetime import timedelta

from .blocks import BLOCKS
from .engine import Engine, output_type
from .native_document import NativeDocument
from .sedona import compile_program, sox_request, toolchain


def _name(node_id):
    return "n_" + re.sub("[^A-Za-z0-9_]", "_", node_id)


def _value(text):
    if text in ("true", "false"):
        return text == "true"
    if text == "null":
        return None
    try:
        return float(text)
    except ValueError:
        return text


def _text(value):
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError("Native input must be a finite number or boolean.")
    return str(value)


def inventory(root):
    records = []

    def visit(element, parent=""):
        path = parent + "/" + element.get("name") if parent or element.get("id") != "0" else ""
        records.append(
            {
                "id": int(element.get("id")),
                "path": path or "/",
                "type": element.get("type"),
                "properties": [dict(p.attrib) for p in element.findall("property")],
                "links": [dict(p.attrib) for p in element.findall("link")],
            }
        )
        for child in element.findall("component"):
            visit(child, path)

    component = root.find("component")
    if component is not None:
        visit(component)
    return {"platform": root.get("platform"), "components": records}


def _configuration(snapshot):
    return [
        {**c, "properties": [p for p in c["properties"] if p["config"] == "true"]}
        for c in snapshot["components"]
        if c["path"].startswith("/online")
    ]


def _digest(snapshot):
    return hashlib.sha256(json.dumps(_configuration(snapshot), sort_keys=True).encode()).hexdigest()


def _document_configuration(snapshot):
    document = NativeDocument.from_snapshot(snapshot).model_dump()
    # Child order defines native execution order and stays significant. Link
    # enumeration order does not; every destination has exactly one writer.
    document["links"].sort(key=lambda link: json.dumps(link, sort_keys=True))
    return document


class NativeSimulator:
    """Owns only its spawned SVM. No discovery or field-controller connections."""

    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.process = None
        self.reference = None
        self.password = None
        self.port = None
        self.log = None
        self.folder = None
        self.generation = 0
        self.plans = {}
        self.backups = []
        self.history = []

    def status(self):
        with self.lock:
            available = False
            try:
                sdk, _ = toolchain()
                available = (sdk / "bin/svm-bms64").is_file()
            except ValueError:
                pass
            running = self.process is not None and self.process.poll() is None
            return {
                "available": available,
                "running": running,
                "kind": "Native Sedona SVM (experimental 64-bit Unix port)",
                "address": f"127.0.0.1:{self.port}" if running else None,
                "program": self.reference.program.model_dump() if self.reference else None,
                "time": self.reference.time if self.reference else 0,
                "generation": self.generation,
                "history": self.history[-200:],
                "backups": [{"id": b["id"], "generation": b["generation"]} for b in self.backups],
                "target": "Owned loopback simulation process; no physical I/O",
            }

    def stop(self):
        with self.lock:
            if self.process is not None:
                if self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=5)
                self.process = None
            if self.log:
                self.log.close()
                self.log = None
            self.password = None
            self.plans.clear()
            self.backups.clear()

    def start(self, program, *, record=True):
        with self.lock:
            candidate = Engine(program, allow_native_extension=True)
            sdk, _ = toolchain()
            executable = sdk / "bin/svm-bms64"
            if not executable.is_file():
                raise ValueError("Native SVM is missing. Run scripts/setup_sedona.py.")
            # Compile before stopping a working simulator, so compiler errors
            # cannot destroy its running state or commissioning backups.
            folder = self.store.directory / "native-simulation" / secrets.token_hex(8)
            folder.mkdir(parents=True, mode=0o700)
            password = secrets.token_hex(24)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reserve:
                reserve.bind(("127.0.0.1", 0))
                port = reserve.getsockname()[1]
            compile_program(program, folder, auth=("sim", password), port=port)
            self.stop()
            self.folder = folder.resolve()
            self.log = (self.folder / "svm.log").open("w")
            self.process = subprocess.Popen(
                [str(executable), str(self.folder / "kits.scode"), str(self.folder / "app.sab")],
                cwd=self.folder,
                stdout=self.log,
                stderr=subprocess.STDOUT,
            )
            self.password, self.port, self.reference = password, port, candidate
            self.history = []
            self.generation += 1
            try:
                # Startup uses the real Sox session handshake, not an elapsed-time
                # assumption. A failed process never becomes a ready controller.
                time.sleep(0.08)
                self._request([{"op": "read", "path": "/logic/graph", "slot": "successfulScans"}])
            except Exception:
                self.stop()
                raise
            if record:
                self.store.record(
                    "native.simulator.start",
                    {"program": program.digest(), "transport": "sox-loopback"},
                )
            return self.status()

    def _request(self, operations):
        if self.process is None or self.process.poll() is not None:
            raise ValueError("Native simulator is stopped.")
        return sox_request("127.0.0.1", self.port, "sim", self.password, operations)

    def inspect(self):
        with self.lock:
            return inventory(self._request([{"op": "inventory", "path": "/"}]))

    def snapshot_program(self):
        with self.lock:
            document = NativeDocument.from_snapshot(self.inspect())
            program = self.reference.program.model_copy(deep=True)
            if document.components:
                program.metadata["native_sedona"] = document.model_dump()
            else:
                program.metadata.pop("native_sedona", None)
            return program

    def save(self, expected_revision):
        with self.lock:
            program = self.snapshot_program()
            saved = self.store.save(program, expected_revision=expected_revision)
            self.reference.program = saved
            self.store.record(
                "native.project.save",
                {"id": saved.id, "revision": saved.revision, "sha256": saved.digest()},
            )
            return saved

    def step(self, inputs=None, dt=None, clock=None):
        with self.lock:
            if not self.reference:
                raise ValueError("Start a native simulator first.")
            inputs = inputs or {}
            candidate = copy.deepcopy(self.reference)
            expected, expected_fault = None, None
            try:
                expected = candidate.step(inputs, dt, clock)
            except ValueError as exc:
                expected_fault = str(exc)
            # Invalid types/unknown identifiers are API errors, not a simulated
            # sensor quality condition. Send every input each scan to prevent
            # stale values from a preceding partial override.
            nodes = {n.id: n for n in candidate.program.nodes if n.kind == "Input"}
            if set(inputs) - nodes.keys():
                raise ValueError("Unknown native input identifier.")
            actual_dt = candidate.program.scan_seconds if dt is None else dt
            if (
                type(actual_dt) not in (float, int)
                or not math.isfinite(actual_dt)
                or not 0 < actual_dt <= 60
            ):
                raise ValueError("Native timestep must be in (0,60].")
            current_clock = clock or self.reference.clock + timedelta(seconds=actual_dt)
            operations = []

            def write(slot, value):
                operations.append(
                    {"op": "write", "path": "/logic/graph", "slot": slot, "value": _text(value)}
                )

            for name, n in nodes.items():
                value = inputs.get(
                    name, n.params.get("default", BLOCKS["Input"].parameters["default"])
                )
                quality = "good"
                if isinstance(value, dict):
                    quality, value = value.get("quality", "good"), value.get("value")
                if quality != "good":
                    value = False if output_type(n) == "boolean" else 0
                if (output_type(n) == "boolean") != (type(value) is bool):
                    raise ValueError("Native input type mismatch: " + name)
                write(_name(name), value)
                write(_name(name) + "_valid", quality == "good")
            write("StudioScanSeconds", actual_dt)
            write("StudioDayOfWeek", current_clock.weekday())
            write("StudioMinuteOfDay", current_clock.hour * 60 + current_clock.minute)
            operations.append({"op": "invoke", "path": "/logic/graph", "slot": "step"})
            slots = ["StudioFault", "successfulScans"] + [
                _name(n.id) for n in candidate.program.nodes if n.kind == "Output"
            ]
            operations += [{"op": "read", "path": "/logic/graph", "slot": s} for s in slots]
            response = self._request(operations)
            values = {r.get("slot"): _value(r.get("value")) for r in response.findall("read")}
            outputs = {
                n.id: values[_name(n.id)] for n in candidate.program.nodes if n.kind == "Output"
            }
            matches = values["StudioFault"] == (expected_fault is not None)
            comparison = expected["outputs"] if expected else self.reference.outputs
            for key, value in comparison.items():
                actual = outputs[key]
                matches = matches and (
                    actual == value
                    if type(value) is bool
                    else actual is not None
                    and math.isclose(actual, value, rel_tol=2e-5, abs_tol=2e-4)
                )
            if expected and not values["StudioFault"]:
                self.reference = candidate
                self.reference.history = []
            row = {
                "time": self.reference.time,
                "clock": current_clock.isoformat(),
                "outputs": outputs,
                "fault": values["StudioFault"],
                "fault_detail": expected_fault,
                "successful_scans": values["successfulScans"],
                "matches_reference": bool(matches),
                "execution": "compiled Sedona SCode via native SVM",
            }
            self.history.append(row)
            self.history = self.history[-1000:]
            return row

    def plan(self, operations):
        with self.lock:
            if not 1 <= len(operations) <= 100:
                raise ValueError("Online plan requires 1–100 operations.")
            allowed = {
                "types::WriteFloat",
                "types::WriteBool",
                "types::ConstFloat",
                "types::ConstBool",
                "math::Add2",
                "math::Sub2",
                "math::Mul2",
                "math::Div2",
                "math::Min",
                "math::Max",
            }
            keys = {
                "add": {"op", "path", "name", "type"},
                "write": {"op", "path", "slot", "value"},
                "delete": {"op", "path"},
                "link": {"op", "path", "slot", "target", "target_slot"},
                "unlink": {"op", "path", "slot", "target", "target_slot"},
            }
            for operation in operations:
                if not isinstance(operation, dict) or any(
                    not isinstance(value, str) or len(value) > 256 for value in operation.values()
                ):
                    raise ValueError(
                        "Online operation fields must be strings of at most 256 characters."
                    )
                op, path = operation.get("op"), operation.get("path", "")
                if op not in ("add", "write", "delete", "link", "unlink"):
                    raise ValueError("Unsupported online operation.")
                if set(operation) != keys[op]:
                    raise ValueError("Online operation has missing or unexpected fields.")
                paths = [path] + ([operation.get("target", "")] if op in ("link", "unlink") else [])
                if any(
                    not re.fullmatch(r"/online(?:/[A-Za-z][A-Za-z0-9_]{0,6})*", p) for p in paths
                ):
                    raise ValueError(
                        "Online changes are confined to the native simulation commissioning folder."
                    )
                if op == "delete" and path == "/online":
                    raise ValueError("Cannot remove the commissioning root.")
                if op == "add":
                    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,6}", operation.get("name", "")):
                        raise ValueError(
                            "Sedona component names use 1–7 letters/digits/underscores."
                        )
                    if operation.get("type") not in allowed:
                        raise ValueError("Type is outside the tested native commissioning palette.")
            before = self.inspect()
            # Execute the proposed structural/configuration operations on a
            # separate native SVM first. The active simulator keeps running.
            shadow = NativeSimulator(self.store)
            try:
                shadow.start(self.reference.program, record=False)
                shadow._restore(before)
                shadow._request(operations)
                preflight = shadow.inspect()
                expected = _document_configuration(preflight)
            finally:
                shadow.stop()
                if shadow.folder:
                    import shutil

                    shutil.rmtree(shadow.folder)
            token = secrets.token_urlsafe(24)
            self.plans[token] = {
                "operations": copy.deepcopy(operations),
                "before": before,
                "digest": _digest(before),
                "expected": expected,
                "generation": self.generation,
                "expires": time.monotonic() + 300,
            }
            self.plans = {k: v for k, v in self.plans.items() if v["expires"] > time.monotonic()}
            return {
                "token": token,
                "generation": self.generation,
                "operations": operations,
                "preflight": preflight,
                "expires_in": 300,
                "target": "Owned native SVM /online",
                "atomic": False,
                "recovery": "Configuration snapshot and compensating rollback",
            }

    def _restore(self, snapshot):
        components = [c for c in snapshot["components"] if c["path"].startswith("/online/")]
        operations = [
            {"op": "delete", "path": "/online"},
            {"op": "add", "path": "/", "type": "sys::Folder", "name": "online"},
        ]
        for c in components:
            parent, name = c["path"].rsplit("/", 1)
            operations.append({"op": "add", "path": parent, "name": name, "type": c["type"]})
            operations += [
                {"op": "write", "path": c["path"], "slot": p["name"], "value": p["value"]}
                for p in c["properties"]
                if p["config"] == "true"
            ]
        by_id = {c["id"]: c for c in components}
        for c in components:
            for link in c["links"]:
                target = by_id.get(int(link["to"]))
                if target is None:
                    raise ValueError("Snapshot has a link outside the commissioning subtree.")
                source_slot = next(
                    p["name"] for p in c["properties"] if p["id"] == link["from_slot"]
                )
                target_slot = next(
                    p["name"] for p in target["properties"] if p["id"] == link["to_slot"]
                )
                operations.append(
                    {
                        "op": "link",
                        "path": c["path"],
                        "slot": source_slot,
                        "target": target["path"],
                        "target_slot": target_slot,
                    }
                )
        self._request(operations)

    def apply(self, token):
        with self.lock:
            plan = self.plans.pop(token, None)
            if (
                not plan
                or plan["expires"] < time.monotonic()
                or plan["generation"] != self.generation
            ):
                raise ValueError(
                    "Native plan expired, was consumed, or belongs to a different simulator generation."
                )
            if _digest(self.inspect()) != plan["digest"]:
                raise ValueError("Native configuration changed after preview. Create a new plan.")
            backup_id = secrets.token_hex(8)
            backup = {"id": backup_id, "snapshot": plan["before"], "generation": self.generation}
            self.store.record(
                "native.online.apply", {"backup": backup, "operations": plan["operations"]}
            )
            try:
                self._request(plan["operations"])
                actual = self.inspect()
                if _document_configuration(actual) != plan["expected"]:
                    raise ValueError("Native configuration readback differs from the preview.")
            except Exception:
                self.generation += 1
                self.plans.clear()
                try:
                    self._restore(plan["before"])
                    if _document_configuration(self.inspect()) != _document_configuration(
                        plan["before"]
                    ):
                        raise ValueError("Native recovery readback did not match the backup.")
                except Exception as recovery:
                    self.store.record("native.online.recovery_failed", {"backup_id": backup_id})
                    raise ValueError(
                        "Native change and recovery failed. Restart the simulator from a saved project."
                    ) from recovery
                self.store.record("native.online.compensated", {"backup_id": backup_id})
                raise
            self.backups.append(backup)
            self.backups = self.backups[-20:]
            self.generation += 1
            self.plans.clear()
            self.store.record("native.online.verified", {"backup_id": backup_id})
            return {"backup_id": backup_id, "status": self.status(), "inventory": actual}

    def rollback(self, backup_id, expected_generation):
        with self.lock:
            if expected_generation != self.generation:
                raise ValueError("Native generation changed; reload before rollback.")
            backup = next((b for b in self.backups if b["id"] == backup_id), None)
            if not backup:
                raise ValueError("Native configuration backup not found.")
            self.store.record("native.online.rollback", {"backup_id": backup_id})
            self._restore(backup["snapshot"])
            actual = self.inspect()
            if _document_configuration(actual) != _document_configuration(backup["snapshot"]):
                self.store.record("native.online.rollback_failed", {"backup_id": backup_id})
                raise ValueError("Native rollback readback differs from the backup.")
            self.generation += 1
            self.plans.clear()
            self.store.record("native.online.rollback_verified", {"backup_id": backup_id})
            return {"status": self.status(), "inventory": actual}
