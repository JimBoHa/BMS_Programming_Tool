"""Build the elapsed-time airflow permissive and proportional discharge limit from native primitives."""

from collections import defaultdict

from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    Enumerated,
    ObjectIdentifier,
    Real,
    Unsigned,
)

from .moi_application import _list
from .moi_identity import MoiIdentity, sha
from .moi_parameters import ParameterApplication
from .native_inline_monitor import MODELS, floating_valve_configuration, sources
from .native_inputs import archive, encoded, raw_property, record_instance, replace_properties
from .native_root_layout import assemble_root, verify_layout


def _wire(*fields):
    return b"\x3e" + b"".join(encoded(Unsigned(v)) for v in fields) + b"\x3f"


# Standard Component Name, class, setup and complete typed port inventory.
BO = {7000: 530, 7001: 530, 85: 531}
NUM = {7000: 526, 7001: 526, 85: 527}
CMP = {50083: 526, 50084: 526, 637: 526, 85: 531}
SPECS = {
    "prevF": (79, 538, None, {513: 526, 85: 527}),
    "prevB": (81, 538, None, {513: 530, 85: 531}),
    "reliable": (21, 539, None, {513: 526, 85: 531}),
    "and": (24, 559, 1, BO),
    "or": (25, 559, 2, BO),
    "xor": (26, 559, 3, BO),
    "ge": (32, 560, 3, CMP),
    "gt": (28, 560, 1, CMP),
    "add": (41, 561, 14, NUM),
    "sub": (43, 561, 13, NUM),
    "mul": (40, 561, 15, NUM),
    "div": (42, 561, 12, NUM),
    "max": (58, 561, 17, NUM),
    "min": (59, 561, 18, NUM),
    "select": (14, 562, None, {961: 530, 7000: 526, 7001: 526, 85: 527}),
    "timer": (
        62,
        558,
        None,
        {85: 531, 513: 530, 1082: 530, 518: 528, 1080: 526, 1083: 528, 1081: 527},
    ),
}


def required(b, message):
    if not b:
        raise ValueError(message)


def parts(binary):
    m = MoiIdentity(binary)
    rd = m.reader
    children = defaultdict(list)
    for r in m.records:
        ref = rd.scalar(r, 32527) or ""
        children[ref.rpartition(".")[0]].append(r)
    return m, children


def get_ref(m, r):
    return m.reader.scalar(r, 32527)


def one(sequence, message):
    values = list(sequence)
    required(len(values) == 1, message)
    return values[0]


class InlineSequenceCompiler:
    separate_root_layout = False  # Historic receipt images retain their exact encoding.
    allow_floating = False

    def __init__(self, files, donor, first, *, phase_sampling=False):
        self.phase_sampling = phase_sampling
        self.first_instance = first
        self.original = files
        effective, self.merge = ParameterApplication(files[3], files[11], files[12]).compile()
        self.application, self.children = parts(effective)
        self.reader = self.application.reader
        self.read = self.reader.scalar
        self.other, self.others = parts(donor)
        required(
            not self.reader.errors and not self.other.reader.errors,
            "Incomplete native source graph",
        )
        required(
            self.application.summary()["format_versions"]
            == self.other.summary()["format_versions"],
            "Timer donor uses a different native format",
        )
        required(
            self.application.summary()["format_versions"] in ({"acs": 62, "dmcs": 62},),
            "Unqualified application format",
        )
        required(
            self.application.summary()["model"] in MODELS
            and self.application.summary()["model"] == self.other.summary()["model"],
            "The primitive source must match the target controller model.",
        )
        self.root = one(
            (r for r in self.application.records if r["class_id"] == 575), "Ambiguous root"
        )
        self.rootref = get_ref(self.application, self.root)
        self.g = self.application.reader.diagram(self.rootref, retained_activity_refs=True)
        self.physical = sources(self.application, self.g, allow_floating=self.allow_floating)
        valve = self.physical["valve"]
        self.floating_valve = (
            floating_valve_configuration(self.application, valve)
            if valve["class_id"] == 251
            else None
        )
        self.old = self.g["blocks"]
        self.order = list(self.g["execution_order"])
        refs = {b["ref"]: b["index"] for b in self.old}
        self.wires = [
            (refs[x["source_ref"]], x["source_port"], refs[x["target_ref"]], x["target_port"])
            for x in self.g["connections"]
        ]
        required(
            not ({3162, 3461, 3383, 3384} & self.root["properties"].keys()),
            "Unsupported original root table",
        )
        self.taken = {record_instance(self.application, r) for r in self.application.records}
        self.taken.update(
            ObjectIdentifier(self.read(r, 75))[1]
            for r in self.application.records
            if self.read(r, 75)
        )
        required(
            type(first) is int and 1 <= first <= 4194302, "Select a valid first object instance."
        )
        self.ptr = first
        self.added = []
        self.ids = []
        self.nodes = {}
        self.specs = {}
        self.stages = {"early": [], "late": []}
        self.stage = "early"
        self.source_wires = list(self.wires)
        self.exposures = {}
        self.allocations = []
        self.all_tags = set()
        for name in SPECS:
            self.specs[name] = self.prototype(name)

    def prototype(self, name):
        fn, cls, setup, expected = SPECS[name]
        choices = [(self.application, self.children), (self.other, self.others)]
        for doc, children in choices:
            read = doc.reader.scalar
            for r in doc.records:
                if (r["class_id"], read(r, 3670), read(r, 518)) != (cls, fn, setup):
                    continue
                if set(r["properties"]) - (
                    {75, 32527, 3670, 3184, 518} | ({2381, 3122} if name == "select" else set())
                ):
                    continue
                if name == "select" and (
                    read(r, 3122) != 1
                    or [int(x) for x in _list(r["properties"][2381]["tags"], Unsigned)] != [0, 2]
                ):
                    continue
                kids = children[get_ref(doc, r)]
                kmap = {read(k, 3365): k for k in kids}
                if (
                    len(kmap) != len(kids)
                    or {i: k["class_id"] for i, k in kmap.items()} != expected
                ):
                    continue
                if any(
                    set(k["properties"]) - {75, 32527, 3365, 3113, 3670, 74, 931, 117, 661}
                    for k in kids
                ):
                    continue
                if name == "timer" and (
                    read(kmap[518], 931) != 21
                    or read(kmap[1083], 931) != 22
                    or read(kmap[1080], 117) != 73
                ):
                    continue
                return doc, r, kmap
        raise ValueError("No released typed source for " + name)

    def alloc(self):
        while self.ptr in self.taken:
            self.ptr += 1
        required(self.ptr <= 4194302, "Identifier space exhausted")
        n = self.ptr
        self.ptr += 1
        self.taken.add(n)
        return n

    def clone(self, doc, r, num, obj_type, ref, props):
        changes = {
            75: encoded(ObjectIdentifier((obj_type, num))),
            32527: encoded(CharacterString(ref)),
            **props,
        }
        data = bytearray(replace_properties(doc, r, changes))
        data[6:10] = ((r["class_id"] << 22) | num).to_bytes(4, "big")
        self.added.append(bytes(data))
        self.allocations.append(str(ObjectIdentifier((obj_type, num))))

    def reg(self, label, cid, number):
        required(label not in self.all_tags, "Duplicate label")
        self.all_tags.add(label)
        index = len(self.old) + len(self.ids)
        self.ids.append(ObjectIdentifier((cid, number)))
        self.stages[self.stage].append(index)
        self.nodes[label] = index
        return index

    def block(self, kind, label, *inputs, defaults=None, clock=False, prototype=None, fields=None):
        doc, parent, children = prototype or self.specs[kind]
        num = self.alloc()
        cls = parent["class_id"]
        ref = f"{self.rootref}.{cls}_{num}"
        index = self.reg(label, cls, num)
        inputmap = {port: sig for port, sig in inputs}
        vals = defaults or {}
        required((inputmap.keys() | vals.keys()) <= children.keys(), "Unknown input port")
        exposed = [int(v) for v in _list(parent["properties"][3184]["tags"], Enumerated)]
        required(85 in exposed and inputmap.keys() <= set(exposed), "Connection to a hidden port")
        meta = {2390: encoded(CharacterString(label)), **(fields or {})}
        if clock:
            required(
                kind == "timer" and vals.get(518) == 5 and vals.get(1080) in (60, 3601),
                "Unsupported sampling clock",
            )
            meta[1184] = encoded(Unsigned(1))
            meta[3184] = b"".join(encoded(Enumerated(i)) for i in dict.fromkeys([*exposed, 1081]))
        self.clone(doc, parent, num, cls, ref, meta)
        for port, child in children.items():
            typ = int(ObjectIdentifier(doc.reader.scalar(child, 75))[0])
            n = self.alloc()
            if typ == 19:
                val = Enumerated(vals.get(port, 0))
                required(kind == "timer", "Unknown enumeration")
            elif typ == 5:
                val = Boolean(vals.get(port, False))
            elif typ == 2:
                val = Real(vals.get(port, 0.0))
            else:
                raise ValueError("Unknown child type")
            self.clone(doc, child, n, typ, f"{ref}.{typ}_{n}", {3113: encoded(val)})
        for port, sig in inputmap.items():
            self.wire(sig, index, port)
        return (index, 85)

    def wire(self, source, idx, port):
        required(
            not any((e[2], e[3]) == (idx, port) for e in self.wires),
            "A native input already has a writer",
        )
        self.wires.append((*source, idx, port))

    def param(self, label, unit, default):
        candidate = one(
            (
                r
                for r in self.application.records
                if r["class_id"] == 526
                and self.read(r, 2390) == "ZNT-SP"
                and self.read(r, 3807) is True
                and (self.read(r, 32527) or "").rpartition(".")[0] == self.rootref
            ),
            "A known exposed adjustment prototype is required",
        )
        required(
            set(candidate["properties"]) == {75, 117, 2390, 2567, 3113, 32527, 3365, 3670, 3807}
            and self.read(candidate, 2567) is True,
            "Unexpected network input configuration",
        )
        used = {self.read(r, 3365) for r in self.children[self.rootref]} | {
            e["root_port"] for e in self.exposures.values()
        }
        port = next(n for n in range(7000, 8000) if n not in used)
        num = self.alloc()
        idx = self.reg(label, 2, num)
        ref = f"{self.rootref}.2_{num}"
        self.clone(
            self.application,
            candidate,
            num,
            2,
            ref,
            {
                2390: encoded(CharacterString(label)),
                117: encoded(Enumerated(unit)),
                3113: encoded(Real(default)),
                3365: encoded(Enumerated(port)),
                3670: encoded(Enumerated(3)),
                3807: encoded(Boolean(True)),
            },
        )
        self.exposures[label] = {
            "object": str(ObjectIdentifier((2, num))),
            "ref": ref,
            "root_port": port,
            "units": unit,
            "default": default,
        }
        return idx, 663

    def arithmetic(self, kind, label, left, right):
        a, b = (50083, 50084) if kind in ("ge", "gt") else (7000, 7001)
        wires = []
        defaults = {}
        for port, v in ((a, left), (b, right)):
            if isinstance(v, tuple):
                wires.append((port, v))
            else:
                defaults[port] = v
        return self.block(kind, label, *wires, defaults=defaults)

    def select(self, label, test, on, off=0):
        wires = [(961, test)]
        ds = {}
        for port, v in ((7001, on), (7000, off)):
            if isinstance(v, tuple):
                wires.append((port, v))
            else:
                ds[port] = v
        return self.block("select", label, *wires, defaults=ds)

    def member(self, cls, *, name=None, fn=None):
        return one(
            (
                b
                for b in self.old
                if b["class_id"] == cls
                and (name is None or self.read(self.reader.records[b["ref"]], 2390) == name)
                and (fn is None or self.read(self.reader.records[b["ref"]], 3670) == fn)
            ),
            f"Unproven existing block: {cls}/{name}/{fn}",
        )

    def hardware_reader(self, label, source_record, property_id, boolean=False, default=0.0):
        """Instantiate the release's generic read-only Sensor, with a local attribute reference."""
        pressure = self.member(556, name="DA-VP")
        pattern = self.reader.records[pressure["ref"]]
        required(
            set(self.read(s, 3365) for s in self.children[pressure["ref"]]) == {8000, 86},
            "The released sensor output and priority ports are required",
        )
        allowed = {240: {81, 85, 1433}, 527: {3368}}
        required(
            property_id in allowed.get(source_record["class_id"], set())
            and boolean == (property_id in {81, 3368}),
            "Unexpected local attribute or type",
        )
        original_ref = get_ref(self.application, source_record)
        required(
            original_ref.startswith(self.rootref.split("/")[0] + "/") and ".." not in original_ref,
            "The measured object must belong to the current application",
        )
        parent_num = self.alloc()
        ref = f"{self.rootref}.556_{parent_num}"
        result = self.reg(label, 556, parent_num)
        # Generic Sensor (Boolean/Float) manufacturer definitions have no hardware allocation
        # or equipment-module GUID. They have one source reference and one typed result.
        props = {
            32527: encoded(CharacterString(ref)),
            75: encoded(ObjectIdentifier((556, parent_num))),
            2390: encoded(CharacterString(label)),
            3114: encoded(Boolean(False)),
            3184: raw_property(self.application, pattern, 3184)[:-1],
            3399: b"\x3e"
            + encoded(CharacterString(original_ref))
            + b"\x4e\x4f"
            + encoded(Enumerated(property_id))
            + b"\x3f",
            3579: encoded(Unsigned(1 if boolean else 0)),
            3670: encoded(Enumerated(91 if boolean else 89)),
        }
        header = bytearray(self.application.data[pattern["offset"] : pattern["offset"] + 12])
        required(
            header[4:6] == bytes.fromhex("0e1c") and header[10:12] == bytes.fromhex("0f1e"),
            "Unsupported sensor record framing",
        )
        header[6:10] = ((556 << 22) | parent_num).to_bytes(4, "big")
        for pid, data in props.items():
            width = max(1, (pid.bit_length() + 7) // 8)
            header.extend(
                bytes([8 | width]) + pid.to_bytes(width, "big") + b"\x2e" + data + b"\x2f"
            )
        self.added.append(bytes(header) + b"\x1f")
        self.allocations.append(str(ObjectIdentifier((556, parent_num))))
        base = {self.read(c, 3365): c for c in self.children[pressure["ref"]]}
        if boolean:
            child_doc, _, typed = self.specs["and"]
            output_proto = typed[85]
            output_type = 5
            child_params = {3365: encoded(Enumerated(8000)), 3113: encoded(Boolean(default))}
        else:
            child_doc = self.application
            output_proto = base[8000]
            output_type = 2
            child_params = {
                3365: encoded(Enumerated(8000)),
                3113: encoded(Real(default)),
                117: encoded(Enumerated(self.read(source_record, 117))),
                3930: encoded(Boolean(False)),
                22: encoded(Real(0.0)),
            }
        number = self.alloc()
        self.clone(
            child_doc,
            output_proto,
            number,
            output_type,
            f"{ref}.{output_type}_{number}",
            child_params,
        )
        number = self.alloc()
        self.clone(self.application, base[86], number, 2, f"{ref}.2_{number}", {})
        return result, 8000

    def clear_service_flag(self, label, signal):
        doc, parent, _ = self.specs["reliable"]
        bd, _, children = self.specs["prevB"]
        required(
            parent["class_id"] == 539
            and set(children) == {513, 85}
            and (children[513]["class_id"], children[85]["class_id"]) == (530, 531),
            "The release boolean quality checker lacks its typed ports",
        )
        number = self.alloc()
        ref = f"{self.rootref}.539_{number}"
        name = label + " service signal reliable"
        checker = self.reg(name, 539, number)
        self.clone(
            doc,
            parent,
            number,
            539,
            ref,
            {3670: encoded(Enumerated(23)), 2390: encoded(CharacterString(name))},
        )
        for port in (513, 85):
            number = self.alloc()
            self.clone(
                bd, children[port], number, 5, f"{ref}.5_{number}", {3113: encoded(Boolean(False))}
            )
        self.wire(signal, checker, 513)
        marker = self.select(label + " flag read", signal, 0.0, 1.0)
        guarded = self.select(label + " reliable flag or zero", (checker, 85), marker, 0.0)
        return self.arithmetic("gt", label + " in service", guarded, 0.5)

    def independent_flow(self, flow, pressure, hardware_reading):
        """Create a private calculation with the original box's calibration and hardware source."""
        source = self.reader.records[flow["ref"]]
        ports = {self.read(child, 3365): child for child in self.children[flow["ref"]]}
        expected = {
            2383: 526,
            3504: 526,
            3654: 530,
            960: 526,
            968: 526,
            50215: 526,
            3505: 527,
            3655: 527,
        }
        required(
            {p: c["class_id"] for p, c in ports.items()} == expected,
            "Unrecognized differential pressure flow calculation",
        )
        required(
            self.read(source, 117) == 58
            and self.read(ports[3505], 117) == 84
            and self.read(source, 63464) == 0
            and self.read(source, 3656) > 0,
            "Pressure and CFM units or calibration could not be qualified",
        )
        required(
            set(source["properties"]) <= {75, 117, 661, 2390, 3184, 3656, 3670, 63464, 3506, 32527},
            "Additional flow configuration requires independent qualification",
        )
        upstream = {
            dst_port: (src, pin)
            for src, pin, dst, dst_port in self.source_wires
            if dst == flow["index"]
        }
        required(
            set(upstream) == {3504, 3654, 960, 968} and upstream[3504] == (pressure["index"], 8000),
            "Pressure, autozero, area or pickup gain wiring is ambiguous",
        )
        num = self.alloc()
        ref = f"{self.rootref}.570_{num}"
        label = "Inline independent pickup calculation"
        idx = self.reg(label, 570, num)
        self.clone(self.application, source, num, 570, ref, {2390: encoded(CharacterString(label))})
        for port, child in ports.items():
            obj_type = int(ObjectIdentifier(self.read(child, 75))[0])
            child_num = self.alloc()
            fields = {}
            if port == 3505:
                fields = {
                    2390: encoded(CharacterString("Inline private pickup flow")),
                    3807: encoded(Boolean(False)),
                    3930: encoded(Boolean(False)),
                }
                required(
                    self.read(child, 3807) is True and self.read(child, 2390) == "SA-F",
                    "Original calculated airflow output could not be identified",
                )
            else:
                required(self.read(child, 3807) is not True, "Unexpected exposed calculation port")
            self.clone(
                self.application,
                child,
                child_num,
                obj_type,
                f"{ref}.{obj_type}_{child_num}",
                fields,
            )
        for port, origin in upstream.items():
            self.wire(hardware_reading if port == 3504 else origin, idx, port)
        return idx, 3505

    def phase_sectors(self, phase):
        q = self.arithmetic
        upper = q("ge", "Inline upper half minute", phase, 30.0)
        slot = self.select(
            "Inline second of half minute",
            upper,
            q("sub", "Inline folded clock", phase, 30.0),
            phase,
        )
        gates = [q("ge", f"Inline second at least {i:02d}", slot, float(i)) for i in range(1, 30)]
        phases = [self.block("xor", "Inline second 00", (7000, gates[0]), defaults={7001: True})]
        phases.extend(
            q("xor", f"Inline second {i:02d}", gates[i - 1], gates[i]) for i in range(1, 29)
        )
        phases.append(gates[-1])

        return phases

    def combine(self, nodes, kind, label):
        depth = 0
        while len(nodes) > 1:
            depth += 1
            nodes = [
                self.arithmetic(kind, f"{label} {depth}-{i // 2 + 1}", nodes[i], nodes[i + 1])
                if i + 1 < len(nodes)
                else nodes[i]
                for i in range(0, len(nodes), 2)
            ]
        return nodes[0]

    def phase_window(self, phase, clock_ok, data_ok, flow):
        """Use sustained clock levels to address 30 independent one-second samples."""
        q = self.arithmetic
        phases = self.phase_sectors(phase)
        # A held level survives the immediate re-execution of native Last Value.
        # The other 29 registers cannot change while this clock sector is active.
        values, counts = [], []
        for i, active in enumerate(phases):
            memory = self.block("prevF", f"Inline stored airflow {i:02d}")
            value = self.select(f"Inline captured airflow {i:02d}", active, flow, memory)
            self.wire(value, memory[0], 513)
            values.append(value)
            alive = self.block(
                "timer",
                f"Inline recent second {i:02d}",
                (513, q("and", f"Inline valid sample {i:02d}", active, data_ok)),
                defaults={518: 4, 1080: 29.0},
            )
            counts.append(self.select(f"Inline measured second {i:02d}", alive, 1.0))
        count = self.combine(counts, "add", "Inline observed seconds")
        total = self.combine(values, "add", "Inline measured CFM sum")
        even = self.combine(phases[::2], "or", "Inline even clock sector")
        odd = self.block("xor", "Inline odd clock sector", (7000, even), defaults={7001: True})
        even_recent = self.block(
            "timer", "Inline even clock active", (513, even), defaults={518: 4, 1080: 2.0}
        )
        odd_recent = self.block(
            "timer", "Inline odd clock active", (513, odd), defaults={518: 4, 1080: 2.0}
        )
        ticking = q("and", "Inline alternating seconds proven", even_recent, odd_recent)
        valid = q("and", "Inline valid sensors and timer", data_ok, clock_ok)
        warm = self.block(
            "timer", "Inline full window elapsed", (513, valid), defaults={518: 2, 1080: 30.0}
        )
        complete = q(
            "and",
            "Inline full measured window",
            q("ge", "Inline 30 recent elapsed seconds", count, 30.0),
            q("and", "Inline healthy sampling", ticking, valid),
        )
        ready = q(
            "and",
            "Inline complete timed history",
            warm,
            self.block(
                "timer",
                "Inline last measured second elapsed",
                (513, complete),
                defaults={518: 2, 1080: 1.0},
            ),
        )
        mean = self.select(
            "Inline complete 30-second mean",
            complete,
            q("div", "Inline airflow 30-second mean", total, 30.0),
        )
        return even, odd, count, ready, mean

    def phase_ramp(self, even, odd, permit, target):
        """Each half of a two-phase register can advance once in its elapsed second."""
        q = self.arithmetic
        a = self.block("prevF", "Inline even valve memory")
        b = self.block("prevF", "Inline odd valve memory")

        def bank(label, active, own, other):
            upper = q("add", label + " five point allowance", other, 5.0)
            advanced = q("min", label + " bounded opening", target, upper)
            retained = self.select(label + " elapsed second", active, advanced, own)
            value = self.select(
                label + " clear on inhibit",
                permit,
                q("min", label + " immediate cutback", retained, target),
            )
            self.wire(value, own[0], 513)
            return value

        even_value = bank("Inline even valve", even, a, b)
        odd_value = bank("Inline odd valve", odd, b, a)
        return self.select("Inline protected valve command", even, even_value, odd_value)

    def body(self):

        q = self.arithmetic
        flow = self.member(570, fn=681)
        pressure = self.member(556, name="DA-VP")
        dat = self.member(556, name="DA-T")
        valve = self.member(555, name="HTG-O")
        enable = self.member(530, name="HTG-EN")
        passthrough = self.member(592, fn=711)
        required(
            all(
                self.read(r, 2390) not in ("VLV-LOCKOUT-CFM", "MAX-DA-T")
                for r in self.application.records
            ),
            "Tuning point already present",
        )

        def obj(block, cid):
            return one(
                (
                    r
                    for r in self.application.records
                    if r["class_id"] in cid
                    and record_instance(self.application, r)
                    == record_instance(self.application, self.reader.records[block["ref"]])
                ),
                "Ambiguous physical point",
            )

        val = obj(valve, (241, 251))
        if self.floating_valve is not None:
            required(
                val["offset"] == self.physical["valve"]["offset"],
                "The inline heat sink must reference the verified external floating valve.",
            )
        dp = obj(pressure, (240,))
        probe = obj(dat, (240,))
        required(
            self.read(val, 117) == 98 and self.read(dp, 117) == 58 and self.read(probe, 117) == 64,
            "Physical units mismatch",
        )
        required(
            self.read(dp, 31) == "AI1-Int" and self.read(probe, 31).startswith(("UI", "IN")),
            "Unexpected sensor assignment",
        )
        raw_cfm = one(
            (
                r
                for r in self.children[flow["ref"]]
                if self.read(r, 3365) == 3505 and r["class_id"] == 527
            ),
            "Unknown airflow calculation output",
        )
        required(
            self.read(raw_cfm, 117) == 84 and self.read(raw_cfm, 2390) == "SA-F",
            "Airflow output must be measured CFM",
        )
        physical = [r for r in self.application.records if r["class_id"] in (239, 241, 251)]
        required(
            len(physical) == 2 and {self.read(r, 2390) for r in physical} == {"HTG-O", "DPR-O"},
            "Only inline units with one valve and a damper qualify",
        )
        old_enable = (enable["index"], 663, passthrough["index"], 513)
        original = one(
            (e for e in self.wires if e[2] == valve["index"] and e[3] == 7000),
            "Ambiguous heating command",
        )
        demand = original[:2]
        required(
            old_enable in self.wires
            and self.old[demand[0]]["class_id"] == 536
            and self.read(self.reader.records[self.old[demand[0]]["ref"]], 3670) == 6653,
            "Existing valve or enable wiring differs",
        )
        required(
            (pressure["index"], 8000, flow["index"], 3504) in self.wires, "Wrong airflow transducer"
        )
        early = self.order.index(passthrough["index"])
        late = self.order.index(valve["index"])
        required(
            max(self.order.index(b["index"]) for b in (flow, pressure, dat, enable))
            < early
            < self.order.index(demand[0])
            < late,
            "Required execution order is absent",
        )
        lock = self.param("VLV-LOCKOUT-CFM", 84, 30)
        high = self.param("MAX-DA-T", 64, 125)
        flow_sig = (flow["index"], 3505)
        dp_sig = (pressure["index"], 8000)
        dat_sig = (dat["index"], 8000)
        rawok = self.block("reliable", "Inline pressure reliable", (513, dp_sig))
        flowok = self.block("reliable", "Inline flow reliable", (513, flow_sig))
        dp_hardware = self.hardware_reader("Inline hardware pickup pressure", dp, 1433)
        dt_hardware = self.hardware_reader(
            "Inline physical discharge temperature", probe, 85, default=250.0
        )
        pressure_service = self.clear_service_flag(
            "Inline pressure",
            self.hardware_reader(
                "Inline pickup out of service", dp, 81, boolean=True, default=True
            ),
        )
        temperature_service = self.clear_service_flag(
            "Inline discharge",
            self.hardware_reader(
                "Inline discharge out of service", probe, 81, boolean=True, default=True
            ),
        )
        unforced_flow = self.clear_service_flag(
            "Inline published flow",
            self.hardware_reader(
                "Inline published flow in test", raw_cfm, 3368, boolean=True, default=True
            ),
        )
        witness = self.independent_flow(flow, pressure, dp_hardware)
        witness_ok = self.block("reliable", "Inline pickup calculation reliable", (513, witness))
        pathok = q("and", "Inline pressure and flow reliable", rawok, flowok)
        pathok = q(
            "and",
            "Inline raw pickup available",
            pathok,
            self.block("reliable", "Inline raw pickup quality", (513, dp_hardware)),
        )
        pathok = q("and", "Inline primary and private data reliable", pathok, witness_ok)
        pathok = q("and", "Inline physical pickup available", pathok, pressure_service)
        pathok = q("and", "Inline published flow outside test", pathok, unforced_flow)
        paired = q("min", "Inline corroborated measured CFM", flow_sig, witness)
        safe = self.select("Inline valid flow or zero", pathok, paired)
        nonneg = q("ge", "Inline flow nonnegative", safe, 0)
        pathok = q("and", "Inline supply flow valid", pathok, nonneg)
        clock = self.block(
            "timer", "Inline elapsed time clock", defaults={518: 5, 1080: 60.0}, clock=True
        )
        remaining = (clock[0], 1081)
        clockok = self.block("reliable", "Inline countdown is reliable", (513, remaining))
        phase = self.select(
            "Inline normalized second",
            q("ge", "Inline countdown rollover", remaining, 60.0),
            0.0,
            remaining,
        )
        previous_clock = self.block("prevF", "Inline previous clock second", (513, phase))
        if self.phase_sampling:
            tick, odd, total, ready, mean = self.phase_window(phase, clockok, pathok, safe)
        else:
            difference = q("sub", "Inline clock second difference", previous_clock, phase)
            delta = self.select(
                "Inline elapsed seconds",
                q("ge", "Inline clock did not wrap", difference, 0.0),
                difference,
                q("add", "Inline wrapped countdown", difference, 60.0),
            )
            advanced = q("ge", "Inline countdown advanced", delta, 1.0)
            gap = q("gt", "Inline missed one-second notification", delta, 1.0)
            continuous = self.block(
                "xor", "Inline sample continuity", (7000, gap), defaults={7001: True}
            )
            tick = q("and", "Inline one fresh sample", advanced, continuous)
            watchdog = self.block(
                "timer", "Inline ticking watchdog", (513, tick), defaults={518: 4, 1080: 5.0}
            )
            timed = q(
                "and",
                "Inline clock reports usable timing",
                clockok,
                q("and", "Inline clock fresh without gap", watchdog, continuous),
            )
            have_clock = q("and", "Inline clock and data healthy", timed, pathok)
            warm_input = q(
                "and",
                "Inline valid window timing",
                pathok,
                q("and", "Inline reliable uninterrupted clock", clockok, continuous),
            )
            warm = self.block(
                "timer",
                "Inline full window elapsed",
                (513, warm_input),
                defaults={518: 2, 1080: 30.0},
            )
            accepted = q("and", "Inline fresh airflow sample", have_clock, tick)
            previous = self.block("prevF", "Inline prior sample count")
            plus = q("add", "Inline increment sample count", previous, 1.0)
            bounded = q("min", "Inline cap sample count", plus, 30.0)
            total = self.select("Inline sample count on tick", accepted, bounded, previous)
            total = self.select("Inline clear count on fault", have_clock, total)
            self.wire(total, previous[0], 513)
            full = q("ge", "Inline 30 samples collected", total, 30.0)
            ready = q("and", "Inline complete timed history", full, warm)
            prev = self.block("prevF", "Inline airflow history 01")
            values = []
            src = safe
            for i in range(1, 31):
                if i > 1:
                    prev = self.block("prevF", f"Inline airflow history {i:02d}")
                present = self.select(f"Inline airflow sample {i:02d}", accepted, src, prev)
                self.wire(present, prev[0], 513)
                values.append(present)
                src = prev
            level = 0
            while len(values) > 1:
                level += 1
                new = []
                for pos in range(0, len(values), 2):
                    new.append(
                        q(
                            "add",
                            f"Inline airflow sum {level}-{pos // 2 + 1}",
                            values[pos],
                            values[pos + 1],
                        )
                        if pos + 1 < len(values)
                        else values[pos]
                    )
                values = new
            mean = self.select(
                "Inline complete 30-second mean",
                full,
                q("div", "Inline airflow 30-second mean", values[0], 30.0),
            )
        lock_ok = self.block("reliable", "Inline lockout setting reliable", (513, lock))
        lock = self.select("Inline valid lockout value or zero", lock_ok, lock)
        high_ok = self.block("reliable", "Inline discharge setting reliable", (513, high))
        high = self.select("Inline valid ceiling or zero", high_ok, high)
        above = q("ge", "Inline mean at lockout setting", mean, lock)
        positive = q(
            "and",
            "Inline valid lockout setting",
            lock_ok,
            q("gt", "Inline positive lockout CFM", lock, 0.0),
        )
        proved = q(
            "and",
            "Inline proven average airflow",
            q("and", "Inline complete airflow proof", ready, above),
            positive,
        )
        datok = self.block("reliable", "Inline discharge sensor healthy", (513, dat_sig))
        hardware_temp_ok = self.block(
            "reliable", "Inline physical probe quality", (513, dt_hardware)
        )
        datok = q("and", "Inline duct and physical probe healthy", datok, hardware_temp_ok)
        datok = q("and", "Inline discharge service proven", datok, temperature_service)
        hot = q("max", "Inline higher discharge reading", dat_sig, dt_hardware)
        dat_safe = self.select("Inline usable discharge temp", datok, hot)
        dif = q("sub", "Inline discharge headroom", high, dat_safe)
        pos = q("gt", "Inline below discharge ceiling", dif, 0)
        rearm = q("ge", "Inline high limit reset margin", dif, 2)
        mem = self.block("prevB", "Inline previous thermal permit")
        run = q("and", "Inline remain below limit", mem, pos)
        reset = q("or", "Inline discharge recovered", run, rearm)
        setok = q(
            "and",
            "Inline valid discharge setting",
            high_ok,
            q("gt", "Inline positive discharge limit", high, 0),
        )
        temp = q(
            "and",
            "Inline valid discharge permit",
            q("and", "Inline discharge input available", datok, setok),
            reset,
        )
        self.wire(temp, mem[0], 513)
        allowed = q("and", "Inline temperature and airflow proven", temp, proved)
        permit = q("and", "Inline automatic heat permitted", allowed, (enable["index"], 663))
        self.stage = "late"
        demandok = self.block("reliable", "Inline demand reliable", (513, demand))
        usable = self.select("Inline valid demand or zero", demandok, demand)
        cap = q(
            "min",
            "Inline maximum thermal opening",
            100,
            q(
                "max",
                "Inline nonnegative thermal cap",
                0,
                q("mul", "Inline ten degree throttle band", dif, 10),
            ),
        )
        target = q(
            "min",
            "Inline lesser of room and cap",
            q("max", "Inline nonnegative heat demand", usable, 0),
            cap,
        )
        if self.phase_sampling:
            output = self.phase_ramp(
                tick, odd, q("and", "Inline final automatic permit", permit, demandok), target
            )
        else:
            last = self.block("prevF", "Inline previous valve target")
            step = self.select("Inline permitted opening per tick", tick, 5)
            ramp = q(
                "min",
                "Inline limited upward travel",
                target,
                q("add", "Inline valve opening allowance", last, step),
            )
            output = self.select(
                "Inline protected valve command",
                q("and", "Inline final automatic permit", permit, demandok),
                ramp,
            )
            self.wire(output, last[0], 513)
        self.bind = {
            "airflow": self.read(raw_cfm, 75),
            "discharge": self.read(probe, 75),
            "pressure": self.read(dp, 75),
            "valve": self.read(val, 75),
            "output_type": "floating" if val["class_id"] == 251 else "analog",
            "timer": clock[0],
            "tick": tick[0],
            "n_samples": total[0],
            "ready": ready[0],
            "mean": mean[0],
            "command": output[0],
            "permit": permit[0],
        }
        self.original_edges = [old_enable, original]
        if self.floating_valve is not None:
            self.bind["floating_valve"] = self.floating_valve
        self.new_edges = [(*permit, passthrough["index"], 513), (*output, valve["index"], 7000)]
        self.schedule = (
            self.order[:early]
            + self.stages["early"]
            + self.order[early:late]
            + self.stages["late"]
            + self.order[late:]
        )

    def export(self, *, shadow):
        wires = list(self.wires)
        if not shadow:
            for original, new in zip(self.original_edges, self.new_edges, strict=True):
                wires[wires.index(original)] = new
        required(
            len(self.old) + len(self.ids) <= 512 and len(wires) <= 4096,
            "Root graph exceeds supported size",
        )
        required(len({(e[2], e[3]) for e in wires}) == len(wires), "Duplicate destination")
        rootdata = replace_properties(
            self.application,
            self.root,
            {
                3375: raw_property(self.application, self.root, 3375)[:-1]
                + b"".join(encoded(i) for i in self.ids),
                3117: b"".join(encoded(Unsigned(i)) for i in self.schedule),
                3118: b"".join(_wire(*e) for e in wires),
            },
        )
        records = [
            rootdata
            if r["offset"] == self.root["offset"]
            else self.application.data[r["offset"] : r["end_offset"]]
            for r in self.application.records
        ]
        ordered, added_at, footer = records + self.added, len(records), None
        if self.separate_root_layout:
            ordered, added_at, footer = assemble_root(
                self.application,
                self.root,
                records,
                self.added,
                self.g,
                self.ids,
                len(wires) - len(self.source_wires),
            )
        payload = archive(self.application, ordered)
        re = MoiIdentity(payload)
        g = re.reader.diagram(self.rootref, retained_activity_refs=True)
        verify_layout(self.application, re, footer, g)
        ix = {b["ref"]: b["index"] for b in g["blocks"]}
        wr = [
            (ix[k["source_ref"]], k["source_port"], ix[k["target_ref"]], k["target_port"])
            for k in g["connections"]
        ]
        required(
            not re.reader.errors
            and re.instance == self.application.instance
            and re.summary()["name"] == self.application.summary()["name"]
            and len(re.records) == len(records) + len(self.added),
            "Identity or record count differs",
        )
        required(
            g["execution_order"] == self.schedule
            and wires == wr
            and len(g["blocks"]) == len(self.old) + len(self.ids),
            "Native reparse failed",
        )
        original_positions = re.records[:added_at] + re.records[added_at + len(self.added) :]
        for i, (r, z) in enumerate(zip(self.application.records, original_positions, strict=True)):
            if r["offset"] != self.root["offset"] and i != footer:
                required(r["sha256"] == z["sha256"], "Original record changed")
        new_records = re.records[added_at : added_at + len(self.added)]
        exposed = [r for r in new_records if re.reader.scalar(r, 3807) is True]
        required(
            {re.reader.scalar(r, 2390) for r in exposed} == set(self.exposures)
            and len(exposed) == 2,
            "Unexpected BACnet exposure",
        )
        for r in exposed:
            q = self.exposures[re.reader.scalar(r, 2390)]
            required(
                r["class_id"] == 526
                and (re.reader.scalar(r, 117), re.reader.scalar(r, 3113), re.reader.scalar(r, 75))
                == (q["units"], q["default"], q["object"]),
                "Incorrect exposed tuning point",
            )
        report = {
            "source_sha256": sha(self.original[3]),
            "effective_sha256": self.application.source_sha256,
            "candidate_sha256": sha(payload),
            "format": self.application.summary()["format_versions"],
            "device": self.application.instance,
            "device_name": self.application.summary()["name"],
            "root_ref": self.rootref,
            "valve_wiring": self.bind,
            "new_avs": self.exposures,
            "original_records_preserved": len(records) - 1 - int(footer is not None),
            "original_parameters_merged": self.merge["matched_parameters"],
            "added_records": len(self.added),
            "root_members": len(g["blocks"]),
            "old_wires_replaced": 0 if shadow else 2,
            "added_wires": len(wires) - len(self.source_wires),
            "original_order_preserved": True,
            "verified_native_structure": True,
            "native_timer_cadence_field_verified": False,
            "field_execution_verified": False,
            "shadow": shadow,
            "production_transfer_qualified": False,
        }
        report.update(
            added_objects=self.allocations,
            first_instance=self.first_instance,
            points={name: self.read(item, 75) for name, item in self.physical.items()},
            runtime={k: g["blocks"][v]["object"] for k, v in self.bind.items() if type(v) is int},
            control_edges=[
                {"before": list(a), "after": list(b)}
                for a, b in zip(self.original_edges, self.new_edges, strict=True)
            ],
            effective_native_sha256=sha(self.application.data),
        )
        if self.separate_root_layout:
            report["separate_root_layout_updated"] = footer is not None
        return payload, report


class CompactInlineSequenceCompiler(InlineSequenceCompiler):
    """Offline candidate using two clock witnesses for the thirty airflow registers."""

    def __init__(self, files, donor, first):
        super().__init__(files, donor, first, phase_sampling=True)

    def held(self, label, gate, signal):
        prior = self.block("prevF", label + " memory")
        value = self.select(label, gate, signal, prior)
        self.wire(value, prior[0], 513)
        return value

    def phase_window(self, phase, clock_ok, data_ok, flow):
        q = self.arithmetic
        sectors = self.phase_sectors(phase)
        values = [
            self.held(f"Inline airflow second {i:02d}", sector, flow)
            for i, sector in enumerate(sectors)
        ]
        even = self.combine(sectors[::2], "or", "Inline even clock sector")
        odd = self.block("xor", "Inline odd clock sector", (7000, even), defaults={7001: True})

        # The opposite parity register stays closed throughout the current second,
        # including re-executions triggered by a Last Value propagation.
        # A second timer has a period coprime with the one-minute addressing
        # clock. A missed minute must not appear as the expected next second.
        long_clock = self.block(
            "timer", "Inline long continuity timer", defaults={518: 5, 1080: 3601.0}, clock=True
        )
        raw = (long_clock[0], 1081)
        long_ok = self.block("reliable", "Inline long clock reliable", (513, raw))
        long_phase = self.select(
            "Inline long clock reading",
            q("ge", "Inline long clock rollover", raw, 3601.0),
            0.0,
            raw,
        )

        def elapsed(current, period, name):
            last_even = self.held(name + " even second", even, current)
            last_odd = self.held(name + " odd second", odd, current)
            previous = self.select(name + " opposite second", even, last_odd, last_even)
            difference = q("sub", name + " difference", previous, current)
            return self.select(
                name + " elapsed",
                q("ge", name + " nonwrapped", difference, 0),
                difference,
                q("add", name + " wrapped", difference, period),
            )

        delta = elapsed(phase, 60.0, "Inline short clock")
        long_delta = elapsed(long_phase, 3601.0, "Inline long clock")
        long_step = q(
            "and",
            "Inline secondary clock consecutive",
            q("ge", "Inline secondary clock advanced", long_delta, 1),
            q("ge", "Inline secondary clock bounded", 1, long_delta),
        )
        one_step = q(
            "and",
            "Inline consecutive clock seconds",
            q("ge", "Inline at least one second", delta, 1),
            q("ge", "Inline at most one second", 1, delta),
        )
        recent_even = self.block(
            "timer", "Inline even clock active", (513, even), defaults={518: 4, 1080: 2.0}
        )
        recent_odd = self.block(
            "timer", "Inline odd clock active", (513, odd), defaults={518: 4, 1080: 2.0}
        )
        continuous = q(
            "and",
            "Inline clock advances every second",
            one_step,
            q("and", "Inline clock switches parity", recent_even, recent_odd),
        )
        valid = q("and", "Inline both sampling sources healthy", data_ok, clock_ok)
        valid = q(
            "and",
            "Inline secondary timer confirms progress",
            valid,
            q("and", "Inline long clock advances reliably", long_ok, long_step),
        )
        warm = self.block(
            "timer",
            "Inline complete timed history",
            (513, q("and", "Inline uninterrupted observation", continuous, valid)),
            defaults={518: 2, 1080: 30.0},
        )
        # Warm-up starts only after a valid elapsed tick. Thirty consecutive
        # healthy seconds replace every register, also after quality recovery.
        count = self.select("Inline confirmed samples in complete window", warm, 30.0)
        total = self.combine(values, "add", "Inline measured CFM sum")
        mean = self.select(
            "Inline complete 30-second mean",
            warm,
            q("div", "Inline airflow 30-second mean", total, 30.0),
        )
        return even, odd, count, warm, mean
