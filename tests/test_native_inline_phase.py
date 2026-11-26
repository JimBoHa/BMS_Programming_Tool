"""Exercise elapsed-time registers decoded from the authored native fixture."""

from collections import deque
from operator import add, and_, ge, gt, or_, sub, xor
from random import Random

import pytest
from bms_tool.moi_identity import MoiIdentity
from bms_tool.native_inline_sequence import SPECS, InlineSequenceCompiler

from .test_native_inline_sequence import authored_source


class PhasePeer:
    def __init__(self):
        source = authored_source()
        compiler = InlineSequenceCompiler(
            source, authored_source(catalog=True)[3], 200, phase_sampling=True
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
        children = {}
        for ref, record in app.reader.records.items():
            parent = ref.rpartition(".")[0]
            children.setdefault(parent, {})[app.reader.scalar(record, 3365)] = app.reader.scalar(
                record, 3113
            )
        kinds = {spec[0]: name for name, spec in SPECS.items()}
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
            "Inline normalized second": (60 - sec % 60) % 60 if phase is None else phase,
            "Inline countdown is reliable": True,
            "Inline supply flow valid": healthy,
            "Inline valid flow or zero": flow if healthy else 0,
            "Inline lesser of room and cap": demand,
        }
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
                    return defaults[port] if source is None else observed[source]

                if kind == "prevF":
                    values[i] = self.memory.get(i, 0)
                    pending[i] = self.inputs[i, 513]
                elif kind == "timer":
                    on = bool(get(513))
                    mode = get(518)
                    length = get(1080)
                    prev, edge = self.timers.get(i, (False, None))
                    if on != prev:
                        edge = sec
                    if mode == 2:
                        values[i] = on and edge is not None and sec - edge >= length
                    elif mode == 4:
                        values[i] = on or edge is not None and sec - edge < length
                    else:
                        raise AssertionError(mode)
                    self.timers[i] = on, edge
                elif kind == "select":
                    values[i] = get(7001 if get(961) else 7000)
                else:
                    ports = (50083, 50084) if kind in ("ge", "gt") else (7000, 7001)
                    values[i] = ops[kind](*(get(p) for p in ports))
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
