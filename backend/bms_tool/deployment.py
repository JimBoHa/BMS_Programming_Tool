"""Transactional online graph changes for our own runtime, not proprietary firmware."""

import copy
import secrets
import time

from .engine import Engine
from .models import Program


class Runtime:
    def __init__(self, store):
        self.store = store
        self.engine = None
        self.generation = 0
        self.plans = {}
        self.backups = []

    def status(self):
        return {
            "kind": "BMS Studio runtime",
            "target": "Local sandbox; no field outputs bound",
            "generation": self.generation,
            "program": self.engine.program.model_dump() if self.engine else None,
            "snapshot": self.engine.snapshot() if self.engine else None,
            "backups": [
                {
                    "id": b["id"],
                    "name": b["engine"].program.name,
                    "generation": b["generation"],
                }
                for b in self.backups
            ],
        }

    def plan(self, program: Program, inputs=None):
        if program.target.family != "universal-runtime":
            raise ValueError(
                "This online adapter targets BMS Studio runtime only. It cannot install applications into JCI/ALC/Honeywell/Niagara firmware."
            )
        candidate = Engine(program)
        # Prove the proposed graph can execute a complete scan before offering apply.
        candidate.step(inputs or {})
        old = self.engine.program if self.engine else None
        before = {n.id: n for n in old.nodes} if old else {}
        after = {n.id: n for n in program.nodes}
        token = secrets.token_urlsafe(24)
        diff = {
            "added": sorted(after.keys() - before.keys()),
            "removed": sorted(before.keys() - after.keys()),
            "changed": [id for id in after.keys() & before.keys() if after[id] != before[id]],
            "wiring_changed": old is None or old.edges != program.edges,
            "macro_definitions_changed": old is None
            or old.metadata.get("macros") != program.metadata.get("macros"),
        }
        self.plans[token] = {
            "program": program.model_copy(deep=True),
            "generation": self.generation,
            "expires": time.monotonic() + 300,
            "inputs": copy.deepcopy(inputs or {}),
            "hash": program.digest(),
        }
        self.plans = {k: v for k, v in self.plans.items() if v["expires"] > time.monotonic()}
        return {
            "token": token,
            "generation": self.generation,
            "sha256": program.digest(),
            "expires_in": 300,
            "diff": diff,
            "target": "Local sandbox runtime",
            "preflight_outputs": candidate.outputs,
        }

    def apply(self, token):
        plan = self.plans.pop(token, None)
        if not plan or plan["expires"] < time.monotonic():
            raise ValueError("Deployment plan expired or was already consumed.")
        if plan["generation"] != self.generation:
            raise ValueError("Runtime changed since preflight. Create a new plan.")
        candidate = Engine(plan["program"])
        if self.engine:
            old = self.engine.nodes
            # Preserve state only when kind, parameters, and every incoming source
            # match. Changing a control law or feedback wiring deliberately resets it.
            for n in candidate.nodes.values():
                previous = old.get(n.id)
                old_links = {k: v for k, v in self.engine.links.items() if k[0] == n.id}
                new_links = {k: v for k, v in candidate.links.items() if k[0] == n.id}
                if (
                    previous
                    and (
                        previous.kind,
                        previous.params,
                        previous.value_type,
                        previous.unit,
                    )
                    == (n.kind, n.params, n.value_type, n.unit)
                    and old_links == new_links
                ):
                    if n.id in self.engine.state:
                        candidate.state[n.id] = copy.deepcopy(self.engine.state[n.id])
            candidate.time = self.engine.time
            candidate.clock = self.engine.clock
        candidate.step(plan["inputs"])
        # Evidence is durable before changing the active pointer.
        self.store.record(
            "runtime.apply",
            {
                "generation": self.generation + 1,
                "old": self.engine.program.digest() if self.engine else None,
                "new": candidate.program.digest(),
                "target": "local-sandbox",
            },
        )
        if self.engine:
            self.backups.append(
                {
                    "id": secrets.token_hex(8),
                    "generation": self.generation,
                    "engine": copy.deepcopy(self.engine),
                }
            )
            self.backups = self.backups[-20:]
        self.engine = candidate
        self.generation += 1
        return self.status()

    def rollback(self, backup_id, expected_generation):
        if expected_generation != self.generation:
            raise ValueError("Runtime generation changed; reload before rollback.")
        backup = next((b for b in self.backups if b["id"] == backup_id), None)
        if not backup:
            raise ValueError("Runtime backup not found.")
        restored = copy.deepcopy(backup["engine"])
        self.store.record(
            "runtime.rollback",
            {
                "backup": backup_id,
                "generation": self.generation + 1,
                "sha256": restored.program.digest(),
            },
        )
        self.engine = restored
        self.generation += 1
        self.plans.clear()
        return self.status()
