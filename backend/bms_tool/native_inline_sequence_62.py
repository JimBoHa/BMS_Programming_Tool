"""Lower the one-second sampling graph to native 62/62 comparison and reduction blocks."""

from bacpypes3.primitivedata import Enumerated, ObjectIdentifier

from .moi_application import _list
from .native_inline_sequence import SPECS, CompactInlineSequenceCompiler, get_ref
from .native_inputs import encoded


class LegacyInlineSequenceCompiler(CompactInlineSequenceCompiler):
    separate_root_layout = True
    allow_floating = True

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
