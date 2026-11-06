"""Local IPv4 choices for connection setup; enumeration does not open BACnet."""

import ipaddress
import socket

import ifaddr


def _preferred_ip():
    # UDP connect asks the OS which source it would route with; no packet is sent.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            return probe.getsockname()[0]
    except OSError:
        return None


def ipv4_interfaces():
    preferred = _preferred_ip()
    rows = {}
    for adapter in ifaddr.get_adapters():
        for entry in adapter.ips:
            if not isinstance(entry.ip, str):
                continue
            try:
                ip = ipaddress.IPv4Address(entry.ip)
                network = ipaddress.IPv4Network((ip, entry.network_prefix), strict=False)
            except ValueError:
                continue
            if ip.is_loopback or ip.is_unspecified or ip.is_multicast:
                continue
            key = (str(ip), entry.network_prefix)
            rows.setdefault(
                key,
                {
                    "address": str(ip),
                    "name": str(adapter.nice_name or adapter.name),
                    "network": str(network),
                    "prefix": entry.network_prefix,
                    "recommended": str(ip) == preferred,
                    "broadcast_available": network.prefixlen < 31,
                },
            )
    choices = sorted(
        rows.values(), key=lambda row: (not row["recommended"], row["name"], row["address"])
    )
    return {"interfaces": choices, "read_only": True, "opens_connection": False}
