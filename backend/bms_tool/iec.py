"""Execute generated IEC Structured Text through real MatIEC and native C.

The compiler/runtime headers are separately installed external dependencies.
Only Studio-generated ST is compiled; arbitrary uploaded C/ST is not executed.
This local host profile has no physical I/O, network or controller download.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import select
import shutil
import struct
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .engine import Engine, output_type
from .executable_numbers import require_number
from .file_access import file_lock
from .formats import ConversionError, export_st, iec_source_parts
from .iec_symbols import symbol_profile
from .macros import expand_macros
from .models import Program
from .source_profiles import source_profile

ROOT = Path(__file__).resolve().parents[2]
PIN = "3a41303bcb4e50403417bc39c63f88981d7d961e"
_LOCK = threading.RLock()
_CONFIGURATION = """
CONFIGURATION BMSCONFIG
RESOURCE BMSRESOURCE ON PLC
TASK BMSTASK(INTERVAL := T#1s, PRIORITY := 0);
PROGRAM BMSINSTANCE WITH BMSTASK : MAIN;
END_RESOURCE
END_CONFIGURATION
"""


def _library_digest(directory):
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(directory).as_posix().encode() + b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def toolchain():
    if os.name != "posix":
        raise ConversionError("The current native IEC host profile requires POSIX process pipes.")
    home = Path(os.environ.get("BMS_IEC_HOME", ROOT.parent / ".toolchain" / ("matiec-" + PIN[:12])))
    if not (home / "manifest.json").is_file() or not (home / "bin/iec2c").is_file():
        raise ConversionError("Native IEC compiler unavailable. Run scripts/setup_iec.py first.")
    manifest = json.loads((home / "manifest.json").read_text())
    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != "bms-iec-toolchain/1"
        or manifest.get("revision") != PIN
    ):
        raise ConversionError("The IEC toolchain does not match the pinned compiler profile.")
    if hashlib.sha256((home / "bin/iec2c").read_bytes()).hexdigest() != manifest.get(
        "binary_sha256"
    ):
        raise ConversionError("The IEC compiler checksum differs from its build manifest.")
    if not (home / "source/lib/C/iec_std_lib.h").is_file() or not shutil.which("clang"):
        raise ConversionError("Native IEC runtime headers or host clang compiler are unavailable.")
    if _library_digest(home / "source/lib") != manifest.get("library_sha256"):
        raise ConversionError("The IEC runtime library checksum differs from its build manifest.")
    return home.resolve(), manifest


@contextmanager
def _tool_lock(home):
    deadline = time.monotonic() + 45
    if not _LOCK.acquire(timeout=45):
        raise ConversionError("The IEC compiler queue is busy; retry after current work ends.")
    try:
        try:
            with file_lock(
                home / ".build.lock",
                timeout=max(0, deadline - time.monotonic()),
                busy="The IEC toolchain is busy rebuilding or compiling.",
            ):
                yield
        except ValueError as exc:
            raise ConversionError(str(exc)) from exc
    finally:
        _LOCK.release()


def profile():
    error, manifest = None, None
    try:
        _, manifest = toolchain()
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        error = str(exc)
    return {
        "available": error is None,
        "error": error,
        "compiler": "MatIEC iec2c then host clang",
        "revision": PIN,
        "execution": "compiled IEC Structured Text via MatIEC/native C",
        "host_initialization": "studio-iec-zero-initialized-main/1",
        "number_encoding": "studio-iec-json-negative-zero/1",
        "types": {"number": "IEC REAL / host IEEE float32", "boolean": "IEC BOOL"},
        "limits": {
            "nodes": 2000,
            "scans": 1000,
            "compile_seconds": 45,
            "compiler_invocations": 2,
            "queue_seconds": 45,
            "scan_seconds": 3,
        },
        "calendar": "IANA/date evaluation supplied by host; native validity flags fail closed",
        "physical_io": False,
        "controller_download": False,
        "certified": False,
        "provenance": manifest,
        "source_generator": source_profile(),
        "symbol_generator": symbol_profile(),
    }


def _run(args, *, cwd, timeout=45):
    try:
        result = subprocess.run(list(map(str, args)), cwd=cwd, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConversionError("IEC native tool did not finish: " + type(exc).__name__) from exc
    if result.returncode:
        raise ConversionError(
            "IEC compiler rejected the generated program: "
            + (result.stdout + result.stderr).decode(errors="replace")[-6000:]
        )
    return result


def _harness(declarations, output_nodes, symbols):
    fields = declarations["inputVars"]
    states = symbols.state_rows()
    lines = [
        "#include <stdio.h>",
        "#include <stdlib.h>",
        "#include <string.h>",
        "#include <math.h>",
        '#include "iec_std_lib.h"',
        '#include "accessor.h"',
        '#include "POUS.h"',
        '#include "POUS.c"',
        "TIME __CURRENT_TIME;",
        "static void number(double x) {",
        ' if (x == 0.0 && signbit(x)) fputs("-0.0", stdout);',
        ' else if (isfinite(x)) printf("%.9g", x); else fputs("null", stdout);',
        "}",
        "int main(void) {",
        " MAIN_data__ data = {0}; MAIN_init__(&data, 0); unsigned successful = 0, attempts = 0;",
        f" char line[{max(1024, len(fields) * 48 + 16)}]; double values[{max(1, len(fields))}];",
        " while (fgets(line, sizeof(line), stdin)) {",
        "  if (++attempts > 1000 || !strchr(line, '\\n')) return 2;",
        "  char *cursor = line, *next;",
        f"  for (unsigned i=0;i<{len(fields)};i++) {{ values[i]=strtod(cursor,&next); if(next==cursor || !isfinite(values[i])) return 2; cursor=next; }}",
        "  while (*cursor==' ' || *cursor=='\\t' || *cursor=='\\r' || *cursor=='\\n') cursor++; if(*cursor) return 2;",
    ]
    for index, (name, typ, _) in enumerate(fields):
        if typ == "BOOL":
            lines.append(f"  if(values[{index}]!=0.0 && values[{index}]!=1.0) return 2;")
        elif typ == "INT":
            lines.append(
                f"  if(values[{index}] < -32768 || values[{index}] > 32767 || floor(values[{index}]) != values[{index}]) return 2;"
            )
        lines.append(f"  data.{name.upper()}.value = ({typ})values[{index}];")
    lines += [
        "  MAIN_body__(&data); if(!data.STUDIOFAULT.value) successful++;",
        '  printf("{\\"fault\\":%s,\\"successful_scans\\":%u,\\"outputs\\":{", data.STUDIOFAULT.value?"true":"false", successful);',
    ]
    for index, node in enumerate(output_nodes):
        prefix = ("," if index else "") + json.dumps(node.id) + ":"
        lines.append("  fputs(" + json.dumps(prefix) + ", stdout);")
        member = "data." + symbols.role(node.id).upper() + ".value"
        lines.append(
            f'  fputs({member}?"true":"false",stdout);'
            if output_type(node) == "boolean"
            else f"  number({member});"
        )
    lines.append('  fputs("},\\"native_state\\":{", stdout);')
    for index, state in enumerate(states):
        prefix = ("," if index else "") + json.dumps(state["state_label"]) + ":"
        lines.append("  fputs(" + json.dumps(prefix) + ", stdout);")
        member = "data." + state["symbol"].upper() + ".value"
        lines.append(
            f'  fputs({member}?"true":"false",stdout);'
            if state["type"] == "BOOL"
            else f"  number({member});"
        )
    lines += ['  fputs("}}\\n", stdout); fflush(stdout);', " }", " return 0;", "}"]
    return "\n".join(lines) + "\n"


class NativeIEC:
    """Own a compiled executable and its independent graph-engine reference."""

    def __init__(self, program):
        self.program = Program.model_validate(program).model_copy(deep=True)
        self.graph = expand_macros(self.program)
        self.reference = Engine(self.program)
        self.declarations, _, self.symbols = iec_source_parts(self.program)
        if len(self.graph.nodes) > 2000:
            raise ConversionError("IEC host profile supports at most 2000 expanded nodes.")
        self.home, self.manifest = toolchain()
        self._directory = tempfile.TemporaryDirectory(prefix="bms-iec-")
        self.directory = Path(self._directory.name)
        self.process = None
        self.attempts = 0
        self.history = []
        self._io_lock = threading.RLock()
        self.outputs = [node for node in self.program.nodes if node.kind == "Output"]
        self.inputs = {node.id: node for node in self.program.nodes if node.kind == "Input"}
        self.source_st = export_st(self.program, embedded=False).decode()
        try:
            (self.directory / "program.st").write_text(self.source_st + _CONFIGURATION)
            with _tool_lock(self.home):
                _run(
                    [
                        self.home / "bin/iec2c",
                        "-I",
                        self.home / "source/lib",
                        "-T",
                        self.directory,
                        self.directory / "program.st",
                    ],
                    cwd=self.directory,
                )
                self.generated_c = (self.directory / "POUS.c").read_text()
                (self.directory / "host.c").write_text(
                    _harness(self.declarations, self.outputs, self.symbols)
                )
                result = _run(
                    [
                        "clang",
                        "-std=c11",
                        "-O2",
                        "-I" + str(self.home / "source/lib/C"),
                        "-I" + str(self.directory),
                        self.directory / "host.c",
                        "-lm",
                        "-o",
                        self.directory / "scan",
                    ],
                    cwd=self.directory,
                )
            warning_text = result.stderr.decode(errors="replace")
            self.warnings = {
                "count": warning_text.count("warning:"),
                "categories": sorted(set(re.findall(r"\[-W([^]]+)\]", warning_text))),
                "detail": warning_text[-2000:],
            }
            self._stderr = (self.directory / "runtime-stderr.txt").open("w+b")
            self.process = subprocess.Popen(
                [str(self.directory / "scan")],
                cwd=self.directory,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr,
                bufsize=0,
            )
            os.set_blocking(self.process.stdin.fileno(), False)
            os.set_blocking(self.process.stdout.fileno(), False)
        except BaseException:
            self.close()
            raise

    def _exchange(self, bindings):
        if self.process is None or self.process.poll() is not None:
            raise ConversionError("The native IEC process is stopped.")
        if self.attempts >= 1000:
            raise ConversionError("IEC verification session scan limit reached (1000).")
        values = [bindings[name] for name, _, _ in self.declarations["inputVars"]]
        for value in values:
            if type(value) is not bool:
                require_number(value, "IEC binding")
        request = (
            " ".join(
                str(int(value)) if type(value) is bool else format(value, ".17g")
                for value in values
            )
            + "\n"
        ).encode()
        if len(request) > 1024 * 1024:
            raise ConversionError("IEC scan request exceeds its bound.")
        deadline = time.monotonic() + 3
        offset, response = 0, bytearray()
        try:
            while offset < len(request):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([], [self.process.stdin], [], remaining)[1]:
                    raise TimeoutError
                offset += os.write(self.process.stdin.fileno(), request[offset:])
            while not response.endswith(b"\n"):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([self.process.stdout], [], [], remaining)[0]:
                    raise TimeoutError
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise OSError("Native IEC process closed its output.")
                response.extend(chunk)
                if len(response) > 1024 * 1024:
                    raise ValueError("Native IEC response exceeds its bound.")
            self.attempts += 1
            return json.loads(response)
        except (OSError, TimeoutError, ValueError) as exc:
            self.close()
            raise ConversionError("Native IEC scan failed: " + str(exc)) from exc

    def step(self, inputs=None, dt=None, clock=None, *, calendar_bindings=None):
        with self._io_lock:
            inputs = {} if inputs is None else inputs
            if not isinstance(inputs, dict) or inputs.keys() - self.inputs.keys():
                raise ValueError("IEC inputs must name existing graph Input blocks.")
            actual_dt = self.program.scan_seconds if dt is None else dt
            if (
                type(actual_dt) not in (int, float)
                or not 0 < actual_dt <= 60
                or not math.isfinite(actual_dt)
                or struct.unpack("f", struct.pack("f", actual_dt))[0] == 0
            ):
                raise ValueError("IEC scan duration must be finite and in (0,60] seconds.")
            try:
                current_clock = (
                    self.reference.clock + timedelta(seconds=actual_dt) if clock is None else clock
                )
            except OverflowError as exc:
                raise ValueError("IEC host clock exceeds the datetime range.") from exc
            if (
                not isinstance(current_clock, datetime)
                or current_clock.tzinfo is None
                or current_clock.utcoffset() is None
            ):
                raise ValueError("IEC host clock must be timezone-aware.")
            current_clock = current_clock.astimezone(UTC)
            bindings = {
                "StudioScanSeconds": actual_dt,
                "StudioDayOfWeek": current_clock.weekday(),
                "StudioMinuteOfDay": current_clock.hour * 60 + current_clock.minute,
            }
            for identifier, node in self.inputs.items():
                boolean = output_type(node) == "boolean"
                value = inputs.get(identifier, node.params.get("default", False if boolean else 0))
                quality = "good"
                if isinstance(value, dict):
                    if value.keys() - {"value", "quality"}:
                        raise ValueError(
                            "IEC input-quality wrappers accept only value and quality."
                        )
                    quality, value = value.get("quality", "good"), value.get("value")
                    if not isinstance(quality, str):
                        raise ValueError("IEC input quality must be a string.")
                if quality != "good":
                    value = False if boolean else 0
                if boolean:
                    if type(value) is not bool:
                        raise ValueError("IEC Boolean input type mismatch: " + identifier)
                else:
                    require_number(value, f"IEC numeric input {identifier}")
                    if (
                        type(value) not in (int, float)
                        or not -3.0e38 <= value <= 3.0e38
                        or not math.isfinite(value)
                    ):
                        raise ValueError(
                            "IEC numeric input must be finite and within ±3e38: " + identifier
                        )
                    if value and struct.unpack("f", struct.pack("f", value))[0] == 0:
                        raise ValueError("IEC numeric input underflows REAL: " + identifier)
                bindings[self.symbols.role(identifier)] = value
                bindings[self.symbols.role(identifier, "valid")] = quality == "good"
            host_fault = None
            calendars = {
                key: calendar
                for key, calendar in self.reference.calendars.items()
                if self.reference.nodes[key].params.get("timezone")
                or self.reference.nodes[key].params.get("exceptions")
            }
            if calendar_bindings is not None and (
                not isinstance(calendar_bindings, dict)
                or calendar_bindings.keys() - calendars.keys()
            ):
                raise ValueError("Calendar bindings must name hosted Schedule blocks.")
            for identifier, calendar in calendars.items():
                if calendar_bindings is None:
                    active, valid = calendar.active(current_clock), True
                else:
                    row = calendar_bindings.get(identifier, {"value": False, "valid": False})
                    if (
                        not isinstance(row, dict)
                        or set(row) != {"value", "valid"}
                        or type(row["value"]) is not bool
                        or type(row["valid"]) is not bool
                    ):
                        raise ValueError(
                            "Calendar host bindings need explicit Boolean value and valid fields."
                        )
                    active, valid = row["value"], row["valid"]
                bindings[self.symbols.role(identifier, "calendar")] = active
                bindings[self.symbols.role(identifier, "calendar_valid")] = valid
                if not valid:
                    host_fault = "Calendar host validity is false: " + identifier
            candidate = copy.deepcopy(self.reference)
            expected, expected_fault = None, host_fault
            if host_fault is None:
                try:
                    expected = candidate.step(inputs, actual_dt, current_clock)
                except ValueError as exc:
                    expected_fault = str(exc)
            native = self._exchange(bindings)
            comparison = expected["outputs"] if expected is not None else self.reference.outputs
            baseline = {
                node.id: comparison.get(node.id, False if output_type(node) == "boolean" else 0.0)
                for node in self.outputs
            }
            matches = native["fault"] == (expected_fault is not None)
            for identifier, value in baseline.items():
                actual = native["outputs"].get(identifier)
                matches = matches and (
                    type(actual) is bool and actual == value
                    if type(value) is bool
                    else type(actual) in (int, float)
                    and math.isfinite(actual)
                    and math.isclose(actual, value, rel_tol=2e-5, abs_tol=2e-4)
                )
            if expected is not None:
                self.reference = candidate
                self.reference.history = []
            row = {
                **native,
                "source_generator": source_profile(),
                "time": self.reference.time,
                "clock": current_clock.isoformat(),
                "reference_outputs": baseline,
                "reference_fault": expected_fault,
                "host_calendar_fault": host_fault,
                "matches_reference": bool(matches),
                "execution": "compiled IEC Structured Text via MatIEC/native C",
            }
            self.history = (self.history + [row])[-1000:]
            return row

    def compilation(self):
        return {
            "compiled": True,
            "native_runtime_verified": False,
            "source_st": self.source_st,
            "generated_c": self.generated_c,
            "program_sha256": self.program.digest(),
            "profile": profile(),
            "warnings": self.warnings,
            "source_generator": source_profile(),
            "symbol_table": self.symbols.evidence(),
        }

    def close(self):
        process, self.process = self.process, None
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()
        if hasattr(self, "_stderr"):
            self._stderr.close()
        self._directory.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def compile_program(program):
    with NativeIEC(program) as native:
        return native.compilation()


def verify_program(program, inputs=None, *, scans=1, dt=None, clock=None):
    if type(scans) is not int or not 1 <= scans <= 1000:
        raise ValueError("IEC verification scans must be an integer 1..1000.")
    with NativeIEC(program) as native:
        rows = [native.step(inputs, dt, clock if index == 0 else None) for index in range(scans)]
        return {
            "matches_reference": all(row["matches_reference"] for row in rows),
            "native_runtime_verified": True,
            "rows": rows,
            "program_sha256": native.program.digest(),
            "warnings": native.warnings,
            "profile": profile(),
            "symbol_table": native.symbols.evidence(),
        }


def verify_scenario(program, events, duration, dt=None, *, clock=None):
    program = Program.model_validate(program)
    actual_dt = program.scan_seconds if dt is None else dt
    if (
        type(actual_dt) not in (int, float)
        or not 0 < actual_dt <= 60
        or not math.isfinite(actual_dt)
        or struct.unpack("f", struct.pack("f", actual_dt))[0] == 0
    ):
        raise ValueError("IEC scenario timestep must be finite and in (0,60].")
    if (
        type(duration) not in (int, float)
        or not 0 < duration <= 86400
        or not math.isfinite(duration)
        or duration / actual_dt > 1000
    ):
        raise ValueError("IEC scenario must contain at most 1000 scans in 0..86400 seconds.")
    if not isinstance(events, list) or len(events) > 10000:
        raise ValueError("IEC scenario accepts at most 10000 timed input events.")
    for event in events:
        if (
            not isinstance(event, dict)
            or set(event) != {"time", "inputs"}
            or type(event["time"]) not in (int, float)
            or not 0 <= event["time"] <= duration
            or not math.isfinite(event["time"])
            or not isinstance(event["inputs"], dict)
        ):
            raise ValueError("IEC events need finite time within duration and an input map.")
    ordered = sorted(events, key=lambda event: event["time"])
    base = datetime(2026, 1, 5, tzinfo=UTC) if clock is None else clock
    if not isinstance(base, datetime) or base.tzinfo is None or base.utcoffset() is None:
        raise ValueError("IEC host clock must be timezone-aware.")
    try:
        base + timedelta(seconds=math.ceil(duration / actual_dt) * actual_dt)
    except OverflowError as exc:
        raise ValueError("IEC scenario exceeds the host datetime range.") from exc
    inputs, index, rows = {}, 0, []
    with NativeIEC(program) as native:
        for scan in range(math.ceil(duration / actual_dt)):
            while index < len(ordered) and ordered[index]["time"] <= scan * actual_dt:
                inputs.update(ordered[index]["inputs"])
                index += 1
            rows.append(
                native.step(inputs, actual_dt, base + timedelta(seconds=(scan + 1) * actual_dt))
            )
        return {
            "matches_reference": all(row["matches_reference"] for row in rows),
            "native_runtime_verified": True,
            "rows": rows,
            "program_sha256": native.program.digest(),
            "warnings": native.warnings,
            "profile": profile(),
            "symbol_table": native.symbols.evidence(),
        }
