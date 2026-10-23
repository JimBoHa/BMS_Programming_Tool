"""Representative actual host pulse state/rollback, retaining compiler-returned bindings."""

import copy
import hashlib
import json
import os
import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest
from bms_tool import iec
from bms_tool.formats import export_st

from tests.test_cancelable_pulse_template import caller

pytestmark = pytest.mark.skipif(
    not iec.profile()["available"], reason="Optional pinned IEC unavailable"
)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()


class PulseOracle:
    """Independent two-instance Boolean/time recurrence, not the graph interpreter."""

    def __init__(self, duration, scan):
        self.duration, self.scan = duration, scan
        self.elapsed = {"first": 0, "second": 0}
        self.done = {"first": False, "second": False}
        self.outputs = {"first": False, "second": False}
        self.commits = 0

    def step(self, inputs):
        values = {}
        for name in self.outputs:
            value = inputs.get(name + "_request", False)
            if isinstance(value, dict):
                if value.get("quality", "good") != "good":
                    return True
                value = value.get("value", False)
            assert type(value) is bool
            values[name] = value
        for name, value in values.items():
            self.outputs[name] = value and not self.done[name]
            self.elapsed[name] = self.elapsed[name] + self.scan if value else 0
            self.done[name] = value and self.elapsed[name] >= self.duration
        self.commits += 1
        return False


@contextmanager
def retained_native(program, case, phase="only"):
    location = os.environ.get("BMS_PULSE_NATIVE_EVIDENCE")
    folder = Path(location) / case / phase if location else None
    native, process, failure, cleanup_errors, observations = None, None, None, [], []
    if folder:
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "original-constructor-program.json").write_bytes(
            program.model_dump_json().encode()
        )
        (folder / "pre-generated-input.st").write_bytes(
            export_st(program, embedded=False) + iec._CONFIGURATION.encode()
        )
    try:
        native = iec.NativeIEC(program)
        process = native.process
        compiled = native.compilation()
        table = compiled["symbol_table"]
        assert (
            table["sha256"]
            == hashlib.sha256(
                canonical({k: v for k, v in table.items() if k != "sha256"})
            ).hexdigest()
        )
        assert compiled["program_sha256"] == program.digest()
        if folder:
            original = folder / "compiler-originals"
            original.mkdir()
            for path in native.directory.iterdir():
                if path.is_file():
                    shutil.copyfile(path, original / path.name)
            assert (folder / "pre-generated-input.st").read_bytes() == (
                original / "program.st"
            ).read_bytes()
            assert (original / "POUS.c").read_text() == compiled["generated_c"]
            (folder / "original-compiler-expanded-graph.json").write_bytes(
                native.graph.model_dump_json().encode()
            )
            (folder / "original-compiler-returned-compilation.json").write_text(
                json.dumps(compiled, indent=2, allow_nan=False) + "\n"
            )
            (folder / "original-compiler-returned-symbol-table.json").write_text(
                json.dumps(table, indent=2, allow_nan=False) + "\n"
            )
        yield native, observations, table
    except BaseException as exc:
        failure = exc
    finally:
        try:
            if native is not None and folder:
                final = folder / "runtime-final"
                final.mkdir()
                for path in native.directory.iterdir():
                    if path.is_file():
                        shutil.copyfile(path, final / path.name)
                for name in ("program.st", "POUS.c", "host.c", "scan"):
                    assert (folder / "compiler-originals" / name).read_bytes() == (
                        final / name
                    ).read_bytes()
        except BaseException as exc:
            cleanup_errors.append(exc)
        finally:
            if native is not None:
                try:
                    native.close()
                except BaseException as exc:
                    cleanup_errors.append(exc)
        reaped = process is not None and process.poll() is not None
        if folder:
            (folder / "original-step-observations.json").write_text(
                json.dumps(observations, indent=2, allow_nan=False) + "\n"
            )
            files = {
                str(path.relative_to(folder)): {
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "bytes": path.stat().st_size,
                }
                for path in sorted(folder.rglob("*"))
                if path.is_file()
            }
            receipt = {
                "status": "passed"
                if failure is None and not cleanup_errors and reaped
                else "failed",
                "error": None if failure is None else repr(failure),
                "cleanup_errors": [repr(error) for error in cleanup_errors],
                "program_sha256": program.digest(),
                "worker_pid": None if process is None else process.pid,
                "worker_reaped": reaped,
                "worker_returncode": None if process is None else process.poll(),
                "submitted_scans": len(observations),
                "files": files,
                "qualification": "Original constructor Program and compiler-returned compilation/SymbolTable retained before first scan; actual compiler ST/C/host/executable copied at start and completion. Decoded NativeIEC.step observations are original API observations, not a raw stdout/packet capture. Pre-generated ST is explicitly labeled and compared to actual compiler ST only when construction returns. No SDK/compiler/engine/flags/deadline/tolerance changes or physical JCI claim.",
            }
            (folder / "EVIDENCE.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if failure is not None:
        raise failure
    if cleanup_errors:
        raise cleanup_errors[0]
    assert reaped, "Owned IEC worker was not reaped"


def run(native, rows, table, oracle, first=False, second=False):
    inputs = {"first_request": first, "second_request": second}
    old = copy.deepcopy((oracle.elapsed, oracle.done, oracle.outputs, oracle.commits))
    fault = oracle.step(inputs)
    row = {
        "inputs": inputs,
        "independent_expected": {
            "fault": fault,
            "outputs": oracle.outputs.copy(),
            "elapsed": oracle.elapsed.copy(),
            "done": oracle.done.copy(),
            "commits": oracle.commits,
            "time": oracle.commits * oracle.scan,
        },
    }
    rows.append(row)
    try:
        actual = native.step(inputs)
    except BaseException as exc:
        row["native_step_exception"] = repr(exc)
        raise
    row["native_step_observation"] = actual
    assert all(type(value) is bool for value in actual["outputs"].values())
    assert actual["fault"] is fault and actual["matches_reference"]
    assert actual["outputs"] == oracle.outputs
    assert (
        actual["successful_scans"] == oracle.commits
        and actual["time"] == oracle.commits * oracle.scan
    )
    # Map independent instance state to the actual compiler-returned original-ID roles.
    instances = [node for node in native.program.nodes if node.kind == "Macro"]
    bindings = {}
    incoming = {}
    for edge in native.graph.edges:
        incoming.setdefault(edge.target, []).append(edge.source)
    for name, instance in zip(("first", "second"), instances, strict=True):
        ancestors, pending = set(), [instance.id]
        while pending:
            identifier = pending.pop()
            if identifier in ancestors:
                continue
            ancestors.add(identifier)
            pending.extend(incoming.get(identifier, []))
        timers = [
            node for node in table["nodes"] if node["id"] in ancestors and node["kind"] == "TimerOn"
        ]
        memories = [
            node for node in table["nodes"] if node["id"] in ancestors and node["kind"] == "Delay"
        ]
        assert len(timers) == len(memories) == 1
        bindings[timers[0]["roles"]["elapsed"]["state_label"]] = oracle.elapsed[name]
        bindings[memories[0]["roles"]["memory"]["state_label"]] = oracle.done[name]
    assert len(bindings) == 4
    assert actual["native_state"] == bindings
    assert all(
        type(actual["native_state"][key]) is bool
        if type(value) is bool
        else type(actual["native_state"][key]) in (int, float)
        for key, value in bindings.items()
    )
    row["independent_expected_state_from_returned_table"] = bindings
    if fault:
        assert (oracle.elapsed, oracle.done, oracle.outputs, oracle.commits) == old
    return actual


@pytest.mark.parametrize(
    "case", ["one-second", "one-step-sixty", "held-cancel", "quality-retention", "fresh-restart"]
)
def test_actual_compiled_pulse_timing_state_quality_and_restart(case):
    duration, scan = {
        "one-second": (1, 1),
        "one-step-sixty": (60, 60),
        "held-cancel": (6, 2),
        "quality-retention": (3, 1),
        "fresh-restart": (5, 1),
    }[case]
    program = caller(duration, scan)
    with retained_native(program, case, "before" if case == "fresh-restart" else "only") as (
        native,
        rows,
        table,
    ):
        oracle = PulseOracle(duration, scan)
        if case in ("one-second", "one-step-sixty"):
            for first, second in [
                (False, False),
                (True, True),
                (True, True),
                (False, True),
                (True, False),
                (True, True),
            ]:
                run(native, rows, table, oracle, first, second)
        elif case == "held-cancel":
            for first, second in [
                (True, False),
                (False, True),
                (True, True),
                (True, True),
                (True, True),
                (True, True),
                (False, False),
                (True, True),
            ]:
                run(native, rows, table, oracle, first, second)
        elif case == "quality-retention":
            first = run(native, rows, table, oracle, {"value": True, "quality": "stale"})
            assert first["successful_scans"] == 0 and first["outputs"] == {
                "first": False,
                "second": False,
            }
            positive = run(native, rows, table, oracle, True, True)
            for quality in ("stale", "fault", "unreliable", "unknown"):
                rejected = run(
                    native, rows, table, oracle, {"value": False, "quality": quality}, False
                )
                assert rejected["native_state"] == positive["native_state"] and rejected[
                    "outputs"
                ] == {
                    "first": True,
                    "second": True,
                }
            run(native, rows, table, oracle, True, True)
            run(native, rows, table, oracle, True, True)
            run(native, rows, table, oracle, True, True)
            run(native, rows, table, oracle, False, True)
            run(native, rows, table, oracle, True, False)
        else:
            run(native, rows, table, oracle, True)
            run(native, rows, table, oracle, True)
    if case == "fresh-restart":
        # The first owned worker has exited before a fresh process starts from the same exact source.
        with retained_native(program, case, "after") as (native, rows, table):
            oracle = PulseOracle(duration, scan)
            run(native, rows, table, oracle)
            for _ in range(duration + 1):
                run(native, rows, table, oracle, True)
