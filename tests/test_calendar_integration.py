import copy
from datetime import UTC, datetime

from bms_tool.engine import Engine, validate
from bms_tool.formats import export_program, import_program
from bms_tool.iec_symbols import SymbolTable
from bms_tool.models import Edge, Node, Program


def calendar_program():
    return Program(
        id="calendar-test",
        nodes=[
            Node(
                id="occupied",
                kind="Schedule",
                params={
                    "timezone": "America/Los_Angeles",
                    "start": "08:00",
                    "end": "18:00",
                    "exceptions": [{"date": "2026-01-06", "enabled": False}],
                },
            ),
            Node(id="out", kind="Output", value_type="boolean"),
        ],
        edges=[Edge(id="e", source="occupied", target="out")],
    )


def test_engine_calendar_timezone_exception_and_copy_keep_source_intact():
    engine = Engine(calendar_program())
    assert engine.step(clock=datetime(2026, 1, 5, 17, tzinfo=UTC))["outputs"]["out"]
    assert not copy.deepcopy(engine).step(clock=datetime(2026, 1, 6, 17, tzinfo=UTC))["outputs"][
        "out"
    ]
    assert engine.clock.day == 5


def test_calendar_validation_and_exports_require_host_calendar_binding():
    p = calendar_program()
    symbols = SymbolTable(p)
    assert not [d for d in validate(p) if d.level == "error"]
    for fmt, suffix in (("st", "st"), ("plcopen", "xml")):
        data, _, _ = export_program(p, fmt)
        assert symbols.role("occupied", "calendar_valid").encode() in data
        assert symbols.role("occupied", "calendar").encode() in data
        assert import_program(data, "calendar." + suffix) == p
    p.nodes[0].params["timezone"] = "Unknown/Zone"
    assert any(d.code == "parameter" and "timezone" in d.message for d in validate(p))
