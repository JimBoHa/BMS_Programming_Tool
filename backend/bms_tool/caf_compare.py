"""Compare observed CAF records without inventing native application semantics.

Both original archives stay untouched. Object references and property kind/ID
are exact identities; names never cause fuzzy remapping between controllers.
Unknown records, simulation values, order and container differences stay visible.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from xml.parsers import expat

from .caf import ATTRIBUTES, BY_CLASS, CLASSES, CafArchive, Q

SCOPE = (
    "Offline native record comparison only. No compilation, controller compatibility "
    "decision, program simulation or device write."
)
CATEGORIES = {
    "object_identity",
    "object_membership",
    "record_order",
    "controller_identity",
    "wiring",
    "execution_order",
    "block_membership",
    "drawing",
    "application_value",
    "simulation_value",
    "native_metadata",
    "opaque_metadata",
}
GRAPH_FIELDS = {
    "3118": "wiring",
    "3117": "execution_order",
    "3375": "block_membership",
    "3383": "drawing",
    "3384": "drawing",
}
QNAME = re.compile(r"(?<![\w.:-])([\w.-]+):([\w.-]+)(?![\w.:-])")


def _lexical_evidence(xml):
    """Retain XML evidence that ElementTree's expanded-name tree omits.

    Comments/PIs may contain operator information. QName-valued attributes or
    text depend on namespace bindings even when their literal value is unchanged.
    Hash every event; keep only a bounded preview of this ancillary evidence.
    """
    parser = expat.ParserCreate(namespace_separator="\x1f")
    parser.buffer_text = True
    groups = {
        key: {"hash": hashlib.sha256(), "count": 0, "preview": []}
        for key in ("annotations", "qname_bindings")
    }
    stack, bindings, pending = [], {"xml": "http://www.w3.org/XML/1998/namespace"}, []
    outside_position = 0
    root_state = "before_root"

    def emit(group, value):
        target = groups[group]
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        target["hash"].update(len(raw).to_bytes(8, "big"))
        target["hash"].update(raw)
        target["count"] += 1
        if len(target["preview"]) < 8:
            decoded = raw.decode()
            target["preview"].append({"event": decoded[:2048], "truncated": len(decoded) > 2048})

    def qnames(text, location):
        # A declared prefix is required. URLs and undeclared prose prefixes do
        # not create bindings; an ambiguous declared token stays reviewable.
        used = sorted({match[1] for match in QNAME.finditer(text) if match[1] in bindings})
        if used:
            emit("qname_bindings", [location, [(prefix, bindings[prefix]) for prefix in used]])

    def flush_text():
        if stack and stack[-1]["text"]:
            frame = stack[-1]
            qnames("".join(frame["text"]), [frame["path"], "text", frame["children"]])
            frame["text"].clear()

    def start(tag, attrs):
        nonlocal root_state
        flush_text()
        if stack:
            parent = stack[-1]
            path = (*parent["path"], parent["children"])
            parent["children"] += 1
        else:
            path = ()
            root_state = "inside_root"
        restore = []
        for prefix, uri in pending:
            restore.append((prefix, bindings.get(prefix)))
            bindings[prefix] = uri
        pending.clear()
        stack.append({"path": path, "children": 0, "restore": restore, "text": []})
        for key, value in sorted(attrs.items()):
            qnames(value, [path, "attribute", key])
            if key == "http://www.w3.org/2001/XMLSchema-instance\x1ftype" and re.fullmatch(
                r"[^\W\d][\w.-]*", value.strip()
            ):
                # Unlike arbitrary strings, xsi:type is known to be a QName.
                # Its unprefixed form resolves through the default namespace.
                emit("qname_bindings", [[path, "attribute", key], [("", bindings.get("", ""))]])

    def end(tag):
        nonlocal root_state
        flush_text()
        frame = stack.pop()
        if not stack:
            root_state = "after_root"
        for prefix, previous in reversed(frame["restore"]):
            if previous is None:
                bindings.pop(prefix, None)
            else:
                bindings[prefix] = previous

    def annotation(kind, *values):
        nonlocal outside_position
        # Do not flush text: a comment does not split a possible QName token.
        position = (
            [stack[-1]["path"], stack[-1]["children"]] if stack else [root_state, outside_position]
        )
        emit("annotations", [position, kind, *values])
        if not stack:
            outside_position += 1

    def reject(*args):
        raise ValueError("XML entities and DTDs are forbidden.")

    parser.StartNamespaceDeclHandler = lambda prefix, uri: pending.append((prefix or "", uri or ""))
    parser.StartElementHandler, parser.EndElementHandler = start, end
    parser.CharacterDataHandler = lambda text: stack[-1]["text"].append(text) if stack else None
    parser.CommentHandler = lambda text: annotation("comment", text)
    parser.ProcessingInstructionHandler = lambda target, data: annotation(
        "processing_instruction", target, data
    )
    parser.StartDoctypeDeclHandler = parser.EntityDeclHandler = parser.ExternalEntityRefHandler = (
        reject
    )
    parser.Parse(xml, True)
    return {
        key: {
            "sha256": value["hash"].hexdigest(),
            "events": value["count"],
            "preview": value["preview"],
            "preview_truncated": value["count"] > 8,
        }
        for key, value in groups.items()
    }


def _attribute_preview(attributes):
    preview, budget = {}, 4096
    for key, value in sorted(attributes.items()):
        if len(preview) >= 16 or budget < 2:
            break
        clipped_key = key[: min(256, budget // 2)]
        budget -= len(clipped_key)
        clipped_value = value[: min(512, budget)]
        budget -= len(clipped_value)
        preview[clipped_key] = clipped_value
    return preview, preview != attributes


def _mixed(text):
    return text if text and text.strip() else ""


def _identity_preview(values, limit=256):
    """Bound repeated identity previews without changing internal matching keys."""
    preview, truncated = {}, {}
    for key, value in values.items():
        preview[key] = value[:limit] if isinstance(value, str) else value
        if isinstance(value, str) and len(value) > limit:
            truncated[key] = {
                "characters": len(value),
                "sha256": hashlib.sha256(value.encode()).hexdigest(),
            }
    return preview, truncated


def _summary_preview(summary):
    preview, truncated = _identity_preview(
        {
            key: summary[key]
            for key in (
                "sha256",
                "entry",
                "xml_bytes",
                "objects",
                "model",
                "release_mode",
                "validation",
            )
        }
    )
    return {**preview, "truncated_fields": truncated}


def _fingerprints(root):
    fingerprints, counts = {}, {}
    for item in reversed(list(root.iter())):
        text = item.text or ""
        if (len(item) or item.tag in {Q + "object", Q + "objects"}) and not text.strip():
            text = ""
        content = [
            item.tag,
            sorted(item.attrib.items()),
            text,
            [
                [fingerprints[child], child.tail if (child.tail or "").strip() else ""]
                for child in item
            ],
        ]
        fingerprints[item] = hashlib.sha256(
            json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        counts[item] = 1 + sum(counts[child] for child in item)
    return fingerprints, counts


def _keys(children):
    seen, result = Counter(), {}
    for child in children:
        base = (child.tag, child.get("id", ""))
        key = (*base, seen[base])
        seen[base] += 1
        result[key] = child
    return result


def _order_evidence(order):
    return {
        "sha256": hashlib.sha256(json.dumps(order, ensure_ascii=False).encode()).hexdigest(),
        "events": len(order),
        "preview": [
            {
                "event": json.dumps(item, ensure_ascii=False)[:2048],
                "truncated": len(json.dumps(item, ensure_ascii=False)) > 2048,
            }
            for item in order[:8]
        ],
        "preview_truncated": len(order) > 8,
    }


def _label(obj):
    name = next(
        (CafArchive.scalar(p) for p in obj if p.tag == Q + "property" and p.get("id") == "2390"),
        None,
    )
    preview, truncated = _identity_preview(
        {
            "ref": obj.get("ref"),
            "name": (name or {}).get("text", ""),
            "class_id": obj.get("classid"),
        }
    )
    return {
        **preview,
        "truncated_fields": truncated,
        "class_name": CLASSES.get(obj.get("classid"), {}).get("name", "Unknown class"),
    }


def _side(element, hashes, counts):
    if element is None:
        return None
    scalar = CafArchive.scalar(element)
    if scalar:
        scalar = dict(scalar)
        text = scalar["text"]
        scalar["text"] = text[:2048]
        scalar["text_truncated"] = len(text) > 2048
        scalar["attributes"], scalar["attributes_truncated"] = _attribute_preview(
            scalar["attributes"]
        )
        scalar["type_truncated"] = len(scalar["type"]) > 256
        scalar["type"] = scalar["type"][:256]
    attributes, attributes_truncated = _attribute_preview(element.attrib)
    mixed_content = []
    for index, child in enumerate(element.iter()):
        if index >= 64 or len(mixed_content) >= 8:
            break
        for kind, text in (("text", child.text if len(child) else None), ("tail", child.tail)):
            if _mixed(text):
                mixed_content.append(
                    {"element": child.tag.removeprefix(Q)[:256], "kind": kind, "text": text[:2048]}
                )
    return {
        "sha256": hashlib.sha256(
            json.dumps([hashes[element], _mixed(element.tail)], ensure_ascii=False).encode()
        ).hexdigest(),
        "attributes": attributes,
        "attributes_count": len(element.attrib),
        "attributes_truncated": attributes_truncated,
        "scalar": scalar,
        "elements": counts[element],
        "child_types": [child.tag.removeprefix(Q)[:256] for child in list(element)[:12]],
        "mixed_text": (element.text or "")[:2048]
        if len(element) and (element.text or "").strip()
        else None,
        "tail_text": (element.tail or "")[:2048] if (element.tail or "").strip() else None,
        "mixed_content": mixed_content,
        "leaf_text": (element.text or "")[:2048] if not len(element) else None,
        "leaf_text_truncated": not len(element) and len(element.text or "") > 2048,
    }


def _same_numeric_lexeme(before, after):
    old, new = CafArchive.scalar(before), CafArchive.scalar(after)
    if not old or not new or old["type"] != new["type"] or old["attributes"] != new["attributes"]:
        return False
    if (
        before.tag != after.tag
        or before.attrib != after.attrib
        or len(before) != 1
        or len(after) != 1
        or before[0].attrib != after[0].attrib
        or (before.tail or "").strip()
        or (after.tail or "").strip()
    ):
        return False
    old_elements, new_elements = list(before.iter()), list(after.iter())
    if len(old_elements) != 3 or len(new_elements) != 3:
        return False
    for index, (left, right) in enumerate(zip(old_elements, new_elements, strict=True)):
        if (
            left.tag != right.tag
            or left.attrib != right.attrib
            or _mixed(left.tail) != _mixed(right.tail)
            or (index < 2 and _mixed(left.text) != _mixed(right.text))
        ):
            return False
    if old["type"] not in {
        "float",
        "double",
        "short",
        "unsignedByte",
        "unsignedShort",
        "unsignedLong",
        "long",
        "enum",
    }:
        return False
    if max(len(old["text"]), len(new["text"])) > 200:
        return False
    try:
        left, right = Decimal(old["text"]), Decimal(new["text"])
        return left.is_finite() and right.is_finite() and left == right
    except InvalidOperation:
        return False


def _category(obj, key, primary_ref):
    kind, pid, _ = key
    if kind == Q + "simulationProperty":
        return "simulation_value"
    if kind != Q + "property":
        return "opaque_metadata"
    if obj.get("ref") == primary_ref and pid in {"12", "70"}:
        return "controller_identity"
    if obj.get("classid") in {"536", "575"} and pid in GRAPH_FIELDS:
        return GRAPH_FIELDS[pid]
    return "application_value" if pid == "3113" else "native_metadata"


def compare_cafs(
    before: CafArchive | bytes,
    after: CafArchive | bytes,
    *,
    offset=0,
    limit=100,
    category=None,
    query="",
):
    if type(offset) is not int or not 0 <= offset <= 200000:
        raise ValueError("CAF comparison offset must be 0..200000.")
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("CAF comparison page size must be 1..500.")
    if category is not None and category not in CATEGORIES:
        raise ValueError("Unknown CAF comparison category.")
    if not isinstance(query, str) or len(query) > 200:
        raise ValueError("CAF comparison search is limited to 200 characters.")
    before = before if isinstance(before, CafArchive) else CafArchive(before)
    after = after if isinstance(after, CafArchive) else CafArchive(after)
    old_hashes, old_counts = _fingerprints(before.root)
    new_hashes, new_counts = _fingerprints(after.root)
    old_lexical, new_lexical = _lexical_evidence(before.xml), _lexical_evidence(after.xml)
    changes = []
    primary_ref = next(iter(after.objects), next(iter(before.objects), None))
    labels = {
        ref: _label(after.objects[ref] if ref in after.objects else before.objects[ref])
        for ref in before.objects.keys() | after.objects.keys()
    }

    def add(kind, group, *, ref=None, key=None, old=None, new=None, **details):
        obj = after.objects.get(ref) if ref in after.objects else before.objects.get(ref)
        identity, truncated = _identity_preview(
            {
                "record_kind": key[0].removeprefix(Q) if key else None,
                "property_id": key[1] if key else None,
            }
        )
        label = labels.get(ref)
        identity["ref"] = label["ref"] if label else None
        if label and "ref" in label["truncated_fields"]:
            truncated["ref"] = label["truncated_fields"]["ref"]
        changes.append(
            {
                "change": kind,
                "category": group,
                **identity,
                "truncated_identity_fields": truncated,
                "object": labels.get(ref),
                "occurrence": key[2] if key else None,
                "property_name": BY_CLASS.get(obj.get("classid"), {}).get(
                    key[1], ATTRIBUTES.get(key[1], "Unmapped property")
                )
                if obj is not None and key
                else None,
                "_old": old,
                "_new": new,
                **details,
            }
        )

    if before.root.attrib != after.root.attrib:
        add("root_attributes_changed", "opaque_metadata", old=before.root, new=after.root)
    if _mixed(before.root.text) != _mixed(after.root.text):
        add("root_text_changed", "opaque_metadata", old=before.root, new=after.root)
    for kind in old_lexical:
        if old_lexical[kind]["sha256"] != new_lexical[kind]["sha256"]:
            add(
                f"xml_{kind}_changed",
                "opaque_metadata",
                before_evidence=old_lexical[kind],
                after_evidence=new_lexical[kind],
            )

    def root_order(archive):
        return [(item.tag, item.get("ref", item.get("id", ""))) for item in archive.root]

    old_order, new_order = root_order(before), root_order(after)
    if old_order != new_order:
        add(
            "root_record_order_changed",
            "record_order",
            before_evidence=_order_evidence(old_order),
            after_evidence=_order_evidence(new_order),
            before_count=len(old_order),
            after_count=len(new_order),
        )
    for ref in sorted(before.objects.keys() | after.objects.keys()):
        old, new = before.objects.get(ref), after.objects.get(ref)
        if old is None or new is None:
            add(
                "object_added" if old is None else "object_removed",
                "object_membership",
                ref=ref,
                old=old,
                new=new,
            )
            continue
        if old.attrib != new.attrib:
            add("object_attributes_changed", "object_identity", ref=ref, old=old, new=new)
        if _mixed(old.text) != _mixed(new.text) or _mixed(old.tail) != _mixed(new.tail):
            add("object_text_changed", "opaque_metadata", ref=ref, old=old, new=new)
        old_records, new_records = _keys(old), _keys(new)
        if list(old_records) != list(new_records):
            add(
                "record_order_changed",
                "record_order",
                ref=ref,
                before_evidence=_order_evidence(list(old_records)),
                after_evidence=_order_evidence(list(new_records)),
                before_count=len(old_records),
                after_count=len(new_records),
            )
        for key in sorted(old_records.keys() | new_records.keys()):
            left, right = old_records.get(key), new_records.get(key)
            if (
                left is not None
                and right is not None
                and old_hashes[left] == new_hashes[right]
                and _mixed(left.tail) == _mixed(right.tail)
            ):
                continue
            kind = (
                "record_added"
                if left is None
                else "record_removed"
                if right is None
                else "record_changed"
            )
            add(
                kind,
                _category(new, key, primary_ref),
                ref=ref,
                key=key,
                old=left,
                new=right,
                numeric_lexeme_only=left is not None
                and right is not None
                and _same_numeric_lexeme(left, right),
            )
    old_metadata = _keys(child for child in before.root if child.tag != Q + "object")
    new_metadata = _keys(child for child in after.root if child.tag != Q + "object")
    for key in sorted(old_metadata.keys() | new_metadata.keys()):
        left, right = old_metadata.get(key), new_metadata.get(key)
        if (
            left is not None
            and right is not None
            and old_hashes[left] == new_hashes[right]
            and _mixed(left.tail) == _mixed(right.tail)
        ):
            continue
        add("root_metadata_changed", "opaque_metadata", key=key, old=left, new=right)
    filtered = [
        row
        for row in changes
        if (category is None or row["category"] == category)
        and (
            not query
            or query.casefold()
            in json.dumps(
                {k: v for k, v in row.items() if not k.startswith("_")}, ensure_ascii=False
            ).casefold()
        )
    ]
    page = []
    for index, row in enumerate(filtered[offset : offset + limit], offset):
        item = {key: value for key, value in row.items() if not key.startswith("_")}
        item.update(
            index=index,
            before=_side(row["_old"], old_hashes, old_counts),
            after=_side(row["_new"], new_hashes, new_counts),
        )
        page.append(item)
    before_summary, after_summary = before.summary(), after.summary()
    target_keys = ("model", "release_mode")
    target_metadata_equal = (
        all(before_summary[key] == after_summary[key] for key in target_keys)
        if all(before_summary[key] and after_summary[key] for key in target_keys)
        else None
    )
    return {
        "before": _summary_preview(before_summary),
        "after": _summary_preview(after_summary),
        "byte_identical": before.original == after.original,
        "xml_identical": before.xml == after.xml,
        "native_records_equal": old_hashes[before.root] == new_hashes[after.root]
        and all(old_lexical[key]["sha256"] == new_lexical[key]["sha256"] for key in old_lexical),
        "target_metadata_equal": target_metadata_equal,
        "counts": dict(Counter(row["category"] for row in changes)),
        "total": len(changes),
        "filtered_total": len(filtered),
        "offset": offset,
        "limit": limit,
        "changes": page,
        "can_apply": False,
        "scope": SCOPE,
        "matching": "Exact object reference and native record kind/ID only. Names do not remap objects between controllers.",
        "normalization": "Namespace prefixes on element/attribute names, attribute ordering, empty XML syntax and container indentation are normalized. Leaf text, native record order, comments, processing instructions and namespace bindings referenced by prefixed text/attribute tokens or unprefixed xsi:type values remain significant. Numeric lexeme equivalence is descriptive only. Preview values are bounded; hashes cover full compared content.",
    }
