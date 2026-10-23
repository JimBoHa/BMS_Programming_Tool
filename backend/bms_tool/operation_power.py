"""Bounded advisory idle-sleep requests owned by admitted operations."""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import json
import math
import os
import secrets
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

PROFILE = {
    "profile": "studio-operation-idle-awake/1",
    "advisory": True,
    "idle_only": True,
    "maximum_seconds": 1800,
    "temco_apply_seconds": 900,
    "active_limit": 8,
    "recent_limit": 32,
    "integrations": ["App-managed Temco native apply including owned recovery"],
    "scope": "This backend OS only; a guest request does not protect its VM host or remote computers.",
    "limits": [
        "No explicit Sleep, lid-close, shutdown, power-loss or policy guarantee.",
        "No display/user-activity/away-mode request or power-preference change.",
        "Expiry/failure never cancels, retries or authorizes controller operations.",
        "No automatic lease for UI, connections, plans, passive polling or idle simulators.",
        "Linux and other hosts remain unavailable until their exact provider is verified.",
    ],
}
PROFILE_SHA = hashlib.sha256(
    json.dumps(PROFILE, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


def utc():
    return datetime.now(UTC).isoformat()


class MacProvider:
    name = "macos-caffeinate-idle"

    def availability(self):
        return os.path.isfile("/usr/bin/caffeinate") and os.access("/usr/bin/caffeinate", os.X_OK)

    def open(self, seconds):
        child = subprocess.Popen(
            ["/usr/bin/caffeinate", "-i", "-t", str(seconds), "-w", str(os.getpid())],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )

        class OwnedChild:
            pid = child.pid

            def alive(self):
                return child.poll() is None

            def close(self):
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=1)
                else:
                    child.wait(timeout=1)

        return OwnedChild()


class WindowsProvider:
    name = "windows-thread-system-required"

    def availability(self):
        return sys.platform == "win32"

    def open(self, seconds):
        setter = ctypes.WinDLL("kernel32", use_last_error=True).SetThreadExecutionState
        setter.argtypes, setter.restype = [ctypes.c_uint], ctypes.c_uint
        if not setter(0x80000001):  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
            raise OSError("Windows idle request failed.")

        class OwnedThreadRequest:
            def alive(self):
                return True

            def close(self):
                if not setter(0x80000000):  # ES_CONTINUOUS, on this same owning thread
                    raise OSError("Windows idle request clear failed.")

        return OwnedThreadRequest()


class UnavailableProvider:
    name = "unavailable"

    def availability(self):
        return False


def platform_provider():
    if sys.platform == "darwin":
        return MacProvider()
    if sys.platform == "win32":
        return WindowsProvider()
    return UnavailableProvider()


class Lease:
    def __init__(self, kind, seconds, provider):
        self.lock = threading.RLock()
        self.stop, self.ready, self.done = threading.Event(), threading.Event(), threading.Event()
        self.thread = None
        self.row = {
            "id": secrets.token_hex(16),
            "operation": kind,
            "provider": provider,
            "seconds": seconds,
            "created_at": utc(),
            "expires_at": (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(),
            "finished_at": None,
            "state": "starting",
            "request_active": False,
            "cleanup_confirmed": False,
            "error": None,
        }

    def update(self, **values):
        with self.lock:
            self.row.update(values)

    def snapshot(self):
        with self.lock:
            return dict(self.row)


class OperationPower:
    """No assertions until an explicit operation; no cancellation of owners."""

    def __init__(self, provider=None):
        self.provider = provider if provider is not None else platform_provider()
        self.lock = threading.RLock()
        self.leases = OrderedDict()
        self.accepting = True

    def _available(self):
        try:
            return bool(self.provider.availability())
        except Exception:
            return False

    def status(self):
        with self.lock:
            completed = [
                k
                for k, v in self.leases.items()
                if v.done.is_set() and not v.snapshot()["request_active"]
            ]
            for key in completed[: -PROFILE["recent_limit"]]:
                del self.leases[key]
            rows = [lease.snapshot() for lease in self.leases.values()]
            return {
                "profile": PROFILE,
                "profile_sha256": PROFILE_SHA,
                "provider": self.provider.name,
                "provider_available": self._available(),
                "accepting": self.accepting,
                "active": [
                    r
                    for r in rows
                    if r["state"] in ("starting", "active", "releasing") or r["request_active"]
                ],
                "recent": [
                    r
                    for r in rows
                    if r["state"] not in ("starting", "active", "releasing")
                    and not r["request_active"]
                ],
                "native_jci_transfer": False,
            }

    def _run(self, lease, seconds):
        resource = None
        outcome = "released"
        deadline = time.monotonic() + seconds
        try:
            resource = self.provider.open(seconds)
            if not resource.alive():
                raise OSError("Owned idle request exited before admission.")
            lease.update(state="active", request_active=True)
            lease.ready.set()
            while not lease.stop.wait(min(0.1, max(0, deadline - time.monotonic()))):
                if time.monotonic() >= deadline:
                    outcome = "expired"
                    break
                if not resource.alive():
                    raise OSError("Owned idle request ended during the operation.")
        except Exception as exc:
            outcome = "failed"
            lease.update(error=str(exc)[:500] or type(exc).__name__)
        finally:
            lease.update(state="releasing")
            try:
                if resource is not None:
                    resource.close()
                lease.update(cleanup_confirmed=True, request_active=False)
            except Exception as exc:
                outcome = "cleanup_failed"
                lease.update(error=str(exc)[:500] or type(exc).__name__)
            lease.update(state=outcome, finished_at=utc())
            lease.ready.set()
            lease.done.set()

    def _start(self, kind, seconds):
        if kind != "temco-native-apply":
            raise ValueError("Power leases require an implemented operation kind.")
        if type(seconds) is not int or not 1 <= seconds <= PROFILE["maximum_seconds"]:
            raise ValueError("Power lease lifetime must be an integer in1..1800seconds.")
        with self.lock:
            while (
                len(
                    [
                        v
                        for v in self.leases.values()
                        if v.done.is_set() and not v.snapshot()["request_active"]
                    ]
                )
                >= 32
            ):
                key = next(
                    k
                    for k, v in self.leases.items()
                    if v.done.is_set() and not v.snapshot()["request_active"]
                )
                del self.leases[key]
            lease = Lease(kind, seconds, self.provider.name)
            active = sum(
                not v.done.is_set() or v.snapshot()["request_active"] for v in self.leases.values()
            )
            self.leases[lease.row["id"]] = lease
            reason = None
            if not self.accepting:
                reason = "Power manager is closing; no new request admitted."
            elif active >= PROFILE["active_limit"]:
                reason = "Concurrent idle-request limit reached."
            elif not self._available():
                reason = "Idle-request provider is unavailable or unverified on this host."
            if reason:
                lease.update(
                    state="unavailable", error=reason, finished_at=utc(), cleanup_confirmed=True
                )
                lease.ready.set()
                lease.done.set()
            else:
                # Each request owns its API thread. A leaked daemon must not
                # keep an exiting backend alive until the lifetime expires.
                lease.thread = threading.Thread(
                    target=self._run, args=(lease, seconds), daemon=True
                )
                try:
                    lease.thread.start()
                except Exception as exc:
                    lease.update(
                        state="failed",
                        error=str(exc)[:500],
                        finished_at=utc(),
                        cleanup_confirmed=True,
                    )
                    lease.ready.set()
                    lease.done.set()
            return lease

    @staticmethod
    async def _release(lease):
        lease.stop.set()
        # Repeated caller cancellation cannot abandon owned cleanup. This wait
        # itself is bounded, independent of the daemon's OS-request lifetime.
        task = asyncio.create_task(asyncio.to_thread(lease.done.wait, 3))
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError

    @asynccontextmanager
    async def operation(self, kind, seconds=900):
        lease = self._start(kind, seconds)
        try:
            admitted = await asyncio.to_thread(lease.ready.wait, 2)
            if not admitted:
                lease.update(
                    error="Idle-request admission timed out; operation remains unprotected."
                )
                lease.stop.set()
            yield lease
        finally:
            await self._release(lease)

    async def close(self, wait_seconds=0.1):
        """Stop admission; active operations still own their requests/recovery."""
        if (
            type(wait_seconds) not in (int, float)
            or not math.isfinite(wait_seconds)
            or not 0 <= wait_seconds <= 3
        ):
            raise ValueError("Power shutdown observation must be within0..3seconds.")
        with self.lock:
            self.accepting = False
        deadline = time.monotonic() + wait_seconds
        while self.status()["active"] and time.monotonic() < deadline:
            await asyncio.sleep(min(0.01, max(0, deadline - time.monotonic())))
        return {
            "admission_closed": True,
            "pending_active": self.status()["active"],
            "forced_release": False,
        }
