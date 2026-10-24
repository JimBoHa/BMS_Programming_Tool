"""Actual unchanged IEC host: shared state, named mixed ports and rollback."""

import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from bms_tool import activities as a
from bms_tool import iec
from bms_tool.formats import export_st
from bms_tool.models import Edge, Node, Program, canonical

from tests.test_activities import caller


def feedback_calendar():
    graph = Program(
        id="state-and-calendar",
        nodes=[
            Node(id="increment", kind="Input"),
            Node(id="previous", kind="Delay", params={"initial": 0}),
            Node(id="accumulate", kind="Add"),
            Node(id="calendar", kind="Schedule", value_type="boolean", params={"timezone": "UTC"}),
            Node(id="total", kind="Output"),
            Node(id="prior", kind="Output"),
            Node(id="scheduled", kind="Output", value_type="boolean"),
        ],
        edges=[
            Edge(id="input", source="increment", target="accumulate", target_port="a"),
            Edge(id="feedback", source="previous", target="accumulate", target_port="b"),
            Edge(id="memory", source="accumulate", target="previous"),
            Edge(id="total", source="accumulate", target="total"),
            Edge(id="prior", source="previous", target="prior"),
            Edge(id="scheduled", source="calendar", target="scheduled"),
        ],
    )
    return Program(
        id="feedback-calendar-activities",
        nodes=[
            Node(id="delta", kind="Input", params={"default": 1}),
            Node(id="instance", kind="Activity", params={"definition": "state"}),
            Node(id="total", kind="Output"),
            Node(id="prior", kind="Output"),
            Node(id="scheduled", kind="Output", value_type="boolean"),
        ],
        edges=[
            Edge(id="input", source="delta", target="instance", target_port="increment"),
            *(
                Edge(id=port, source="instance", source_port=port, target=port)
                for port in ("total", "prior", "scheduled")
            ),
        ],
        metadata={
            "macros": {
                "version": 2,
                "definitions": [
                    {
                        "id": "state",
                        "name": "One shared accumulator/calendar",
                        "program": graph.model_dump(),
                    }
                ],
            }
        },
    )


def migrated():
    from tests.test_macro_integration import nested_rate_program

    return Program.model_validate(a.migration_preview(nested_rate_program())["program"])


CASES = {
    "mixed-unused-port": lambda: caller(),
    "nested-mixed": lambda: caller(nested=True),
    "two-independent-paths": lambda: caller(instances=2),
    "feedback-calendar": feedback_calendar,
    "explicit-v1-promotion": migrated,
}


@pytest.mark.skipif(
    not iec.profile()["available"], reason="Optional pinned MatIEC/clang unavailable"
)
@pytest.mark.parametrize("case", list(CASES))
def test_actual_named_activity_outputs_single_state_expansion_quality_and_native_bindings(case):
    program = CASES[case]()
    original = canonical(program)
    root = os.environ.get("BMS_ACTIVITY_NATIVE_EVIDENCE")
    folder = Path(root) / case if root else None
    native, process, failure, errors, rows = None, None, None, [], []
    if folder:
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "program.original.json").write_bytes(original)
        (folder / "resolve.original.json").write_bytes(a.canonical(a.resolve(program)))
        (folder / "pregenerated-program.st").write_bytes(
            export_st(program, embedded=False) + iec._CONFIGURATION.encode()
        )
    try:
        native = iec.NativeIEC(program)
        process = native.process
        compilation = native.compilation()
        if folder:
            # Capture actual returned compiler evidence before the first scan.
            (folder / "compilation.original.json").write_text(
                json.dumps(compilation, indent=2) + "\n"
            )
            (folder / "symbol-table.returned.json").write_text(
                json.dumps(compilation["symbol_table"], indent=2) + "\n"
            )
            (folder / "expanded.original.json").write_bytes(canonical(native.graph))
        assert compilation["activity_bindings"] == a.resolve(program)
        assert compilation["symbol_table"] == native.symbols.evidence()
        assert compilation["program_sha256"] == program.digest()
        assert {n["id"] for n in compilation["symbol_table"]["nodes"]} == {
            n.id for n in native.graph.nodes
        }
        if folder:
            assert (folder / "pregenerated-program.st").read_bytes() == (
                native.directory / "program.st"
            ).read_bytes()

        def run(inputs=None, **options):
            result = native.step(inputs, **options)
            rows.append(
                {
                    "inputs": inputs or {},
                    "options": {
                        k: v.isoformat() if isinstance(v, datetime) else v
                        for k, v in options.items()
                    },
                    "native_step_observation": result,
                }
            )
            assert result["matches_reference"], result
            assert "activity_bindings" not in result and "symbol_table" not in result
            return result

        if case == "feedback-calendar":
            first = run(clock=datetime(2026, 1, 5, 9, tzinfo=UTC))
            assert first["outputs"]["total"] == 1 and first["outputs"]["prior"] == 0
            assert first["outputs"]["scheduled"] is True
            second = run({"delta": 2})
            assert second["outputs"]["total"] == 3 and second["outputs"]["prior"] == 1
            schedule = next(n.id for n in native.graph.nodes if n.kind == "Schedule")
            failed = run(calendar_bindings={schedule: {"value": True, "valid": False}})
            assert failed["fault"] and failed["outputs"] == second["outputs"]
            assert failed["native_state"] == second["native_state"]
            final = run({"delta": 3})
            assert final["outputs"]["total"] == 6 and final["outputs"]["prior"] == 3
            assert len([n for n in native.graph.nodes if n.kind == "Delay"]) == 1
        else:
            first, second = run(), run()
            expected = (
                {"out_a": 1, "out_b": -1}
                if case == "explicit-v1-promotion"
                else {"value0": 2, "active0": True}
                | ({"value1": -2, "active1": False} if case == "two-independent-paths" else {})
            )
            assert first["outputs"] == expected
            assert second["outputs"] == {
                key: value if type(value) is bool else value * 2 for key, value in expected.items()
            }
            assert len([n for n in native.graph.nodes if n.kind == "Slew"]) == (
                2 if case in ("two-independent-paths", "explicit-v1-promotion") else 1
            )
        previous = rows[-1]["native_step_observation"]
        for node in (n for n in program.nodes if n.kind == "Input"):
            failed = run({node.id: {"quality": "unreliable"}})
            assert failed["fault"] and failed["outputs"] == previous["outputs"]
            assert failed["native_state"] == previous["native_state"]
            assert failed["successful_scans"] == previous["successful_scans"]
        assert canonical(program) == original
    except BaseException as exc:
        failure = exc
    finally:
        try:
            if native is not None and folder:
                for item in native.directory.iterdir():
                    if item.is_file():
                        shutil.copyfile(item, folder / item.name)
        except BaseException as exc:
            errors.append(exc)
        finally:
            if native is not None:
                try:
                    native.close()
                except BaseException as exc:
                    errors.append(exc)
        if folder:
            (folder / "frames.original.json").write_text(json.dumps(rows, indent=2) + "\n")
            (folder / "compiler-profile.original.json").write_text(
                json.dumps(iec.profile(), indent=2) + "\n"
            )
            (folder / "EVIDENCE.json").write_text(
                json.dumps(
                    {
                        "case": case,
                        "pid": process.pid if process else None,
                        "worker_returncode": process.poll() if process else None,
                        "reaped": process is not None and process.poll() is not None,
                        "failure": repr(failure) if failure else None,
                        "cleanup_errors": [repr(e) for e in errors],
                        "frames": len(rows),
                        "files": {
                            p.name: {
                                "bytes": p.stat().st_size,
                                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                            }
                            for p in sorted(folder.iterdir())
                            if p.is_file()
                        },
                    },
                    indent=2,
                )
                + "\n"
            )
        if failure:
            raise failure
        if errors:
            raise errors[0]
        assert process is not None and process.poll() is not None
