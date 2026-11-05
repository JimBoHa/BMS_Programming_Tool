"""Opt-in, subnet-restricted authenticated gateway to an existing local editor.

The editor remains loopback-only. Addresses and access codes are private runtime
configuration, never release defaults. HTTP forwarding makes one attempt only.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import ipaddress
import json
import os
import secrets
import socket
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from starlette.background import BackgroundTask

from .file_access import open_regular

HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
MAX_BODY = 9 * 1024 * 1024


@dataclass(frozen=True)
class LANConfig:
    host: str
    port: int
    networks: tuple
    code: bytes

    @classmethod
    def load(cls, path):
        try:
            document = json.loads(Path(path).read_text())
            if (
                set(document) != {"profile", "host", "port", "allowed_networks", "access_code_file"}
                or document["profile"] != "bms-studio-lan/1"
            ):
                raise ValueError
            host = ipaddress.IPv4Address(document["host"])
            if host.is_unspecified or host.is_multicast:
                raise ValueError
            port = document["port"]
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError
            networks = tuple(
                ipaddress.IPv4Network(n, strict=True) for n in document["allowed_networks"]
            )
            if not networks or len(networks) > 16 or any(n.prefixlen == 0 for n in networks):
                raise ValueError
            descriptor = open_regular(Path(document["access_code_file"]))
            try:
                if os.name != "nt" and os.fstat(descriptor).st_mode & 0o077:
                    raise ValueError
                code = os.read(descriptor, 513).strip()
            finally:
                os.close(descriptor)
            if not 24 <= len(code) <= 256 or any(c < 33 or c > 126 for c in code):
                raise ValueError
            return cls(str(host), port, networks, code)
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError(
                "Invalid private LAN configuration or access-code file; values withheld."
            ) from None

    @property
    def url(self):
        return f"http://{self.host}:{self.port}"

    def refusal(self, request):
        try:
            peer = ipaddress.IPv4Address(request.client.host)
        except (ValueError, AttributeError):
            return PlainTextResponse("Client network is not allowed.", 403)
        if not any(peer in network for network in self.networks):
            return PlainTextResponse("Client network is not allowed.", 403)
        if request.headers.get("host") != f"{self.host}:{self.port}":
            return PlainTextResponse("Use the configured LAN address and port.", 403)
        origin = request.headers.get("origin")
        if origin and origin != self.url:
            return PlainTextResponse("Cross-origin requests are forbidden.", 403)
        try:
            scheme, value = request.headers.get("authorization", "").split(" ", 1)
            credentials = base64.b64decode(value, validate=True)
            valid = scheme.lower() == "basic" and secrets.compare_digest(
                credentials, b"operator:" + self.code
            )
        except (ValueError, binascii.Error):
            valid = False
        if not valid:
            return PlainTextResponse(
                "Sign in as operator with the private LAN access code.",
                401,
                headers={
                    "WWW-Authenticate": 'Basic realm="BMS Studio LAN", charset="UTF-8"',
                    "Cache-Control": "no-store",
                },
            )
        return None


def create_gateway(config, upstream):
    parts = urlsplit(upstream)
    if (
        parts.scheme != "http"
        or parts.hostname != "127.0.0.1"
        or not parts.port
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
        or parts.username
    ):
        raise ValueError("The LAN gateway upstream must be one loopback editor URL.")
    upstream = f"http://127.0.0.1:{parts.port}"

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(310, connect=5, pool=5),
            transport=httpx.AsyncHTTPTransport(retries=0),
        ) as client:
            app.state.client = client
            yield

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.middleware("http")
    async def restrict(request, call_next):
        refusal = config.refusal(request)
        if refusal is not None:
            return refusal
        response = await call_next(request)
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.api_route(
        "/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    )
    async def forward(request: Request, path: str):
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_BODY:
                return PlainTextResponse("Request exceeds 9 MiB.", 413)
            body.extend(chunk)
        # The public origin has already been checked. Present only the local
        # editor's exact host/origin to its unchanged loopback/CSRF admission.
        excluded = HOP_HEADERS | {"host", "origin", "authorization", "forwarded", "content-length"}
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in excluded and not k.lower().startswith("x-forwarded-")
        }
        headers["host"] = f"127.0.0.1:{parts.port}"
        if request.headers.get("origin"):
            headers["origin"] = upstream
        target = upstream + request.scope["raw_path"].decode("ascii")
        if request.url.query:
            target += "?" + request.url.query
        client = request.app.state.client
        try:
            response = await client.send(
                client.build_request(request.method, target, headers=headers, content=bytes(body)),
                stream=True,
            )
        except httpx.HTTPError:
            return PlainTextResponse(
                "The local editor response is unavailable. For a pending field change, inspect Changes and read back before any retry.",
                502,
            )
        outgoing = {k: v for k, v in response.headers.items() if k.lower() not in HOP_HEADERS}
        return StreamingResponse(
            response.aiter_raw(),
            status_code=response.status_code,
            headers=outgoing,
            background=BackgroundTask(response.aclose),
        )

    return app


class LANServer:
    """Own a separately bound gateway for the desktop owner's lifetime."""

    def __init__(self, config, upstream):
        self.config, self.upstream = config, upstream
        self.socket = self.server = self.thread = None

    def start(self):
        import uvicorn

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == "nt":
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.config.host, self.config.port))
            self.socket.listen(128)
            self.server = uvicorn.Server(
                uvicorn.Config(
                    create_gateway(self.config, self.upstream),
                    proxy_headers=False,
                    access_log=False,
                    log_config=None,
                    loop="asyncio",
                    http="h11",
                    ws="none",
                    timeout_graceful_shutdown=30,
                )
            )
            self.thread = threading.Thread(
                target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True
            )
            self.thread.start()
            deadline = time.monotonic() + 10
            while not self.server.started:
                if not self.thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("The authenticated LAN listener did not become ready.")
                time.sleep(0.05)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.server is not None:
            self.server.should_exit = True
        if self.thread is not None:
            self.thread.join(timeout=35)
            if self.thread.is_alive():
                raise RuntimeError("The LAN listener is still finishing shutdown.")
        if self.socket is not None:
            self.socket.close()
            self.socket = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--upstream", required=True)
    args = parser.parse_args()
    config = LANConfig.load(args.config)
    import uvicorn

    uvicorn.run(
        create_gateway(config, args.upstream),
        host=config.host,
        port=config.port,
        proxy_headers=False,
        access_log=False,
        loop="asyncio",
        http="h11",
        ws="none",
    )


if __name__ == "__main__":
    main()
