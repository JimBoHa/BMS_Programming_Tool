"""Validate persisted native graphs before any compiler or Sox mutation is used."""

import pytest
from bms_tool.native_document import NativeDocument


def test_native_child_limit_matches_the_sdk_capacity():
    components = [
        {"path": f"/online/b{index}", "type": "types::WriteFloat"} for index in range(201)
    ]
    assert len(NativeDocument(components=components[:200]).components) == 200
    with pytest.raises(ValueError, match="200-child"):
        NativeDocument(components=components)


def test_native_saved_graph_rejects_incompatible_link_values():
    components = [
        {"path": "/online/enable", "type": "types::ConstBool", "properties": {"out": "true"}},
        {"path": "/online/sensor", "type": "types::WriteFloat", "properties": {"in": "null"}},
    ]
    with pytest.raises(ValueError, match="type mismatch"):
        NativeDocument(
            components=components,
            links=[{"source": "/online/enable", "target": "/online/sensor", "target_port": "in"}],
        )
