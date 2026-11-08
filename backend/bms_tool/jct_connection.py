"""Browser-owned volatile JCT connections and bounded archive metadata routes."""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from fastapi import APIRouter, Request
from pydantic import Field, SecretStr, ValidationError

from .jct_configuration import PROFILE, JctConfigurationApi, inspection_projection
from .metasys_configuration_api import MetasysApiError, _pairs, origin
from .models import StrictModel

IDLE_SECONDS = 1200


class ConnectRequest(StrictModel):
    server_origin: str = Field(min_length=1, max_length=512, strict=True)
    certificate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)
    username: str = Field(min_length=1, max_length=200, strict=True)
    password: SecretStr


class OwnedRequest(StrictModel):
    connection_id: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$", strict=True)


class ArchiveRequest(OwnedRequest):
    archive: str = Field(min_length=1, max_length=128, strict=True)


class ObjectRequest(ArchiveRequest):
    object_id: str = Field(min_length=36, max_length=36, strict=True)


@dataclass
class Entry:
    api: JctConfigurationApi
    version: dict
    used: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class JctConnections:
    def __init__(self, *, connector=None, directory=None):
        self.connector = connector or JctConfigurationApi.connect
        self.directory = directory
        self.entries = {}
        self.pending = 0
        self.closed = False

    def service_hint(self):
        """A local operator may supply a previously trusted origin, never credentials."""
        if self.directory is None:
            return {}
        path = Path(self.directory) / "jct-service-profile.json"
        if not path.exists() or path.stat().st_size > 4096:
            return {}
        try:
            data = json.loads(path.read_text(), object_pairs_hook=_pairs)
            request = ConnectRequest(**data, username="profile-validation", password="unused")
            return {
                "server_origin": origin(request.server_origin),
                "certificate_sha256": request.certificate_sha256,
            }
        except (ValueError, OSError, TypeError):
            return {}

    async def _expire(self):
        for key, entry in list(self.entries.items()):
            if time.monotonic() - entry.used > IDLE_SECONDS:
                self.entries.pop(key, None)
                await entry.api.close()

    async def connect(self, request):
        if self.closed:
            raise ValueError("The JCT connection service is closed.")
        await self._expire()
        if len(self.entries) + self.pending >= 4:
            raise ValueError("Close an existing JCT connection before opening another.")
        self.pending += 1
        api = None
        try:
            async with asyncio.timeout(45):
                api = await self.connector(
                    request.server_origin,
                    request.certificate_sha256,
                    username=request.username,
                    password=request.password.get_secret_value(),
                )
                if api.prefix != JctConfigurationApi.prefix:
                    raise ValueError(
                        "The connection did not establish the configuration API profile."
                    )
                version = await api.tool_version()
            if self.closed:
                raise ValueError("The JCT connection service closed during sign-in.")
            key = secrets.token_urlsafe(24)
            self.entries[key] = Entry(api, version, time.monotonic())
            return {"connection_id": key, **self._status(self.entries[key])}
        except BaseException:
            if api is not None:
                await api.close()
            raise
        finally:
            self.pending -= 1

    @staticmethod
    def _status(entry):
        return {
            "profile": PROFILE,
            "connected": True,
            "account": entry.api.session_key["account"],
            "server_origin": entry.api.origin,
            "tool_version": entry.version,
            "read_only": True,
            "archive_edit_available": False,
            "device_transfer_available": False,
            "idle_expiry_seconds": IDLE_SECONDS,
        }

    async def operate(self, key, operation):
        await self._expire()
        entry = self.entries.get(key)
        if entry is None:
            raise ValueError("The JCT connection is unavailable or expired. Sign in again.")
        async with asyncio.timeout(30):
            async with entry.lock:
                if self.entries.get(key) is not entry:
                    raise ValueError("The JCT connection ended. Repeat the read after signing in.")
                before = entry.api.session_key
                try:
                    result = await operation(entry.api)
                except MetasysApiError as exc:
                    if exc.http_status == 401:
                        self.entries.pop(key, None)
                        await entry.api.close()
                    raise
                if self.entries.get(key) is not entry or before != entry.api.session_key:
                    raise ValueError("The JCT connection changed during this read.")
                entry.used = time.monotonic()
                return result

    async def disconnect(self, key):
        entry = self.entries.pop(key, None)
        if entry is not None:
            await entry.api.close()
        return {"connected": False}

    async def status(self, key):
        await self._expire()
        entry = self.entries.get(key)
        return self._status(entry) if entry is not None else {"connected": False}

    async def close(self):
        self.closed = True
        entries = list(self.entries.values())
        self.entries.clear()
        await asyncio.gather(*(entry.api.close() for entry in entries), return_exceptions=True)


async def body(request, model):
    # Parse manually so FastAPI/Pydantic never echoes an invalid password or an
    # entire credential request in its default validation-error response.
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 8192:
            raise ValueError("Configuration connection request exceeds its limit.")
        raw.extend(chunk)
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
        if type(value) is not dict:
            raise ValueError
        return model(**value)
    except (ValueError, TypeError, ValidationError, UnicodeError, RecursionError):
        raise ValueError(
            "Invalid configuration connection fields. Credential values were withheld."
        ) from None


def jct_router(connections):
    router = APIRouter(prefix="/api/jct")

    @router.get("/profile")
    async def profile():
        return {
            "profile": PROFILE,
            "service_hint": connections.service_hint(),
            "connected": False,
            "scope": "Separate JCT archive metadata connection; no archive edits or field transfers.",
        }

    @router.post("/connect")
    async def connect(request: Request):
        fields = await body(request, ConnectRequest)
        try:
            return await connections.connect(fields)
        except MetasysApiError as exc:
            raise ValueError(
                "JCT configuration sign-in was not accepted"
                + (f" (HTTP {exc.http_status})" if exc.http_status else "")
                + ". Use a configuration account with already accepted terms."
            ) from None
        except httpx.HTTPError:
            raise ValueError("The JCT configuration service could not complete sign-in.") from None

    @router.post("/disconnect")
    async def disconnect(request: Request):
        fields = await body(request, OwnedRequest)
        return await connections.disconnect(fields.connection_id)

    @router.post("/status")
    async def status(request: Request):
        fields = await body(request, OwnedRequest)
        return await connections.status(fields.connection_id)

    @router.post("/archives")
    async def archives(request: Request):
        fields = await body(request, OwnedRequest)
        return await connections.operate(fields.connection_id, lambda api: api.archives())

    @router.post("/archive/devices")
    async def devices(request: Request):
        fields = await body(request, ArchiveRequest)
        return await connections.operate(
            fields.connection_id, lambda api: api.network_devices(fields.archive)
        )

    @router.post("/archive/object")
    async def object_configuration(request: Request):
        fields = await body(request, ObjectRequest)
        result = await connections.operate(
            fields.connection_id, lambda api: api.archive_object(fields.archive, fields.object_id)
        )
        return inspection_projection(result)

    return router
