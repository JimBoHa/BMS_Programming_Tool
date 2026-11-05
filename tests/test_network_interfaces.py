"""Connection setup uses observed networks without opening a field interface."""

from types import SimpleNamespace

from bms_tool import network_interfaces as module
from bms_tool.app import create_app
from fastapi.testclient import TestClient


def adapter(name, *addresses):
    return SimpleNamespace(
        name=name,
        nice_name=name,
        ips=[SimpleNamespace(ip=ip, network_prefix=prefix) for ip, prefix in addresses],
    )


def test_network_choices_use_actual_prefix_and_os_recommendation(monkeypatch):
    monkeypatch.setattr(module, "_preferred_ip", lambda: "192.0.2.40")
    monkeypatch.setattr(
        module.ifaddr,
        "get_adapters",
        lambda: [
            adapter("Loopback", ("127.0.0.1", 8)),
            adapter("Ethernet", ("198.51.100.5", 27)),
            adapter("Wi-Fi", ("192.0.2.40", 26), (("2001:db8::1", 0, 0), 64)),
            adapter("Duplicate", ("192.0.2.40", 26)),
        ],
    )
    report = module.ipv4_interfaces()
    assert report["opens_connection"] is False
    assert report["interfaces"] == [
        {
            "address": "192.0.2.40",
            "name": "Wi-Fi",
            "network": "192.0.2.0/26",
            "prefix": 26,
            "recommended": True,
            "broadcast_available": True,
        },
        {
            "address": "198.51.100.5",
            "name": "Ethernet",
            "network": "198.51.100.0/27",
            "prefix": 27,
            "recommended": False,
            "broadcast_available": True,
        },
    ]


def test_network_choice_endpoint_is_read_only_and_preserves_connection_state(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "_preferred_ip", lambda: None)
    monkeypatch.setattr(
        module.ifaddr, "get_adapters", lambda: [adapter("Tunnel", ("192.0.2.8", 32))]
    )
    app = create_app(tmp_path)
    with TestClient(app) as client:
        before = client.get("/api/bacnet/status").json()
        response = client.get("/api/bacnet/interfaces")
        assert response.status_code == 200
        assert response.json()["interfaces"][0]["broadcast_available"] is False
        assert client.get("/api/bacnet/status").json() == before
