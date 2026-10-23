"""Owned virtual COV links must not derive persistent names from UDP ports."""

import asyncio
import socket
from uuid import uuid4

from bacpypes3.pdu import LocalStation
from bacpypes3.vlan import VirtualNetwork, VirtualNode
from bms_tool.connections import Bacnet
from bms_tool.storage import Store

from . import test_bacnet_cov_routed as routed
from .test_connections import free_udp


def network_of(field):
    return next(layer.node.lan for layer in field.link_layers.values() if hasattr(layer, "node"))


def discard_owned_network(network):
    # Failure cleanup for this regression alone. Never clear global registries
    # or replace a mapping that another owner installed.
    for node in list(network.nodes):
        network.remove_node(node)
    if VirtualNetwork._networks.get(network.name) is network:
        del VirtualNetwork._networks[network.name]


async def test_closed_pairs_reuse_the_same_udp_port_without_reusing_virtual_identity(
    tmp_path, monkeypatch
):
    server_port = free_udp()
    monkeypatch.setattr(routed, "free_udp", lambda: server_port)
    unrelated = VirtualNetwork("cov-unrelated-" + uuid4().hex)
    owned, names = [], []
    try:
        for index in range(2):
            router, field, _, config, _ = routed.routed_pair(4190012 + index * 10)
            network = network_of(field)
            owned.append(network)
            names.append(network.name)
            client = Bacnet(Store(tmp_path / str(index)))
            try:
                await client.connect(
                    f"127.0.0.1:{free_udp()}", router=config["router"], dnet=config["dnet"]
                )
                result = await client.read(config["address"], config["object_id"])
                assert result["value"] == 12.5
            finally:
                client.close()
                routed.close_routed_pair(router, field)
                await asyncio.sleep(0.02)
            # Prove the old real UDP socket released before the next pair.
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as check:
                check.bind(("127.0.0.1", server_port))
        assert len(set(names)) == 2
        assert all(not network.nodes for network in owned)
        assert all(network.name not in VirtualNetwork._networks for network in owned)
        assert VirtualNetwork._networks[unrelated.name] is unrelated
    finally:
        for network in owned:
            discard_owned_network(network)
        discard_owned_network(unrelated)


async def test_pair_cleanup_keeps_foreign_nodes_and_is_idempotent():
    router, field, _, _, _ = routed.routed_pair()
    network = network_of(field)
    foreign = VirtualNode(LocalStation(9), network.name)
    try:
        routed.close_routed_pair(router, field)
        routed.close_routed_pair(router, field)
        await asyncio.sleep(0.02)
        assert network.nodes == [foreign]
        assert foreign.lan is network
        assert VirtualNetwork._networks[network.name] is network
        network.remove_node(foreign)
        routed.close_routed_pair(router, field)
        assert network.name not in VirtualNetwork._networks
    finally:
        routed.close_routed_pair(router, field)
        discard_owned_network(network)


async def test_pair_cleanup_never_removes_a_replacement_registry_owner():
    router, field, _, _, _ = routed.routed_pair()
    network = network_of(field)
    replacement = VirtualNetwork("cov-replacement-" + uuid4().hex)
    try:
        VirtualNetwork._networks[network.name] = replacement
        routed.close_routed_pair(router, field)
        routed.close_routed_pair(router, field)
        await asyncio.sleep(0.02)
        assert not network.nodes
        assert VirtualNetwork._networks[network.name] is replacement
        assert VirtualNetwork._networks[replacement.name] is replacement
    finally:
        routed.close_routed_pair(router, field)
        if VirtualNetwork._networks.get(network.name) is replacement:
            del VirtualNetwork._networks[network.name]
        discard_owned_network(replacement)
