"""Authored HTTP peers; no credentials, vendor assets or site connections."""

import base64
import hashlib
import json
import ssl

import httpx
import pytest
from bms_tool.metasys_configuration_api import (
    MetasysApiError,
    MetasysConfigurationApi,
    origin,
    trusted_context,
)

BASE = "https://configuration.example"
OBJECT = "11111111-1111-4111-8111-111111111111"


class AccountPeer:
    def __init__(self):
        self.requests = []
        self.accepted = True
        self.authenticated = True
        self.change_password = False
        self.token = "test-session-token"
        self.response = httpx.Response(200, json={"item": {"id": OBJECT}})

    async def handle(self, request):
        self.requests.append(request)
        if request.url.path.endswith("/GetPreLoginState"):
            assert "Authorization" not in request.headers
            return httpx.Response(200, json={"IsAuthenticated": False})
        if request.url.path.endswith("/LogIn"):
            assert "Authorization" not in request.headers
            body = json.loads(request.content)
            assert body["username"] == "test-user" and body["password"] == "test-password"
            plain = f"^test-user|test-password|{body['timestamp']}$".encode()
            verifier = base64.b64decode(body["verifier"])
            expected = hashlib.sha256(
                bytes(a ^ b for a, b in zip(plain, verifier, strict=True))
            ).digest()
            assert base64.b64decode(body["challenge"]) == expected
            return httpx.Response(
                200,
                json={
                    "IsAuthenticated": self.authenticated,
                    "IsTermsAndConditionsAccepted": self.accepted,
                    "IsPasswordChangeRequired": self.change_password,
                    "access_token": self.token,
                },
            )
        assert request.headers["Authorization"] == "Bearer " + self.token
        return self.response


@pytest.fixture
async def api():
    peer = AccountPeer()
    client = httpx.AsyncClient(
        base_url=BASE, transport=httpx.MockTransport(peer.handle), follow_redirects=False
    )
    api = MetasysConfigurationApi(BASE, client)
    await api.login(username="test-user", password="test-password")
    try:
        yield api, peer
    finally:
        await api.close()


async def test_explicit_login_uses_an_accepted_session_without_exposing_credentials(api):
    client, peer = api
    assert len(peer.requests) == 2
    assert client.session_key["origin"] == BASE
    assert client.session_key["account"] == "test-user"
    assert "test-password" not in repr(client) and peer.token not in repr(client)
    old = client.session_key
    await client.login(username="test-user", password="test-password")
    assert client.session_key != old
    result = await client.object(OBJECT)
    assert result["item"]["id"] == OBJECT
    assert all(r.url.host == "configuration.example" for r in peer.requests)


@pytest.mark.parametrize("failure", ["terms", "password_change", "authentication", "bad_token"])
async def test_login_never_accepts_terms_changes_passwords_or_creates_auth_from_failure(
    api, failure
):
    client, peer = api
    if failure == "terms":
        peer.accepted = False
    elif failure == "password_change":
        peer.change_password = True
    elif failure == "authentication":
        peer.authenticated = False
    else:
        peer.token = "invalid\r\ntoken"
    with pytest.raises(MetasysApiError):
        await client.login(username="test-user", password="test-password")
    with pytest.raises(ValueError, match="Connect"):
        _ = client.session_key
    assert all(r.url.path.endswith(("/GetPreLoginState", "/LogIn")) for r in peer.requests)


@pytest.mark.parametrize(
    "value",
    [
        "http://configuration.example",
        "https://u:p@configuration.example",
        "https://configuration.example/path",
        "https://configuration.example?x=1",
        "https://configuration.example#fragment",
        "https://configuration.example:0",
        "https://configuration.example:99999",
        "https://configuration.example\\x",
        None,
    ],
)
def test_non_origin_or_untrusted_target_forms_are_rejected(value):
    with pytest.raises((ValueError, httpx.InvalidURL)):
        origin(value)


def test_only_the_explicit_certificate_is_used_as_a_trust_anchor(monkeypatch):
    pem = ssl.DER_cert_to_PEM_cert(b"authored certificate fixture")
    expected = hashlib.sha256(b"authored certificate fixture").hexdigest()
    created = []

    class Context:
        check_hostname = True
        verify_mode = ssl.CERT_REQUIRED

    def make_context(*, cadata):
        assert cadata == pem
        result = Context()
        created.append(result)
        return result

    monkeypatch.setattr(ssl, "create_default_context", make_context)
    with pytest.raises(ValueError, match="differs"):
        trusted_context(pem, "0" * 64)
    assert not created
    context = trusted_context(pem, expected)
    assert context.verify_mode == ssl.CERT_REQUIRED
    with pytest.raises(ValueError):
        trusted_context(pem, "not-a-pin")


@pytest.mark.parametrize(
    "url",
    [
        f"https://other.example/api/v6/objects/{OBJECT}",
        f"{BASE}/api/v6/objects/{OBJECT}?extra=1",
        f"{BASE}/api/v6/objects/{OBJECT}#extra",
        f"{BASE}/api/v6/users/{OBJECT}",
        f"{BASE}/api/v6/objects/../../{OBJECT}",
        f"{BASE}/api/v6/objects/00000000-0000-0000-0000-000000000000",
    ],
)
async def test_resources_cannot_change_origin_path_or_identity_scope(api, url):
    client, peer = api
    with pytest.raises(ValueError):
        client.resource_guid(url)
    assert len(peer.requests) == 2


@pytest.mark.parametrize(
    "raw", [b'{"item":1,"item":2}', b'{"x":NaN}', b'{"x":1e999}', b"[]", b"<html>error</html>"]
)
async def test_ambiguous_non_finite_or_non_object_responses_are_not_accepted(api, raw):
    client, peer = api
    peer.response = httpx.Response(200, content=raw)
    with pytest.raises(MetasysApiError):
        await client.tree_context(OBJECT)


async def test_response_budget_and_no_redirect_or_error_retry(api, monkeypatch):
    from bms_tool import metasys_configuration_api as module

    client, peer = api
    monkeypatch.setattr(module, "MAX_REPLY_BYTES", 16)
    peer.response = httpx.Response(200, content=b'{"body":"' + b"x" * 100 + b'"}')
    with pytest.raises(MetasysApiError, match="budget"):
        await client.tree_context(OBJECT)
    monkeypatch.setattr(module, "MAX_REPLY_BYTES", 1024)
    for code in [302, 400, 401, 403, 500]:
        peer.response = httpx.Response(
            code,
            headers={"Location": "https://other.example/"},
            json={"message": "never echo token or credential material"},
        )
        count = len(peer.requests)
        with pytest.raises(MetasysApiError) as result:
            await client.tree_context(OBJECT)
        assert result.value.http_status == code
        assert len(peer.requests) == count + 1
        assert "credential material" not in str(result.value)


async def test_wrong_native_identity_unknown_attribute_and_class_are_refused(api):
    client, peer = api
    peer.response = httpx.Response(
        200, json={"item": {"id": "22222222-2222-4222-8222-222222222222"}}
    )
    with pytest.raises(MetasysApiError, match="identity"):
        await client.object(OBJECT)
    before = len(peer.requests)
    with pytest.raises(ValueError):
        await client.attribute(OBJECT, "../password")
    with pytest.raises(ValueError):
        await client.creation_schema(OBJECT, "objectTypeEnumSet.programClass")
    with pytest.raises(ValueError):
        await client.enumeration("passwordPolicies")
    assert len(peer.requests) == before
