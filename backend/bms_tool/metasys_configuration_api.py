"""Bounded authenticated Metasys configuration reads and temporary test creation.

The v6 configuration resource contract is independent of field-controller CAF
transfers. Explicit coordinators prepare disposable monitoring mappings, qualify
source methods only on their owned test points and remove those empty test
objects. No production editor, value command, archive download or security
operation is exposed by this module.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import re
import secrets
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit
from uuid import UUID

import httpx

PROFILE = "metasys-configuration-api/1"
PREFIX = "/API/private-api"
MAX_REPLY_BYTES = 8 * 1024 * 1024
MONITOR_TYPES = {
    "objectTypeEnumSet.bacnetDeviceClass": "objectTypeEnumSet.bacnetDeviceClass",
    "objectTypeEnumSet.bacnetAiClass": "objectTypeEnumSet.bacAiClass",
    "objectTypeEnumSet.bacnetBvClass": "objectTypeEnumSet.bacBvClass",
}


class MetasysApiError(ValueError):
    def __init__(self, message, *, http_status=None, response_problem=None):
        super().__init__(message)
        self.http_status = http_status
        self.response_problem = response_problem


def guid(value):
    if type(value) is not str:
        raise ValueError("Use an explicit object GUID.")
    identifier = UUID(value)
    if not identifier.int:
        raise ValueError("A root/wildcard GUID is not an explicit object.")
    return str(identifier)


def origin(value):
    if type(value) is not str:
        raise ValueError("Use an explicit HTTPS configuration origin.")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or "\\" in value
    ):
        raise ValueError("Configuration origin must be HTTPS without credentials, path or query.")
    # Validate port syntax here, before any network operation.
    port = parsed.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Configuration service port is outside its range.")
    return str(httpx.URL(value)).rstrip("/")


def trusted_context(certificate_pem, expected_sha256):
    if type(expected_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("An explicitly trusted SHA-256 certificate fingerprint is required.")
    actual = hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate_pem)).hexdigest()
    if not secrets.compare_digest(actual, expected_sha256):
        raise ValueError("Configuration service certificate differs from the trusted fingerprint.")
    context = ssl.create_default_context(cadata=certificate_pem)
    # This trust profile deliberately binds a supplied certificate for the named
    # origin, including installations addressed by an IP absent from its SAN.
    # Certificate-chain/time validation stays enabled; no verify=False fallback.
    context.check_hostname = False
    return context


def _constant(_value):
    raise MetasysApiError("Non-finite JSON in configuration response.")


def _float(value):
    result = float(value)
    if not math.isfinite(result):
        raise MetasysApiError("Non-finite JSON in configuration response.")
    return result


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise MetasysApiError("Duplicate JSON key in configuration response.")
        result[key] = value
    return result


@dataclass(frozen=True)
class ApiReply:
    http_status: int
    data: dict
    location: str | None = None


class MetasysConfigurationApi:
    prefix = PREFIX
    referer_path = "/UI/"

    def __init__(self, server_origin, client):
        self.origin = origin(server_origin)
        if str(client.base_url).rstrip("/") != self.origin:
            raise ValueError("HTTP client origin differs from the selected configuration service.")
        self._client = client
        self._token = None
        self._session_key = None

    def __repr__(self):
        return f"MetasysConfigurationApi(authenticated={self._token is not None})"

    @classmethod
    async def connect(cls, server_origin, certificate_sha256, *, username, password):
        selected = origin(server_origin)
        parsed = urlsplit(selected)
        pem = await asyncio.to_thread(
            ssl.get_server_certificate, (parsed.hostname, parsed.port or 443), timeout=10
        )
        context = trusted_context(pem, certificate_sha256)
        client = httpx.AsyncClient(
            base_url=selected,
            verify=context,
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(20, connect=10),
        )
        result = cls(selected, client)
        try:
            await result.login(username=username, password=password)
        except BaseException:
            await client.aclose()
            raise
        return result

    async def close(self):
        self._token = None
        self._session_key = None
        await self._client.aclose()

    @property
    def session_key(self):
        if self._session_key is None:
            raise ValueError("Connect the configuration account explicitly first.")
        return {"origin": self.origin, "api_prefix": self.prefix, **self._session_key}

    def _admitted_path(self, method, path):
        return path.startswith(self.prefix + "/")

    async def _request(self, method, path, *, body=None, authenticated=True):
        if (
            not self._admitted_path(method, path)
            or ".." in path
            or "#" in path
            or "\\" in path
            or not path.isascii()
        ):
            raise ValueError("Unexpected configuration API path.")
        if authenticated and self._token is None:
            raise ValueError("Connect the configuration account explicitly first.")
        headers = {
            "Accept": "application/json",
            "Origin": self.origin,
            "Referer": self.origin + self.referer_path,
        }
        if authenticated:
            headers["Authorization"] = "Bearer " + self._token
        if body is not None:
            headers["Content-Type"] = "application/json"
        raw_body = json.dumps(body, allow_nan=False).encode() if body is not None else None
        async with self._client.stream(method, path, headers=headers, content=raw_body) as reply:
            raw = bytearray()
            async for block in reply.aiter_bytes(chunk_size=65536):
                if len(raw) + len(block) > MAX_REPLY_BYTES:
                    raise MetasysApiError(
                        "Configuration response exceeded its byte budget.",
                        http_status=reply.status_code,
                    )
                raw.extend(block)
            # A write response failure or a lost reply does not establish that a
            # mutation was rejected. Its caller must retain intent and reconcile.
            if not 200 <= reply.status_code < 300:
                problem = None
                # An isolated configuration experiment can retain the server's
                # refusal for diagnosis. Authentication payloads and replies are
                # excluded, and this text is never part of the exception string.
                if authenticated and method == "PATCH" and len(raw) <= 4096:
                    try:
                        problem = json.loads(
                            raw,
                            object_pairs_hook=_pairs,
                            parse_constant=_constant,
                            parse_float=_float,
                        )
                    except (ValueError, UnicodeError, RecursionError):
                        pass
                raise MetasysApiError(
                    f"Configuration service returned HTTP {reply.status_code}.",
                    http_status=reply.status_code,
                    response_problem=problem,
                )
            try:
                data = (
                    json.loads(
                        raw, parse_constant=_constant, parse_float=_float, object_pairs_hook=_pairs
                    )
                    if raw
                    else {}
                )
            except (ValueError, UnicodeError, RecursionError) as exc:
                raise MetasysApiError("Configuration response was not valid bounded JSON.") from exc
            if type(data) is not dict:
                raise MetasysApiError("Configuration response did not contain an object.")
            return ApiReply(reply.status_code, data, reply.headers.get("Location"))

    async def login(self, *, username, password):
        self._token = None
        self._session_key = None
        if (
            type(username) is not str
            or not 1 <= len(username) <= 200
            or type(password) is not str
            or not 1 <= len(password) <= 1000
            or any(c in username + password for c in "\x00\r\n")
        ):
            raise ValueError("Explicit existing configuration credentials are required.")
        await self._request(
            "GET", self.prefix + "/Authentication/GetPreLoginState", authenticated=False
        )
        timestamp = int(time.time() * 1000)
        plain = f"^{username}|{password}|{timestamp}$".encode()
        verifier = secrets.token_bytes(len(plain))
        challenge = hashlib.sha256(
            bytes(a ^ b for a, b in zip(plain, verifier, strict=True))
        ).digest()
        response = await self._request(
            "POST",
            self.prefix + "/Authentication/LogIn",
            authenticated=False,
            body={
                "username": username,
                "password": password,
                "domain": "",
                "timestamp": timestamp,
                "challenge": base64.b64encode(challenge).decode(),
                "verifier": base64.b64encode(verifier).decode(),
            },
        )
        data = response.data
        if (
            data.get("IsAuthenticated") is not True
            or data.get("IsTermsAndConditionsAccepted") is not True
            or data.get("IsPasswordChangeRequired") is True
            or type(data.get("access_token")) is not str
            or not re.fullmatch(r"[A-Za-z0-9._~+/-]{1,16384}=*", data["access_token"])
        ):
            raise MetasysApiError(
                "Configuration login did not establish an existing accepted session."
            )
        self._token = data["access_token"]
        self._session_key = {"account": username, "generation": secrets.token_hex(16)}

    def resource_guid(self, url, collection="objects"):
        if collection not in ("objects", "networkDevices"):
            raise ValueError("Unexpected configuration resource collection.")
        if type(url) is not str:
            raise ValueError("Missing configuration resource URL.")
        parsed = urlsplit(url)
        if (
            origin(f"{parsed.scheme}://{parsed.netloc}") != self.origin
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Configuration resource changed origin or includes a query.")
        match = re.fullmatch(
            r"/api/(?:private-api/)?v6/" + collection + r"/([0-9a-f-]{36})",
            parsed.path,
            re.IGNORECASE,
        )
        if not match:
            raise ValueError("Unexpected configuration resource path.")
        return guid(match[1])

    async def object(self, object_id, *, view=None):
        identifier = guid(object_id)
        query = {"includeSchema": "true"}
        if view is not None:
            if not re.fullmatch(r"viewNameEnumSet\.[A-Za-z]+View", view):
                raise ValueError("Unexpected object view.")
            query["viewId"] = view
        result = await self._request(
            "GET", self.prefix + "/v6/objects/" + identifier + "?" + urlencode(query)
        )
        if guid(result.data.get("item", {}).get("id")) != identifier:
            raise MetasysApiError("Configuration object identity differs from the requested GUID.")
        return result.data

    async def network_device(self, device_id):
        identifier = guid(device_id)
        reply = await self._request("GET", self.prefix + "/v6/networkDevices/" + identifier)
        if guid(reply.data.get("id")) != identifier:
            raise MetasysApiError("Network-device metadata returned a different identity.")
        return reply.data

    async def tree_context(self, object_id):
        identifier = guid(object_id)
        return (
            await self._request(
                "GET",
                self.prefix
                + "/v6/objects?"
                + urlencode({"pathTo": identifier, "includeEffectivePermissions": "true"}),
            )
        ).data

    async def children(self, object_id):
        identifier = guid(object_id)
        return (
            await self._request(
                "GET",
                self.prefix
                + "/v6/objects/"
                + identifier
                + "/objects?"
                + urlencode({"depth": 1, "flatten": "true", "includeExtensions": "true"}),
            )
        ).data

    async def creation_schema(self, parent_id, object_type):
        if object_type not in MONITOR_TYPES:
            raise ValueError("This profile admits explicit BACnet monitoring mapper classes only.")
        reply = await self._request(
            "GET",
            self.prefix
            + "/v6/schemas/objectTypes/"
            + object_type
            + "?"
            + urlencode({"parentId": guid(parent_id)}),
        )
        if type(reply.data.get("schema")) is not dict:
            raise MetasysApiError("Creation schema was not supplied.")
        return reply.data

    async def attribute(self, object_id, name):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,79}", name):
            raise ValueError("Unexpected configuration attribute name.")
        return (
            await self._request(
                "GET",
                self.prefix
                + "/v6/objects/"
                + guid(object_id)
                + "/attributes/"
                + name
                + "?includeSchema=true",
            )
        ).data

    async def enumeration(self, name, *, configuration_categories=False):
        if name not in ("timeSyncChoiceEnumSet", "objectCategoryEnumSet"):
            raise ValueError("Unexpected monitoring configuration enumeration.")
        if configuration_categories and name != "objectCategoryEnumSet":
            raise ValueError("Category permission filter requires the category enumeration.")
        suffix = "?permission=modifyConfigItems" if configuration_categories else ""
        return (await self._request("GET", self.prefix + "/v6/schemas/enums/" + name + suffix)).data
