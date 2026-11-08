"""Authored native SOAP service; no vendor server, SDK or credentials."""

import httpx
import pytest
from bms_tool.nae_https import LOGIN_NS, SOAP, SUPPORT_NS, NaeHttps, NaeSoapError
from defusedxml.ElementTree import fromstring

ORIGIN = "https://engine.example"


class Peer:
    def __init__(self):
        self.requests = []
        self.mode = "normal"

    async def request(self, request):
        self.requests.append(request)
        assert request.method == "POST"
        assert request.headers["POST"] == request.url.path
        assert request.headers["Connection"] == "close"
        assert request.headers["Host"] == "engine.example:443"
        assert int(request.headers["Content-Length"]) == len(request.content)
        doc = fromstring(request.content)
        action = doc.find("{" + SOAP + "}Body")[0]
        method = action.tag.rsplit("}", 1)[-1]
        if method == "LoginOverSecureConnection":
            assert b":Credentials" not in request.content and b":UserName" not in request.content
            assert ('<Credentials xmlns="' + LOGIN_NS + '">').encode() in request.content
            assert request.url.path.endswith("/Security/LoginService.asmx")
            fields = {e.tag.rsplit("}", 1)[-1]: e.text for e in action.iter()}
            assert fields["UserName"] == "authored-user"
            assert fields["Password"] == "authored & <password>"
            assert fields["Domain"] == "Metasys Local"
            assert fields["IsPasswordEncrypted"] == "false"
            if self.mode == "refuse":
                return httpx.Response(
                    500,
                    content=(
                        '<s:Envelope xmlns:s="' + SOAP + '"><s:Body><s:Fault><faultstring>'
                        "Invalid Credentials authored-user authored &amp; &lt;password&gt;"
                        "</faultstring></s:Fault></s:Body></s:Envelope>"
                    ).encode(),
                )
            if self.mode == "doctype":
                return httpx.Response(200, content=b'<!DOCTYPE x [<!ENTITY x "bad">]><x>&x;</x>')
            result = (
                '<LoginOverSecureConnectionResponse xmlns="'
                + LOGIN_NS
                + '" xmlns:z="urn:authored-token">'
                "<LoginOverSecureConnectionResult><UserName>authored-user</UserName><UserId>42</UserId>"
                '<securityToken><z:EncryptedData z:marker="opaque">authored-session-token</z:EncryptedData>'
                "</securityToken></LoginOverSecureConnectionResult></LoginOverSecureConnectionResponse>"
            )
        else:
            header = doc.find("{" + SOAP + "}Header")[0]
            assert header.tag.rsplit("}", 1)[-1] == "LoginResult"
            assert (
                b'<z:EncryptedData z:marker="opaque">authored-session-token</z:EncryptedData>'
                in request.content
            )
            assert (
                header.find(".//{urn:authored-token}EncryptedData").text == "authored-session-token"
            )
            if method == "GetConfigView":
                fields = {e.tag.rsplit("}", 1)[-1]: e.text for e in action.iter()}
                assert fields["reference"] == "Example:Engine"
                result = (
                    '<GetConfigViewResponse xmlns="'
                    + SUPPORT_NS
                    + '"><GetConfigViewResult><Config/></GetConfigViewResult></GetConfigViewResponse>'
                )
            else:
                assert method == "Logout"
                result = '<LogoutResponse xmlns="' + LOGIN_NS + '"/>'
        return httpx.Response(
            200,
            content=(
                '<s:Envelope xmlns:s="' + SOAP + '"><s:Body>' + result + "</s:Body></s:Envelope>"
            ).encode(),
        )


@pytest.fixture
async def link():
    peer = Peer()
    client = httpx.AsyncClient(base_url=ORIGIN, transport=httpx.MockTransport(peer.request))
    native = NaeHttps(ORIGIN, client)
    try:
        yield native, peer
    finally:
        await native.close()


async def test_native_login_read_and_logout_preserve_opaque_token_and_do_not_use_tool_apis(link):
    native, peer = link
    result = await native.login(username="authored-user", password="authored & <password>")
    assert result["authenticated"] and result["jct_sct_required"] is False
    assert "authored-session-token" not in repr(native) + str(result)
    view = await native.config_view("Example:Engine", 123, "1.0")
    assert view.tag == "{" + SUPPORT_NS + "}GetConfigViewResponse"
    await native.close()
    assert native.header is None and native.client.is_closed
    assert len(peer.requests) == 3 and all("/MetasysIII/WS/" in r.url.path for r in peer.requests)


@pytest.mark.parametrize("mode", ["refuse", "doctype"])
async def test_native_refusal_and_invalid_xml_do_not_echo_credentials_or_grant_authority(
    link, mode
):
    native, peer = link
    peer.mode = mode
    with pytest.raises(NaeSoapError) as exc:
        await native.login(username="authored-user", password="authored & <password>")
    assert "authored" not in str(exc.value) and native.header is None
    assert len(peer.requests) == 1


@pytest.mark.parametrize(
    "endpoint,method,namespace",
    [
        ("Archive/Archive.asmx", "ApplyArchiveChanges", "urn:unsupported"),
        ("Item/MonitoringAndCommanding.asmx", "WritePropertyMultiple", "urn:unsupported"),
        ("Item/Support.asmx", "GetConfigView", LOGIN_NS),
    ],
)
async def test_native_https_does_not_admit_unqualified_mutations_or_cross_service_namespaces(
    link, endpoint, method, namespace
):
    native, peer = link
    with pytest.raises(ValueError):
        await native._request(endpoint, method, namespace)
    assert not peer.requests


async def test_changed_certificate_stops_before_native_login_dispatch(monkeypatch):
    monkeypatch.setattr(
        "bms_tool.nae_https.ssl.get_server_certificate", lambda *a, **k: "authored certificate"
    )
    monkeypatch.setattr("bms_tool.nae_https.ssl.PEM_cert_to_DER_cert", lambda _: b"authored DER")
    with pytest.raises(ValueError, match="certificate changed"):
        await NaeHttps.connect(ORIGIN, "0" * 64, username="authored-user", password="withheld")
