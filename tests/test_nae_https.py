"""Authored native SOAP service; no vendor server, SDK or credentials."""

import httpx
import pytest
from bms_tool.nae_https import (
    INTEGRATION_NS,
    LOGIN_NS,
    NAV_NS,
    SOAP,
    SUPPORT_NS,
    NaeHttps,
    NaeSoapError,
)
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
            elif method in (
                "GetNavView",
                "GetViewList",
                "GetView",
                "GetEngView",
                "ReadPropertyMultiple",
            ):
                fields = {e.tag.rsplit("}", 1)[-1]: e.text for e in action.iter()}
                assert fields["reference"] == "Example:Engine"
                namespace = INTEGRATION_NS if method == "GetEngView" else NAV_NS
                assert header.tag == "{" + namespace + "}LoginResult"
                assert request.url.path.endswith(
                    "/Integration/Integration.asmx"
                    if method == "GetEngView"
                    else "/Item/MonitoringAndCommanding.asmx"
                )
                if method == "GetNavView":
                    assert fields["classId"] == "-1"  # unfiltered descendants
                    assert fields["recursiveDepth"] == "2"
                    assert fields["includeExtensions"] == "true"
                elif method == "GetViewList":
                    assert fields["activeViewsOnly"] == "true"
                    assert fields["returnDefaultView"] == "false"
                    assert fields["editMode"] == "false"
                    assert fields["useDictionary"] == "false"
                elif method == "GetView":
                    assert fields["viewId"] == "27"
                    assert fields["editMode"] == "true"
                    assert fields["useDictionary"] == "false"
                elif method == "GetEngView":
                    assert fields["engParam1"] == fields["engParam2"] == "0"
                    assert fields["engParam3"] is None
                else:
                    typed = action.find("{" + NAV_NS + "}readRequest")
                    assert typed.attrib == {"useDictionary": "false"}
                    assert len(typed) == 1
                    assert typed[0].tag == "{" + NAV_NS + "}items"
                    assert typed[0][0].attrib == {
                        "reference": "Example:Engine",
                        "propertyList": "2390 32589 75",
                    }
                    assert len(typed[0]) == 1
                result = (
                    "<"
                    + method
                    + 'Response xmlns="'
                    + namespace
                    + '"><'
                    + method
                    + "Result/></"
                    + method
                    + "Response>"
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
        ("Integration/Integration.asmx", "WriteEngPropertyMultiple", INTEGRATION_NS),
        ("Item/Creation.asmx", "CreateItem", NAV_NS),
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


async def test_native_live_view_and_schema_reads_have_distinct_methods_and_canonical_booleans(link):
    native, peer = link
    await native.login(username="authored-user", password="authored & <password>")
    await native.navigation("Example:Engine", depth=2, extensions=True)
    await native.views("Example:Engine")
    await native.view("Example:Engine", 27, edit_mode=True)
    await native.engineering_view("Example:Engine")
    await native.read_properties("Example:Engine", [2390, 32589, 75])
    assert [
        fromstring(r.content).find("{" + SOAP + "}Body")[0].tag.rsplit("}", 1)[-1]
        for r in peer.requests
    ] == [
        "LoginOverSecureConnection",
        "GetNavView",
        "GetViewList",
        "GetView",
        "GetEngView",
        "ReadPropertyMultiple",
    ]


@pytest.mark.parametrize(
    "kind,args,kwargs",
    [
        ("navigation", ("Example:Engine",), {"depth": 3}),
        ("navigation", ("Example:Engine",), {"depth": True}),
        ("navigation", ("Example:Engine",), {"extensions": "true"}),
        ("views", ("",), {}),
        ("view", ("Example:Engine", True), {}),
        ("view", ("Example:Engine", 65536), {}),
        ("view", ("Example:Engine", 27), {"edit_mode": 1}),
        ("engineering_view", ("bad\rreference",), {}),
        ("read_properties", ("Example:Engine", []), {}),
        ("read_properties", ("Example:Engine", [True]), {}),
        ("read_properties", ("Example:Engine", [75, 75]), {}),
        ("read_properties", ("Example:Engine", [-1]), {}),
        ("read_properties", ("Example:Engine", [65536]), {}),
    ],
)
async def test_invalid_native_read_scope_is_rejected_before_dispatch(link, kind, args, kwargs):
    native, peer = link
    with pytest.raises(ValueError):
        await getattr(native, kind)(*args, **kwargs)
    assert not peer.requests
