"""Lower the one-second sampling graph to native 62/62 comparison and reduction blocks."""

from bacpypes3.primitivedata import Enumerated, ObjectIdentifier

from .moi_application import _list
from .native_inline_sequence import SPECS, CompactInlineSequenceCompiler, get_ref
from .native_inputs import encoded


class LegacyInlineSequenceCompiler(CompactInlineSequenceCompiler):
    separate_root_layout = True
    allow_floating = True

    def export(self, *, shadow, grouped=False):
        payload, details = super().export(shadow=shadow)
        if not grouped:
            return payload, details
        from .moi_identity import sha
        from .native_inline_activity_drawing import ActivityDrawing

        payload, hierarchy = ActivityDrawing(self.application, payload, details).encode()
        new_objects = hierarchy["added_objects"]
        return payload, {
            **details,
            "control_edges_coordinate_system": "flat draft before Activity grouping",
            "activity_layout": hierarchy,
            "added_objects": [*details["added_objects"], *new_objects],
            "added_records": details["added_records"] + len(new_objects),
            "root_members": hierarchy["root_members"],
            "candidate_sha256": sha(payload),
        }

    def __init__(self, files, donor, first):
        super().__init__(files, donor, first)
        self.reductions = {"add": {}, "or": {}}
        for doc, children in ((self.application, self.children), (self.other, self.others)):
            read = doc.reader.scalar
            for record in doc.records:
                cid = record["class_id"]
                if cid not in (559, 561) or set(record["properties"]) != {
                    75,
                    518,
                    3184,
                    3670,
                    32527,
                }:
                    continue
                # Only borrow an existing input layout from an associative operation
                # in this same native class. The generated operation is specified below.
                kind = "or" if cid == 559 else "add"
                allowed = ("and", "or", "xor") if cid == 559 else ("add", "mul", "max", "min")
                if (read(record, 3670), read(record, 518)) not in {
                    (SPECS[k][0], SPECS[k][2]) for k in allowed
                }:
                    continue
                pins = [int(p) for p in _list(record["properties"][3184]["tags"], Enumerated)]
                width = len(pins) - 1
                if not 3 <= width <= 30 or set(pins) != {85, *range(7000, 7000 + width)}:
                    continue
                kids = children[get_ref(doc, record)]
                ports = {read(k, 3365): k for k in kids}
                inc, outc, typ = (530, 531, 5) if cid == 559 else (526, 527, 2)
                if (
                    len(kids) != len(pins)
                    or set(ports) != set(pins)
                    or any(
                        k["class_id"] != (outc if port == 85 else inc)
                        or ObjectIdentifier(read(k, 75))[0] != typ
                        or set(k["properties"]) - {75, 32527, 3365, 3113, 3670, 74, 931, 117, 661}
                        for port, k in ports.items()
                    )
                ):
                    continue
                self.reductions[kind].setdefault(width, (doc, record, ports))

    def phase_sectors(self, phase):
        high = self.arithmetic("ge", "Inline upper half minute", phase, 30.0)
        slot = self.select(
            "Inline second of half minute",
            high,
            self.arithmetic("sub", "Inline folded clock", phase, 30.0),
            phase,
        )
        # Release 62 Comparison Setup 5 / Standard Component 30 is Equal (Float).
        # An explicit zero differential compares the integer countdown exactly.
        return [
            self.block(
                "ge",
                f"Inline second {i:02d}",
                (50083, slot),
                defaults={50084: float(i), 637: 0.0},
                fields={3670: encoded(Enumerated(30)), 518: encoded(Enumerated(5))},
            )
            for i in range(30)
        ]

    def combine(self, nodes, kind, label):
        available = self.reductions.get(kind)
        if not available:
            return super().combine(nodes, kind, label)
        widths = sorted(available, reverse=True)
        level = 0
        while len(nodes) > 1:
            level += 1
            reduced = []
            offset = 0
            while offset < len(nodes):
                remaining = len(nodes) - offset
                width = next((w for w in widths if w <= remaining), min(2, remaining))
                chunk = nodes[offset : offset + width]
                name = f"{label} {level}-{len(reduced) + 1}"
                if width == 1:
                    value = chunk[0]
                elif width == 2:
                    value = self.arithmetic(kind, name, *chunk)
                else:
                    fn, _, setup, _ = SPECS[kind]
                    value = self.block(
                        kind,
                        name,
                        *enumerate(chunk, start=7000),
                        prototype=available[width],
                        fields={3670: encoded(Enumerated(fn)), 518: encoded(Enumerated(setup))},
                    )
                reduced.append(value)
                offset += width
            nodes = reduced
        return nodes[0]


class EdgeTimedInlineSequenceCompiler(LegacyInlineSequenceCompiler):
    """Sample on changes of a single native countdown and supervise its actual age."""

    def phase_window(self, phase, clock_ok, data_ok, flow):
        q = self.arithmetic
        previous = (self.nodes["Inline previous clock second"], 85)
        changed = q(
            "or",
            "Inline countdown changed",
            q("gt", "Inline countdown decreased", previous, phase),
            q("gt", "Inline countdown increased", phase, previous),
        )
        previous_health = self.block("prevB", "Inline previous clock health", (513, clock_ok))
        starting = self.block(
            "xor", "Inline first reliable clock", (7000, previous_health), defaults={7001: True}
        )
        update = q("or", "Inline sample clock event", changed, starting)
        sample = self.held("Inline airflow at clock edge", update, flow)
        sectors = self.phase_sectors(phase)
        values = [
            self.held(f"Inline airflow second {index:02d}", active, sample)
            for index, active in enumerate(sectors)
        ]
        even = self.combine(sectors[::2], "or", "Inline even clock sector")
        odd = self.block("xor", "Inline odd clock sector", (7000, even), defaults={7001: True})
        previous_even = self.held("Inline previous even second", even, phase)
        previous_odd = self.held("Inline previous odd second", odd, phase)
        prior = self.select("Inline preceding clock sector", even, previous_odd, previous_even)
        difference = q("sub", "Inline countdown difference", prior, phase)
        elapsed = self.select(
            "Inline elapsed clock seconds",
            q("ge", "Inline countdown stayed in minute", difference, 0),
            difference,
            q("add", "Inline countdown crossed minute", difference, 60),
        )
        consecutive = q(
            "and",
            "Inline one clock second",
            q("ge", "Inline clock advanced", elapsed, 1),
            q("ge", "Inline clock step bounded", 1, elapsed),
        )

        # A falling edge never extends a retriggerable pulse. After a long gap
        # at most one parity can restart; its opposite must already be alive.
        pulses = [
            self.block(
                "timer",
                name,
                (513, q("and", name + " rising edge", gate, update)),
                defaults={518: 1, 1080: 5.0},
                clock=True,
            )
            for name, gate in (
                ("Inline even freshness timer", even),
                ("Inline odd freshness timer", odd),
            )
        ]
        ages = [(index, 1081) for index, _ in pulses]
        qualities = [
            self.block("reliable", name, (513, age))
            for name, age in zip(
                ("Inline even timer reliable", "Inline odd timer reliable"), ages, strict=True
            )
        ]
        fresh = q(
            "and",
            "Inline recent clock edge",
            q("and", "Inline alternate edges present", *pulses),
            q(
                "ge",
                "Inline recent rising edge",
                q("max", "Inline newest pulse remaining", *ages),
                4,
            ),
        )
        timing_ok = q(
            "and",
            "Inline continuous time",
            q(
                "and",
                "Inline clock and edges reliable",
                clock_ok,
                q("and", "Inline pulse clocks reliable", *qualities),
            ),
            q("and", "Inline witnessed clock step", consecutive, fresh),
        )
        warm = self.block(
            "timer",
            "Inline complete timed history",
            (513, q("and", "Inline uninterrupted observation", timing_ok, data_ok)),
            defaults={518: 2, 1080: 30.0},
        )
        count = self.select("Inline confirmed samples in complete window", warm, 30.0)
        total = self.combine(values, "add", "Inline measured CFM sum")
        mean = self.select(
            "Inline complete 30-second mean",
            warm,
            q("div", "Inline airflow 30-second mean", total, 30.0),
        )
        return even, odd, count, warm, mean
