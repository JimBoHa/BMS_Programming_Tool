"""Exercise elapsed-time registers decoded from the authored native fixture."""

from collections import deque
from functools import reduce
from math import floor
from operator import add, and_, eq, ge, gt, or_, sub, xor
from random import Random

import pytest
from bms_tool.moi_identity import MoiIdentity
from bms_tool.native_inline_sequence import (
    SPECS,
    CompactInlineSequenceCompiler,
    InlineSequenceCompiler,
)
from bms_tool.native_inline_sequence_62 import (
    EdgeTimedInlineSequenceCompiler,
    LegacyInlineSequenceCompiler,
)

from .test_native_inline_sequence import authored_source


class PhasePeer:
    def __init__(self, *, compact=False, legacy=False, edge=False, model="FX-PCV1630-0"):
        source = authored_source(model=model)
        library = authored_source(catalog=True, model=model, wide=legacy)[3]
        compiler = (
            EdgeTimedInlineSequenceCompiler(source, library, 200)
            if edge
            else LegacyInlineSequenceCompiler(source, library, 200)
            if legacy
            else CompactInlineSequenceCompiler(source, library, 200)
            if compact
            else InlineSequenceCompiler(source, library, 200, phase_sampling=True)
        )
        compiler.body()
        raw, report = compiler.export(shadow=True)
        app = MoiIdentity(raw)
        diagram = app.reader.diagram(report["root_ref"])
        self.points = {block["name"]: block["index"] for block in diagram["blocks"]}
        by_ref = {block["ref"]: block["index"] for block in diagram["blocks"]}
        self.inputs = {
            (by_ref[e["target_ref"]], e["target_port"]): by_ref[e["source_ref"]]
            for e in diagram["connections"]
        }
        self.output_ports = {
            (by_ref[e["target_ref"]], e["target_port"]): e["source_port"]
            for e in diagram["connections"]
        }
        children = {}
        for ref, record in app.reader.records.items():
            parent = ref.rpartition(".")[0]
            children.setdefault(parent, {})[app.reader.scalar(record, 3365)] = app.reader.scalar(
                record, 3113
            )
        kinds = {spec[0]: name for name, spec in SPECS.items()}
        kinds[30] = "eq"
        self.blocks = {
            b["index"]: (
                kinds.get(app.reader.scalar(app.reader.records[b["ref"]], 3670)),
                children.get(b["ref"], {}),
            )
            for b in diagram["blocks"]
        }
        self.order = diagram["execution_order"]
        self.memory = {}
        self.timers = {}

    def run(self, sec, flow, *, healthy=True, demand=100, phase=None):
        labels = self.points
        boundary = {
            "Inline normalized second": (60 - floor(sec) % 60) % 60 if phase is None else phase,
            "Inline countdown is reliable": True,
            "Inline supply flow valid": healthy,
            "Inline valid flow or zero": flow if healthy else 0,
            "Inline lesser of room and cap": demand,
        }
        if "Inline long clock reading" in labels:
            boundary.update(
                {
                    "Inline long clock reading": (3601 - sec % 3601) % 3601,
                    "Inline long clock reliable": True,
                }
            )
        seeds = {labels[n]: v for n, v in boundary.items()}
        ready = labels["Inline complete timed history"]
        permit = labels["Inline final automatic permit"]
        mean = labels["Inline complete 30-second mean"]
        output = labels["Inline protected valve command"]
        needed = set()

        def include(i):
            if i in needed or i in seeds or i == permit:
                return
            needed.add(i)
            for (dest, _), source in self.inputs.items():
                if dest == i:
                    include(source)

        for i in (ready, mean, output):
            include(i)
        ops = {
            "and": and_,
            "or": or_,
            "xor": xor,
            "add": add,
            "sub": sub,
            "min": min,
            "max": max,
            "ge": ge,
            "eq": eq,
            "gt": gt,
            "div": lambda a, b: a / b,
        }
        for _ in range(7):
            values = seeds.copy()
            pending = {}
            for i in self.order:
                if i == permit:
                    values[i] = values[ready] and values[mean] >= 30
                if i not in needed:
                    continue
                kind, default = self.blocks[i]

                def get(port, index=i, defaults=default, observed=values):
                    source = self.inputs.get((index, port))
                    if source is None:
                        return defaults[port]
                    if self.output_ports[index, port] == 1081:
                        return observed[source, 1081]
                    return observed[source]

                if kind in ("prevF", "prevB"):
                    values[i] = self.memory.get(i, 0)
                    pending[i] = self.inputs[i, 513]
                elif kind == "timer":
                    on = bool(get(513))
                    mode = get(518)
                    length = get(1080)
                    prev, edge = self.timers.get(i, (False, None))
                    if mode == 1:
                        if on and not prev:
                            edge = sec
                        age = sec - edge if edge is not None else length
                        values[i] = age < length
                        values[i, 1081] = max(0, length - floor(age))
                    elif on != prev:
                        edge = sec
                    if mode == 2:
                        values[i] = on and edge is not None and sec - edge >= length
                    elif mode == 4:
                        values[i] = on or edge is not None and sec - edge < length
                    elif mode != 1:
                        raise AssertionError(mode)
                    self.timers[i] = on, edge
                elif kind == "reliable":
                    get(513)
                    values[i] = True
                elif kind == "select":
                    values[i] = get(7001 if get(961) else 7000)
                else:
                    ports = (
                        (50083, 50084)
                        if kind in ("ge", "gt", "eq")
                        else sorted(p for p in default if p >= 7000)
                    )
                    values[i] = reduce(ops[kind], (get(p) for p in ports))
            new = {i: values[src] for i, src in pending.items()}
            if new == self.memory:
                return values[mean], values[ready], values[output]
            self.memory = new
        raise AssertionError("The native feedback did not settle within a single elapsed second.")


def test_elapsed_registers_cover_varying_flow_repeated_executions_and_faults():
    peer = PhasePeer()
    random = Random(27)
    samples = deque(maxlen=30)
    prev = 0
    for t in range(125):
        flow = random.randrange(46, 166)
        samples.append(flow)
        mean, ready, valve = peer.run(t, flow)
        assert peer.run(t, flow) == (mean, ready, valve)
        assert ready == (t >= 30)
        assert valve == (min(prev + 5, 100) if ready else 0)
        if ready:
            assert mean == pytest.approx(sum(samples) / 30)
        prev = valve
    assert peer.run(125, 70, healthy=False) == (0, False, 0)
    for t in range(126, 156):
        assert peer.run(t, 70)[1:] == (False, 0)
    assert peer.run(156, 70) == (70, True, 5)
    assert peer.run(159, 70) == (0, False, 0)
    for t in range(160, 189):
        assert peer.run(t, 70)[2] == 0
    assert peer.run(189, 70) == (70, True, 5)
    for t in range(190, 195):
        last = peer.run(t, 70, phase=(60 - 189 % 60) % 60)
    assert last == (0, False, 0)


@pytest.mark.parametrize(
    "legacy,model",
    [
        (False, "FX-PCV1630-0"),
        (True, "FX-PCV1630-0"),
        (True, "MS-VMA1630-0"),
    ],
)
def test_compact_window_tracks_each_second_and_restarts_after_discontinuity(legacy, model):
    peer = PhasePeer(compact=True, legacy=legacy, model=model)
    samples = deque(maxlen=30)
    random = Random(320)
    for t in range(125):
        value = random.randrange(48, 146)
        samples.append(value)
        mean, ready, valve = peer.run(t, value)
        assert peer.run(t, value) == (mean, ready, valve)
        assert ready == (t >= 31)
        if ready:
            assert mean == pytest.approx(sum(samples) / 30)
            assert 0 < valve <= 100
        else:
            assert (mean, valve) == (0, 0)
    # Missing one second, an entire odd/even pair, and stopping the clock
    # all withdraw heat. Repeated evaluations cannot fill the window.
    assert peer.run(126, 100) == (0, False, 0)
    for t in range(127, 157):
        assert peer.run(t, 100) == (0, False, 0)
    assert peer.run(157, 100) == (100, True, 5)
    assert peer.run(160, 100) == (0, False, 0)
    for t in range(161, 191):
        assert peer.run(t, 100)[2] == 0
    assert peer.run(191, 100) == (100, True, 5)
    assert peer.run(192, 100, healthy=False) == (0, False, 0)
    for t in range(193, 223):
        assert peer.run(t, 70) == (0, False, 0)
    assert peer.run(223, 70) == (70, True, 5)
    for t in range(224, 230):
        stalled = peer.run(t, 70, phase=(60 - 223 % 60) % 60)
    assert stalled == (0, False, 0)


@pytest.mark.parametrize("legacy", [False, True])
def test_compact_window_rejects_a_gap_aliasing_either_sampling_clock(legacy):
    peer = PhasePeer(compact=True, legacy=legacy)
    for sec in range(60):
        peer.run(sec, 80)
    assert peer.run(60, 80)[1]
    sec = 60
    for since_last in (61, 121, 3599, 3601, 3602, 7203):
        sec += since_last
        assert peer.run(sec, 80) == (0, False, 0)
        for _ in range(30):
            sec += 1
            assert peer.run(sec, 80)[2] == 0
        sec += 1
        assert peer.run(sec, 80) == (80, True, 5)


@pytest.mark.parametrize("model", ["FX-PCV1630-0", "MS-VMA1630-0"])
def test_edge_sampling_keeps_one_measurement_across_independent_input_events(model):
    peer = PhasePeer(legacy=True, edge=True, model=model)
    samples = deque(maxlen=30)
    for second in range(100):
        value = 40 + (7 * second) % 83
        phase = (60 - second % 60) % 60
        previous = (phase + 1) % 60
        if second:
            peer.run(second, 173, phase=previous)
        mean, ready, valve = peer.run(second + 0.125, value, phase=phase)
        # A change of the flow input alone must not overwrite this second's sample.
        assert peer.run(second + 0.375, 173, phase=phase) == (mean, ready, valve)
        samples.append(value)
        assert ready == (second >= 31)
        assert mean == pytest.approx(sum(samples) / 30 if ready else 0)
        assert (valve > 0) == ready


def test_edge_sampling_withdraws_heat_on_gaps_stalls_and_bad_measurements():
    peer = PhasePeer(legacy=True, edge=True)
    sec = 60
    for tick in range(sec + 1):
        peer.run(tick, 80)
    for gap in (2, 3, 59, 60, 61, 121, 3599, 3601, 3602, 7203, 86401):
        sec += gap
        assert peer.run(sec, 80) == (0, False, 0)
        # Returning to exactly the same countdown value produces no clock
        # edge. The first new sample is on the following second.
        first_sample_delay = int(gap % 60 == 0)
        for _ in range(30 + first_sample_delay):
            sec += 1
            assert peer.run(sec, 80)[2] == 0
        sec += 1
        assert peer.run(sec, 80) == (80, True, 5)
    frozen = (60 - sec % 60) % 60
    peer.run(sec + 1, 80, phase=frozen)
    assert peer.run(sec + 2, 80, phase=frozen) == (0, False, 0)
    for tick in range(sec + 3, sec + 45):
        peer.run(tick, 80)
    assert peer.run(sec + 45, 80)[1]
    assert peer.run(sec + 45.25, 80, healthy=False) == (0, False, 0)
