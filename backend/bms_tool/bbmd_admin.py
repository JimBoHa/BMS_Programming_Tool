"""Explicit reviewed IPv4 BBMD writes with durable intent and observed outcomes.

BVLC has no invocation identity or compare-and-swap. These operations report
observed states, never write authorship, lease generations or atomic replacement.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import ipaddress
import secrets
import sqlite3
import struct
import time
from datetime import UTC, datetime, timedelta
from typing import Literal

from bacpypes3.ipv4.service import BIPForeign, BIPNormal
from bacpypes3.pdu import PDU, IPv4Address
from pydantic import Field, field_validator, model_validator

from .bbmd_admin_store import MAX_RECORDS, BbmdAdminStore, encoded
from .bbmd_tables import SEND_GAP, TABLES, _endpoint, _raw, _utc, decode_table
from .models import StrictModel
from .scoped_hooks import ScopedAttribute

PROFILE = "reviewed-bbmd-administration/1"
PLAN_SECONDS = 60
MAX_PLANS = 16
LOCK_WAIT = 3
APPLY_SECONDS = 20
SCOPE = (
    "Explicit plain IPv4 Write-BDT replacement or targeted Delete-FDT only. "
    "Results and readbacks have no transaction identity: desired-state observation is not proven authorship, atomic CAS or permanent removal. "
    "A concurrent edit can race the last read and write; identical FDT address/TTL does not prove lease-generation identity. "
    "No automatic retry, rollback, registration change, BBMD hosting or BACnet/SC."
)


class BdtEntry(StrictModel):
    ip: str = Field(min_length=7, max_length=15)
    port: int = Field(ge=0, le=65535, strict=True)
    mask: str = Field(min_length=7, max_length=15)

    @field_validator("ip", "mask")
    @classmethod
    def native_ipv4(cls, value):
        return str(ipaddress.IPv4Address(value))


class BbmdAdminPreview(StrictModel):
    endpoint: str = Field(min_length=7, max_length=32)
    operation: Literal["write-bdt", "delete-fdt"]
    rows: list[BdtEntry] | None = Field(default=None, max_length=256)
    delete_target: str | None = Field(default=None, min_length=7, max_length=32)
    timeout_seconds: float = Field(default=2.0, ge=0.1, le=3.0, strict=True)

    @field_validator("endpoint")
    @classmethod
    def literal_endpoint(cls, value):
        return _endpoint(value)

    @field_validator("delete_target")
    @classmethod
    def native_lease_endpoint(cls, value):
        if value is None:
            return None
        parts = value.split(":")
        if (
            len(parts) != 2
            or not parts[1].isascii()
            or not parts[1].isdigit()
            or not 0 <= int(parts[1]) <= 65535
        ):
            raise ValueError(
                "FDT target requires its exact native IPv4:port, including port0 if advertised."
            )
        return f"{ipaddress.IPv4Address(parts[0])}:{int(parts[1])}"

    @model_validator(mode="after")
    def distinct_operation(self):
        if self.operation == "write-bdt" and self.delete_target is not None:
            raise ValueError("BDT replacement cannot include an FDT deletion target.")
        if self.operation == "delete-fdt" and (self.delete_target is None or self.rows is not None):
            raise ValueError("FDT deletion requires exactly one target, without BDT rows.")
        return self


class BbmdAdminApply(StrictModel):
    id: str = Field(min_length=29, max_length=29)
    apply_token: str = Field(min_length=32, max_length=64)
    review_hash: str = Field(min_length=64, max_length=64)
    acknowledge_limits: bool = Field(strict=True)

    @field_validator("acknowledge_limits")
    @classmethod
    def explicit_acknowledgement(cls, value):
        if not value:
            raise ValueError(
                "Acknowledge the exact replacement/deletion and protocol limits before Apply."
            )
        return value


class BbmdAdminRestore(StrictModel):
    id: str = Field(min_length=29, max_length=29)
    timeout_seconds: float = Field(default=2.0, ge=0.1, le=3.0, strict=True)


def _frame(function, payload=b""):
    return bytes([0x81, function]) + struct.pack(">H", len(payload) + 4) + payload


def _bdt_payload(rows):
    return b"".join(
        ipaddress.IPv4Address(row["ip"]).packed
        + struct.pack(">H", row["port"])
        + ipaddress.IPv4Address(row["mask"]).packed
        for row in rows
    )


def _fdt_identity(rows):
    # Remaining lease naturally changes. This is a membership/TTL guard, not a
    # version or proof that the same registration generation still exists.
    return [(row["address"], row["ttl_seconds"]) for row in rows]


async def _owned_disk(function, *arguments):
    operation = asyncio.create_task(
        asyncio.to_thread(function, *arguments), name="bbmd-evidence-writer"
    )
    cancelled = False
    while True:
        try:
            await asyncio.shield(operation)
            break
        except asyncio.CancelledError:
            cancelled = True
            if operation.done():
                break
        except Exception:
            if not cancelled:
                raise
            break
    if cancelled:
        if not operation.cancelled():
            operation.exception()  # retrieve an eventual storage exception
        raise asyncio.CancelledError
    return operation.result()


class _Session:
    def __init__(self, owner, app, config, layer, binding, target, timeout, receipt):
        self.owner, self.app, self.config, self.layer, self.binding = (
            owner,
            app,
            config,
            layer,
            binding,
        )
        self.target, self.timeout, self.receipt = target, timeout, receipt
        self.pending = None
        self.mode = None
        self.hook = None
        self.listening = False

    def guard(self):
        self.owner._guard(
            self.app,
            self.config,
            self.layer,
            self.binding,
            mux_observer=self.hook.replacement if self.hook else None,
        )

    async def __aenter__(self):
        self.guard()
        original = self.layer.multiplexer.confirmation

        async def unrelated(packet):
            # Preserve genuine observers, but do not dispatch rejected management
            # frames to the default normal link's unbound BVLC service endpoint.
            data = bytes(packet.pduData)
            if (
                len(data) >= 2
                and data[0] == 0x81
                and data[1] in (0, 3, 7)
                and self.layer.serviceElement is None
                and not self.hook.existed
                and getattr(self.layer.confirmation, "__func__", None) is BIPNormal.confirmation
            ):
                return
            return await original(packet)

        async def observe(packet):
            if not self.listening:
                return await unrelated(packet)
            data = bytes(packet.pduData)
            if len(data) < 2 or data[0] != 0x81 or data[1] not in (0, 3, 7):
                return await unrelated(packet)
            if (
                not isinstance(packet.pduSource, IPv4Address)
                or packet.pduSource.addrTuple != self.target.addrTuple
                or not isinstance(packet.pduDestination, IPv4Address)
                or packet.pduDestination.addrTuple != self.binding[2]
            ):
                self.receipt["ignored_peers"] += 1
                return await unrelated(packet)
            try:
                self.guard()
            except ValueError as exc:
                if self.pending is not None and not self.pending.done():
                    self.pending.set_result({"state": "ownership_lost", "reason": str(exc)})
                return await unrelated(packet)
            evidence = _raw(data, self.receipt["endpoint"])
            if data[1] == 0:
                valid = len(data) == 6 and int.from_bytes(data[2:4], "big") == 6
                code = int.from_bytes(data[4:6], "big") if valid else None
                observed = evidence | {
                    "result_code": code,
                    "phase": self.mode,
                    "authorship_proven": False,
                }
                counter = {
                    0: "success",
                    0x10: "write_bdt_nack",
                    0x20: "read_bdt_nack",
                    0x30: "register_foreign_nack",
                    0x40: "read_fdt_nack",
                    0x50: "delete_fdt_nack",
                    0x60: "distribute_broadcast_nack",
                }.get(code, "other" if valid else "malformed")
                self.receipt["result_counts"][counter] += 1
                if code in (0x10, 0x50):
                    # Separate fixed-size evidence survives a flood that fills
                    # the generic Result list; it still has no invocation ID.
                    self.receipt["native_admin_nack_observed"] = True
                    self.receipt["last_native_admin_nack"] = observed
                if len(self.receipt["results_observed"]) < 8:
                    self.receipt["results_observed"].append(observed)
                else:
                    self.receipt["results_omitted"] += 1
                expected = {"write-bdt": 0x10, "delete-fdt": 0x50}.get(self.mode)
                if self.mode in ("bdt", "fdt"):
                    expected = TABLES[self.mode][2]
                if (
                    self.pending is not None
                    and not self.pending.done()
                    and valid
                    and (code == expected or self.mode in ("write-bdt", "delete-fdt") and code == 0)
                ):
                    self.pending.set_result(
                        {
                            "state": "native_result_observed",
                            "result_code": code,
                            "result_hex": f"0x{code:04x}",
                            "response": evidence,
                            "authorship_proven": False,
                        }
                    )
                elif len(self.receipt["unattributed_results"]) < 8:
                    self.receipt["unattributed_results"].append(evidence | {"result_code": code})
                else:
                    self.receipt["unattributed_results_omitted"] += 1
                # This plain-IP profile refuses native/custom BVLC owners.
                # Results remain evidence; none proves authorship or completion.
                return
            if self.pending is None or self.pending.done():
                return await unrelated(packet)
            if self.mode not in ("bdt", "fdt") or data[1] != TABLES[self.mode][1]:
                return await unrelated(packet)
            try:
                result = {"state": "ok", "rows": decode_table(data, self.mode)}
            except (ValueError, OverflowError) as exc:
                result = {"state": "invalid", "reason": str(exc), "rows": []}
            self.pending.set_result(result | {"response": evidence})

        self.hook = ScopedAttribute(self.layer.multiplexer, "confirmation", observe)
        self.listening = True
        return self

    async def __aexit__(self, *unused):
        self.listening = False
        if self.pending is not None and not self.pending.done():
            self.pending.cancel()
        self.pending = None
        self.hook.close()

    async def exchange(self, mode, wire, *, expires=None):
        self.guard()
        await asyncio.sleep(max(0, SEND_GAP - (time.monotonic() - self.owner.network.last_send)))
        self.guard()
        if expires is not None and self.owner.clock() >= expires:
            raise ValueError("Reviewed Apply expired before dispatch; create a fresh preview.")
        self.mode = mode
        self.pending = asyncio.get_running_loop().create_future()
        request = {"mode": mode, "wire_hex": wire.hex(), "sent_at": _utc()}
        self.receipt["requests"].append(request)
        self.owner.network.last_send = time.monotonic()
        if mode in ("write-bdt", "delete-fdt"):
            self.receipt["local_send_entered"] = True
        await self.layer.multiplexer.request(PDU(wire, destination=self.target))
        request["dispatch_returned_at"] = _utc()
        deadline = time.monotonic() + self.timeout
        while not self.pending.done() and time.monotonic() < deadline:
            self.guard()
            await asyncio.wait(
                {self.pending}, timeout=min(0.05, max(0, deadline - time.monotonic()))
            )
        self.guard()
        result = (
            self.pending.result()
            if self.pending.done()
            else {"state": "timeout", "reason": "No attributable response before deadline."}
        )
        if not self.pending.done():
            self.pending.cancel()
        if result["state"] == "ownership_lost":
            raise ValueError(result["reason"])
        self.pending = None
        return result

    async def read(self, table):
        result = await self.exchange(table, _frame(TABLES[table][0]))
        if result["state"] != "ok":
            self.receipt["read_failures"].append({"table": table, **result})
            raise ValueError(
                "Fresh "
                + table.upper()
                + " read failed: "
                + result["state"]
                + "; inspect read_failures evidence."
            )
        return result


class BbmdAdmin:
    def __init__(self, bacnet, network, directory, *, clock=None):
        self.bacnet, self.network = bacnet, network
        self.journal = BbmdAdminStore(directory)
        self.clock = clock or time.monotonic
        self.plans, self.runtime, self.tasks = {}, {}, {}
        self.operations = set()
        self.ownership = None
        self.gate = asyncio.Lock()
        self.closed = False
        try:
            probe = self.journal.claim()
        except ValueError:
            pass
        else:
            try:
                self._recover()
            finally:
                probe.close()

    def _recover(self):
        for identifier in self.journal.ids():
            receipt = self.journal.get(identifier)
            if receipt.get("active"):
                receipt.update(
                    active=False,
                    state="interrupted",
                    outcome="unknown" if receipt.get("dispatch_possible") else "not-dispatched",
                    reason="Previous process ended; no action or verification is resumed automatically.",
                    apply_available=False,
                )
                self.journal.save(receipt)

    async def _claim(self):
        if self.closed:
            raise ValueError("BBMD administration is closed.")
        if self.ownership is None:
            self.ownership = self.journal.claim()
            await _owned_disk(self._recover)

    def _guard(self, app, config, layer, binding=None, *, mux_observer=None):
        if self.closed:
            raise ValueError("BBMD administration is closed.")
        self.network._guard(app, config, layer, binding)
        if isinstance(layer, BIPForeign) or getattr(app, "foreign_link", None) is not None:
            raise ValueError(
                "BBMD administration requires a plain IPv4 interface; active foreign registration is refused."
            )
        if layer.serviceElement is not None:
            raise ValueError(
                "A native BVLC owner is bound; administration is refused without interrupting it."
            )
        if "confirmation" in layer.__dict__ or (
            "confirmation" in layer.multiplexer.__dict__
            and layer.multiplexer.__dict__["confirmation"] is not mux_observer
        ):
            raise ValueError(
                "A custom BVLC management observer owns this interface; administration is refused without replacing it."
            )

    def _source(self, endpoint):
        app, config, layer = self.network._interface()
        self._guard(app, config, layer)
        target = IPv4Address(endpoint)
        own = layer.server.local_transport.get_extra_info("sockname")
        if target.addrTuple == own:
            raise ValueError("Select a remote BBMD endpoint, not this client's own socket.")
        # Reuse read-only validation, including known local broadcast refusal,
        # without starting a query or changing interface/registration settings.
        from .ip_discovery import _bound_network

        try:
            network, _ = _bound_network(app.nsap.local_adapter.adapterAddr, strict_prefix=False)
        except ValueError:
            network = None
        if (
            network is not None
            and network.prefixlen < 31
            and ipaddress.IPv4Address(target.addrTuple[0])
            in (network.network_address, network.broadcast_address)
        ):
            raise ValueError("The BBMD endpoint is a known local network/broadcast address.")
        binding = (app.nsap.local_adapter, layer.server.local_transport, own)
        interface = self.network.interface_ids.setdefault(app, secrets.token_hex(12))
        return app, config, layer, binding, target, interface

    async def _save(self, receipt):
        try:
            await _owned_disk(self.journal.save, copy.deepcopy(receipt))
        except (OSError, sqlite3.Error) as exc:
            raise ValueError("BBMD evidence storage failed: " + str(exc)[:500]) from exc

    def _available(self):
        if any(not task.done() for task in self.tasks.values()):
            raise ValueError("A BBMD administration Apply is active; finish or cancel it first.")
        for identifier in list(self.plans):
            if self.plans[identifier]["expires"] <= self.clock():
                del self.plans[identifier]
        if len(self.plans) >= MAX_PLANS:
            raise ValueError(f"At most {MAX_PLANS} fresh BBMD reviews may be pending.")

    async def preview(self, **arguments):
        task = asyncio.current_task()
        self.operations.add(task)
        try:
            return await self._preview(**arguments)
        finally:
            self.operations.discard(task)

    async def _preview(self, *, restored_from=None, **arguments):
        options = BbmdAdminPreview(**arguments)
        async with self.gate:
            self._available()
            await self._claim()
            await asyncio.wait_for(self.bacnet.lock.acquire(), LOCK_WAIT)
            try:
                app, config, layer, binding, target, interface = self._source(options.endpoint)
                receipt = {
                    "id": "bbma-" + secrets.token_hex(12),
                    "profile": PROFILE,
                    "scope": SCOPE,
                    "endpoint": options.endpoint,
                    "operation": options.operation,
                    "created_at": _utc(),
                    "config": config,
                    "interface_id": interface,
                    "local_endpoint": f"{binding[2][0]}:{binding[2][1]}",
                    "active": False,
                    "state": "review-required",
                    "dispatch_possible": False,
                    "local_send_entered": False,
                    "authorship_proven": False,
                    "atomic_cas": False,
                    "outcome": "not-dispatched",
                    "write_outcome": "not-dispatched",
                    "requests": [],
                    "read_failures": [],
                    "ignored_peers": 0,
                    "results_observed": [],
                    "results_omitted": 0,
                    "result_counts": dict.fromkeys(
                        (
                            "success",
                            "write_bdt_nack",
                            "read_bdt_nack",
                            "register_foreign_nack",
                            "read_fdt_nack",
                            "delete_fdt_nack",
                            "distribute_broadcast_nack",
                            "other",
                            "malformed",
                        ),
                        0,
                    ),
                    "native_admin_nack_observed": False,
                    "last_native_admin_nack": None,
                    "unattributed_results": [],
                    "unattributed_results_omitted": 0,
                    "restored_from": restored_from,
                    "delete_target": options.delete_target,
                }
                table = "bdt" if options.operation == "write-bdt" else "fdt"
                async with asyncio.timeout(8):
                    async with _Session(
                        self, app, config, layer, binding, target, options.timeout_seconds, receipt
                    ) as session:
                        receipt["before"] = await session.read(table)
                if table == "bdt":
                    rows = (
                        [
                            dict(ip=row["ip"], port=row["port"], mask=row["mask"])
                            for row in receipt["before"]["rows"]
                        ]
                        if options.rows is None
                        else [row.model_dump() for row in options.rows]
                    )
                    receipt["desired_rows"] = rows
                    wire = _frame(1, _bdt_payload(rows))
                    no_change = (
                        wire[4:] == bytes.fromhex(receipt["before"]["response"]["raw_hex"])[4:]
                    )
                else:
                    matches = [
                        row
                        for row in receipt["before"]["rows"]
                        if row["address"] == options.delete_target
                    ]
                    if len(matches) != 1:
                        raise ValueError(
                            "FDT deletion requires exactly one current matching endpoint; absent or duplicate leases are not actionable."
                        )
                    receipt["target_before"] = matches[0]
                    receipt["lease_generation_proven"] = False
                    native = IPv4Address(options.delete_target)
                    wire = _frame(8, native.addrAddr)
                    no_change = False
                receipt["write_wire_hex"] = wire.hex()
                receipt["write_sha256"] = hashlib.sha256(wire).hexdigest()
                expires = self.clock() + PLAN_SECONDS
                receipt["expires_at"] = (
                    datetime.now(UTC) + timedelta(seconds=PLAN_SECONDS)
                ).isoformat()
                receipt["review_hash"] = hashlib.sha256(encoded(receipt).encode()).hexdigest()
                receipt["state"] = "no-change" if no_change else "review-required"
                await self._save(receipt)
                self.runtime[receipt["id"]] = receipt
                public = copy.deepcopy(receipt)
                if not no_change:
                    token = secrets.token_urlsafe(32)
                    self.plans[receipt["id"]] = {
                        "token": token,
                        "expires": expires,
                        "app": app,
                        "config": config,
                        "layer": layer,
                        "binding": binding,
                        "target": target,
                        "timeout": options.timeout_seconds,
                        "review_hash": receipt["review_hash"],
                    }
                    public.update(apply_token=token, apply_available=True)
                else:
                    public["apply_available"] = False
                return public
            finally:
                self.bacnet.lock.release()

    async def apply(self, **arguments):
        task = asyncio.current_task()
        self.operations.add(task)
        try:
            return await self._apply(**arguments)
        finally:
            self.operations.discard(task)

    async def _apply(self, **arguments):
        options = BbmdAdminApply(**arguments)
        async with self.gate:
            if self.closed or any(not task.done() for task in self.tasks.values()):
                raise ValueError("BBMD administration is closed or another Apply is active.")
            plan = self.plans.pop(options.id, None)  # first attempt consumes this review
            if plan is None:
                raise ValueError(
                    "Review is absent, used, expired or from an earlier process; preview again."
                )
            receipt = copy.deepcopy(self.runtime[options.id])
            self.runtime[options.id] = receipt
            if (
                not secrets.compare_digest(options.apply_token, plan["token"])
                or not secrets.compare_digest(options.review_hash, plan["review_hash"])
                or self.clock() >= plan["expires"]
            ):
                receipt.update(
                    state="review-refused",
                    reason="Apply token/hash is invalid or expired; review consumed.",
                )
                await self._save(receipt)
                raise ValueError(receipt["reason"])
            stored = await _owned_disk(self.journal.get, options.id)
            sealed = {key: value for key, value in stored.items() if key != "review_hash"}
            if (
                stored.get("review_hash") != plan["review_hash"]
                or hashlib.sha256(encoded(sealed).encode()).hexdigest() != plan["review_hash"]
            ):
                receipt.update(
                    state="review-refused",
                    reason="Durable proposal differs from the reviewed hash; no write allowed.",
                )
                await self._save(receipt)
                raise ValueError(receipt["reason"])
            receipt = stored
            self.runtime[options.id] = receipt
            receipt.update(
                active=True, state="apply-queued", apply_available=False, apply_requested_at=_utc()
            )
            try:
                await self._save(receipt)  # durable admission before task/network creation
            except BaseException as exc:
                receipt.update(
                    active=False,
                    state="admission-failed",
                    outcome="not-dispatched",
                    write_outcome="not-dispatched",
                    reason=str(exc) or type(exc).__name__,
                )
                try:
                    await self._save(receipt)
                except Exception as storage_error:
                    receipt.update(durable=False, storage_error=str(storage_error)[:500])
                raise
            self.tasks[options.id] = asyncio.create_task(
                self._run_apply(receipt, plan), name="bbmd-apply-" + options.id
            )
            return self.detail(options.id)

    async def _run_apply(self, receipt, plan):
        locked = False
        try:
            await asyncio.wait_for(self.bacnet.lock.acquire(), LOCK_WAIT)
            locked = True
            async with asyncio.timeout(APPLY_SECONDS):
                async with _Session(
                    self,
                    plan["app"],
                    plan["config"],
                    plan["layer"],
                    plan["binding"],
                    plan["target"],
                    plan["timeout"],
                    receipt,
                ) as session:
                    receipt["state"] = "checking-baseline"
                    table = "bdt" if receipt["operation"] == "write-bdt" else "fdt"
                    receipt["preapply"] = await session.read(table)
                    before, current = receipt["before"], receipt["preapply"]
                    if table == "bdt":
                        unchanged = before["response"]["sha256"] == current["response"]["sha256"]
                    else:
                        unchanged = _fdt_identity(before["rows"]) == _fdt_identity(current["rows"])
                        receipt["lease_guard"] = (
                            "Address/TTL membership unchanged; remaining lease and generation are not CAS/version identity."
                        )
                    if not unchanged:
                        raise ValueError(
                            "Baseline changed since preview; no write sent. Create a fresh review."
                        )
                    session.guard()
                    if self.clock() >= plan["expires"]:
                        raise ValueError("Reviewed Apply expired before dispatch.")
                    receipt.update(
                        state="intent-durable",
                        intent_at=_utc(),
                        dispatch_possible=True,
                        outcome="unknown",
                        write_outcome="unknown",
                    )
                    await self._save(
                        receipt
                    )  # raw before/preapply backup and intent commit before dispatch
                    receipt["state"] = "dispatching"
                    receipt["write_result"] = await session.exchange(
                        receipt["operation"],
                        bytes.fromhex(receipt["write_wire_hex"]),
                        expires=plan["expires"],
                    )
                    receipt["state"] = "observing"
                    receipt["postapply"] = await session.read(table)
                    if table == "bdt":
                        desired = (
                            bytes.fromhex(receipt["postapply"]["response"]["raw_hex"])[4:]
                            == bytes.fromhex(receipt["write_wire_hex"])[4:]
                        )
                    else:
                        desired = not any(
                            row["address"] == receipt["delete_target"]
                            for row in receipt["postapply"]["rows"]
                        )
                    receipt.update(
                        state="complete",
                        outcome="desired-state-observed" if desired else "different-state-observed",
                        desired_state_observed=desired,
                        observation_at=receipt["postapply"]["response"]["received_at"],
                        authorship_proven=False,
                    )
        except asyncio.CancelledError:
            receipt.update(
                state="cancelled",
                outcome="unknown" if receipt["local_send_entered"] else "not-dispatched",
                write_outcome="unknown" if receipt["local_send_entered"] else "not-dispatched",
                reason="Cancelled; no further verification, retry or rollback is attempted.",
            )
            raise
        except Exception as exc:
            receipt.update(
                state="stopped",
                outcome="unknown" if receipt["local_send_entered"] else "not-dispatched",
                write_outcome="unknown" if receipt["local_send_entered"] else "not-dispatched",
                reason=(
                    "Operation deadline or interface lock wait expired."
                    if isinstance(exc, TimeoutError)
                    else (str(exc) or type(exc).__name__)
                )[:2000],
            )
        finally:
            if locked:
                self.bacnet.lock.release()
            receipt.update(active=False, finished_at=_utc())
            try:
                await self._save(receipt)
                receipt["durable"] = True
            except Exception as exc:
                receipt.update(
                    durable=False, storage_error="Final receipt not saved: " + str(exc)[:500]
                )

    async def cancel(self, identifier):
        task = self.tasks.get(identifier)
        if task is None:
            raise ValueError("No Apply task exists for this receipt.")
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            receipt = self.runtime[identifier]
            if receipt["active"]:  # cancellation before the task's first instruction
                receipt.update(
                    active=False,
                    state="cancelled",
                    outcome="not-dispatched",
                    reason="Cancelled before Apply began.",
                )
                await self._save(receipt)
        return self.detail(identifier)

    def detail(self, identifier):
        receipt = copy.deepcopy(self.runtime.get(identifier) or self.journal.get(identifier))
        receipt.setdefault("durable", not receipt["active"] if identifier in self.runtime else True)
        receipt["active_in_this_process"] = (
            receipt["active"] and identifier in self.tasks and not self.tasks[identifier].done()
        )
        receipt["apply_available"] = (
            False  # only a fresh preview response supplies the one-use token
        )
        return receipt

    def history(self):
        keys = (
            "id",
            "operation",
            "endpoint",
            "created_at",
            "state",
            "outcome",
            "active",
            "dispatch_possible",
            "durable",
            "storage_error",
        )
        return [
            {key: row.get(key, True if key == "durable" else None) for key in keys}
            for row in (self.journal.get(identifier) for identifier in self.journal.ids())
        ]

    async def saved_detail(self, identifier):
        if identifier in self.runtime:
            return self.detail(identifier)
        receipt = await _owned_disk(self.journal.get, identifier)
        receipt.update(apply_available=False, durable=True, active_in_this_process=False)
        return receipt

    async def saved_history(self):
        # Copy mutable runtime summaries only on the event loop. SQLite/hash work
        # runs off-loop, without racing callback mutations during deepcopy.
        rows = await _owned_disk(self.history)
        keys = (
            "id",
            "operation",
            "endpoint",
            "created_at",
            "state",
            "outcome",
            "active",
            "dispatch_possible",
            "durable",
            "storage_error",
        )
        return [
            {
                key: self.runtime[row["id"]].get(
                    key, not self.runtime[row["id"]]["active"] if key == "durable" else None
                )
                for key in keys
            }
            if row["id"] in self.runtime
            else row
            for row in rows
        ]

    def status(self):
        return {
            "profile": PROFILE,
            "scope": SCOPE,
            "auto_retry": False,
            "auto_rollback": False,
            "review_seconds": PLAN_SECONDS,
            "maximum_pending_reviews": MAX_PLANS,
            "history_capacity": MAX_RECORDS,
            "active": [
                self.detail(identifier)
                for identifier, task in self.tasks.items()
                if not task.done()
            ],
        }

    async def restore_preview(self, identifier, timeout_seconds=2.0):
        original = await _owned_disk(self.journal.get, identifier)
        if original["operation"] != "write-bdt":
            raise ValueError(
                "FDT registration recreation is not a restore operation in this profile."
            )
        rows = [
            {key: row[key] for key in ("ip", "port", "mask")} for row in original["before"]["rows"]
        ]
        return await self.preview(
            endpoint=original["endpoint"],
            operation="write-bdt",
            rows=rows,
            timeout_seconds=timeout_seconds,
            restored_from=identifier,
        )

    async def close(self):
        self.closed = True
        try:
            pending = [task for task in self.operations if task is not asyncio.current_task()]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for identifier in list(self.tasks):
                if not self.tasks[identifier].done():
                    await self.cancel(identifier)
            self.plans.clear()
        finally:
            if self.ownership is not None:
                self.ownership.close()
                self.ownership = None
