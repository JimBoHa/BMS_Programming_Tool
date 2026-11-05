"""Resolve captured hardware hosts without treating root-scoped names as local wiring."""

import re


def input_host(props, present, modules, root, *, sa_records_present):
    unknown = {"kind": "unknown"}
    reference = props.get(32527)
    matches = [
        module
        for module in modules
        if isinstance(module.get("item_reference"), str)
        and isinstance(reference, str)
        and reference.startswith(module["item_reference"] + ".")
    ]
    if len(matches) > 1:
        return unknown, "Native input matches multiple configured SA module references."
    parent = matches[0] if matches else None
    if 2577 in present:
        return (
            unknown,
            "Native Device Reference property requires a separately qualified host interpretation.",
        )
    if 3645 in present:
        mac = props.get(3645)
        if type(mac) is not int or not 1 <= mac <= 254:
            return unknown, "Native SA address has no qualified positive integer module binding."
        if parent is not None and parent["sa_mac"] != mac:
            return unknown, "Explicit SA address conflicts with native parent assignment."
        assigned = [module for module in modules if module["sa_mac"] == mac]
        if len(assigned) != 1:
            return unknown, "Explicit SA address does not identify one configured module."
        return {
            "kind": "sa",
            "sa_mac": mac,
            "evidence": "Explicit native SA Bus MAC Address property 3645 and unique configured module",
        }, None
    if parent is not None:
        if sum(module["sa_mac"] == parent["sa_mac"] for module in modules) != 1:
            return unknown, "Native parent module has an ambiguous configured SA address."
        return {
            "kind": "sa",
            "sa_mac": parent["sa_mac"],
            "evidence": "Native point item-reference beneath configured module",
        }, None
    if (
        isinstance(root, str)
        and isinstance(reference, str)
        and re.fullmatch(re.escape(root) + r"/[0-9]+_[0-9]+", reference)
    ):
        if sa_records_present:
            return (
                unknown,
                "Controller-root input reference does not establish a local host when SA modules are present.",
            )
        return {
            "kind": "local-configured",
            "sa_mac": None,
            "evidence": "Native point item-reference directly beneath controller without SA module records",
        }, None
    return unknown, "Native input lacks an unambiguous configured host binding."
