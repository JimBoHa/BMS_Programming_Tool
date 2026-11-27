"""Keep the separate 62/62 root drawing tables aligned with their native graph."""

from bacpypes3.primitivedata import Boolean, CharacterString, ObjectIdentifier, Real, Unsigned

from .moi_application import _list, _structs
from .native_inputs import encoded, raw_property, record_instance, replace_properties

POSITION = (Real, Real, Unsigned)
CONTINUATION = (Boolean, CharacterString)


def _row(*values):
    return b"\x3e" + b"".join(encoded(value) for value in values) + b"\x3f"


def assemble_root(app, root, records, additions, graph, member_ids, extra_wires):
    """Return ordered raw records, the addition offset and the edited footer index."""
    layouts = [
        (i, r)
        for i, r in enumerate(app.records)
        if r["class_id"] == 127 and {3383, 3384} & r["properties"].keys()
    ]
    if not layouts:
        # An opaque trailing metadata record still belongs at the end. Archives
        # without a separate root drawing have no parallel tables to extend.
        insert = len(records) - int(app.records[-1]["class_id"] == 127)
        return records[:insert] + additions + records[insert:], insert, None
    if len(layouts) != 1:
        raise ValueError("Ambiguous separate native root layout.")
    insert, footer = layouts[0]
    if (
        insert != len(records) - 1
        or record_instance(app, footer) != record_instance(app, root)
        or not {3383, 3384} <= footer["properties"].keys()
    ):
        raise ValueError(
            "The separate native root layout is incomplete, misplaced or belongs to a different root."
        )
    positions = _structs(footer["properties"][3383]["tags"], POSITION)
    continuations = _structs(footer["properties"][3384]["tags"], CONTINUATION)
    if len(positions) != len(graph["blocks"]) or len(continuations) != len(graph["connections"]):
        raise ValueError("Existing root layout counts differ from the original blocks or wires.")

    # Carry forward the recorded display flags for a member of the same native
    # public type. Coordinates of new blocks remain unplaced. Nested activity
    # drawings often provide primitive types absent from the root diagram.
    styles = {}

    def index(ids, rows):
        for oid, (_, _, flags) in zip(ids, rows, strict=True):
            styles.setdefault(int(oid[0]), int(flags))

    index([ObjectIdentifier(b["object"]) for b in graph["blocks"]], positions)
    for r in app.records:
        p = r["properties"]
        if r["class_id"] == 536 and {3375, 3383} <= p.keys():
            ids = _list(p[3375]["tags"], ObjectIdentifier)
            rows = _structs(p[3383]["tags"], POSITION)
            index(ids, rows)
    added_positions = b"".join(
        _row(Real(0), Real(0), Unsigned(styles.get(int(oid[0]), 0))) for oid in member_ids
    )
    ordinary_wire = _row(Boolean(False), CharacterString(""))
    replacements = {
        3383: raw_property(app, footer, 3383)[:-1] + added_positions,
        3384: raw_property(app, footer, 3384)[:-1] + ordinary_wire * extra_wires,
    }
    tail = replace_properties(app, footer, replacements)
    return records[:insert] + additions + [tail], insert, insert


def verify_layout(source, app, footer, graph):
    if footer is None:
        return
    last = app.records[-1]
    original = source.records[footer]
    props = last["properties"]
    if (
        last["class_id"] != 127
        or record_instance(source, original) != record_instance(app, last)
        or props.keys() != original["properties"].keys()
        or len(_structs(props[3383]["tags"], POSITION)) != len(graph["blocks"])
        or len(_structs(props[3384]["tags"], CONTINUATION)) != len(graph["connections"])
    ):
        raise ValueError("The serialized native root layout does not cover the complete graph.")
    for pid in props:
        old, new = raw_property(source, original, pid), raw_property(app, last, pid)
        retained = new.startswith(old[:-1]) if pid in (3383, 3384) else new == old
        if not retained:
            raise ValueError(
                "The serialized native layout changed original drawing or selection data."
            )
