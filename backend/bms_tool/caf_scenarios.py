"""Persist and preview local input stimuli without executing native CAF logic.

Only observed saved Input Float/Boolean simulation records form the input
contract. Quality is local metadata, not a claimed JCI encoding. Native startup
copies reuse the separately verified scalar editor and refuse non-good quality.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import uuid
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal

from .caf import CafArchive, Q
from .caf_simulation import CafSimulationProfile, _value
from .storage import Conflict

FORMAT = "bms.caf-local-input-scenario"
VERSION = 1
MAX_BYTES = 2 * 1024 * 1024
MAX_SCENARIOS = 200
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_INPUTS = 256
MAX_EVENTS = 2000
MAX_FRAMES = 2001
MAX_PREVIEW_BYTES = 4 * 1024 * 1024
QUALITIES = ("good", "open-circuit", "short-circuit", "unreliable", "out-of-service")
SEMANTICS = {
    "time": "Elapsed seconds from zero; no wall clock or native scan timing.",
    "hold": "Zero-order hold. Updates apply inclusively at their exact time; omitted inputs retain prior values.",
    "frames": "Zero, each dt boundary below duration, every event time, and duration; sorted and unique.",
    "initial_quality": "Locally assumed good; not a measured controller condition.",
    "quality": "Local stimulus metadata only; no native quality encoding or logic execution.",
    "value": "Validated native scalar text, preserved without interpolation or unit conversion.",
}
SCOPE = "Input-stimulus preview only. Native CAF logic and controller outputs are not executed."


def _json(value):
    try:
        return json.dumps(
            value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode()
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError("Local scenario must contain bounded finite JSON values.") from exc


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _number(value, label, *, positive=False, maximum=86400):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid or value < 0 or (positive and value == 0) or value > maximum:
        raise ValueError(
            f"{label} requires finite seconds {'above zero' if positive else 'at least zero'} through {maximum}."
        )
    return value


class CafInputScenarios:
    def __init__(self, archive: CafArchive):
        self.archive = archive
        rows = CafSimulationProfile(archive).summary()["records"]
        inputs = []
        for row in rows:
            # 527 is an Output Float Block, not an input. Enums remain unsupported.
            if not row["editable"] or row["class_id"] not in {"526", "530"}:
                continue
            obj = archive.objects[row["ref"]]
            units = [p for p in obj if p.tag == Q + "property" and p.get("id") == "117"]
            unit = archive.scalar(units[0]) if len(units) == 1 else None
            inputs.append(
                {
                    "id": row["ref"] + "::simulationProperty:3113",
                    "ref": row["ref"],
                    "property_id": "3113",
                    "class_id": row["class_id"],
                    "class_version": row["class_version"],
                    "name": row["name"],
                    "native_type": row["native_type"],
                    "units_native": unit,
                    "unit_status": "raw-native-metadata" if unit else "unknown",
                    "initial_value": row["old"],
                }
            )
        if len(inputs) > MAX_INPUTS or len(_json(inputs)) > 128 * 1024:
            raise ValueError("Local CAF input contract exceeds 256 inputs or 128 KiB.")
        if len({row["id"] for row in inputs}) != len(inputs):
            raise ValueError("Local CAF input contract has ambiguous input identities.")
        self.inputs = inputs
        self.input_bytes = len(_json(inputs))
        self.frame_bytes = sum(len(_json(row["id"])) + 640 for row in inputs) + 100
        self.profile_hash = _digest({"version": VERSION, "inputs": inputs, "semantics": SEMANTICS})

    def contract(self):
        return {
            "source_sha256": self.archive.hash,
            "profile_sha256": self.profile_hash,
            "inputs": copy.deepcopy(self.inputs),
            "semantics": copy.deepcopy(SEMANTICS),
            "qualities": QUALITIES,
            "scope": SCOPE,
            "native_execution": False,
        }

    def template(self):
        # A supported large input contract must have a usable bounded starting draft.
        interval = next(
            (
                dt
                for dt in range(1, 61)
                if self._preview_bytes(math.ceil(60 / dt) + 1) <= MAX_PREVIEW_BYTES
            ),
            60,
        )
        return {
            "format": FORMAT,
            "version": VERSION,
            "source_sha256": self.archive.hash,
            "profile_sha256": self.profile_hash,
            "inputs": copy.deepcopy(self.inputs),
            "name": "New input scenario",
            "description": "",
            "duration": 60,
            "dt": interval,
            "events": [],
        }

    def validate(self, scenario):
        expected = set(self.template())
        if not isinstance(scenario, dict) or set(scenario) != expected:
            raise ValueError("Local CAF input scenario requires the exact versioned fields.")
        if (
            scenario["format"] != FORMAT
            or type(scenario["version"]) is not int
            or scenario["version"] != VERSION
            or scenario["source_sha256"] != self.archive.hash
            or scenario["profile_sha256"] != self.profile_hash
            or _json(scenario["inputs"]) != _json(self.inputs)
        ):
            raise ValueError(
                "Scenario source SHA-256, semantic input profile or exact input guards do not match this CAF."
            )
        if len(_json(scenario)) > MAX_BYTES:
            raise ValueError("Local input scenario exceeds 2 MiB.")
        for key, limit in (("name", 120), ("description", 2000)):
            text = scenario[key]
            if (
                not isinstance(text, str)
                or len(text) > limit
                or (key == "name" and not text.strip())
                or any(ord(c) < 32 and c not in "\n\t" for c in text)
            ):
                raise ValueError(f"Scenario {key} requires text through {limit} characters.")
        duration = _number(scenario["duration"], "Scenario duration", positive=True)
        dt = _number(scenario["dt"], "Scenario dt", positive=True, maximum=60)
        if Decimal(str(duration)) / Decimal(str(dt)) > MAX_FRAMES - 1:
            raise ValueError(
                "Scenario exceeds 2001 preview frames; increase dt or shorten duration."
            )
        events = scenario["events"]
        if not isinstance(events, list) or len(events) > MAX_EVENTS:
            raise ValueError("Scenario requires at most 2000 event rows.")
        if not self.inputs:
            raise ValueError(
                "This CAF has no supported saved input startup records for local scenarios."
            )
        definitions = {row["id"]: row for row in self.inputs}
        previous = -1
        for event in events:
            if not isinstance(event, dict) or set(event) != {"time", "values"}:
                raise ValueError("Each scenario event requires time and values only.")
            time = _number(event["time"], "Event time", maximum=duration)
            if time <= previous:
                raise ValueError(
                    "Event rows require strictly increasing times; combine simultaneous input updates in one row."
                )
            previous = time
            if not isinstance(event["values"], dict) or not event["values"]:
                raise ValueError("Each event requires at least one exact input identity.")
            for identity, sample in event["values"].items():
                if (
                    identity not in definitions
                    or not isinstance(sample, dict)
                    or set(sample) != {"value", "quality"}
                ):
                    raise ValueError("Event contains an unknown input identity or sample fields.")
                _value(sample["value"], definitions[identity]["native_type"])
                if sample["quality"] not in QUALITIES:
                    raise ValueError("Event quality must use a documented local stimulus quality.")
        times = self._times(scenario)
        # Bound repeated identities and scalar text before allocating the preview.
        if len(times) > MAX_FRAMES or self._preview_bytes(len(times)) > MAX_PREVIEW_BYTES:
            raise ValueError("Scenario exceeds bounded preview frame/byte capacity.")
        return copy.deepcopy(scenario)

    def _preview_bytes(self, count):
        return self.input_bytes + 4096 + count * self.frame_bytes

    @staticmethod
    def _times(scenario):
        duration, dt = Decimal(str(scenario["duration"])), Decimal(str(scenario["dt"]))
        count = int((duration / dt).to_integral_value(rounding=ROUND_CEILING))
        times = {i * dt for i in range(count)}
        times.add(duration)
        times.update(Decimal(str(event["time"])) for event in scenario["events"])
        return [float(time) for time in sorted(times)]

    def preview(self, scenario):
        scenario = self.validate(scenario)
        values = {
            row["id"]: {"value": row["initial_value"], "quality": "good"} for row in self.inputs
        }
        frames, index = [], 0
        for time in self._times(scenario):
            while index < len(scenario["events"]) and scenario["events"][index]["time"] <= time:
                values.update(scenario["events"][index]["values"])
                index += 1
            frames.append({"time": time, "inputs": copy.deepcopy(values)})
        return {
            "source_sha256": self.archive.hash,
            "profile_sha256": self.profile_hash,
            "scenario_sha256": _digest(scenario),
            "scenario_name": scenario["name"],
            "input_definitions": copy.deepcopy(self.inputs),
            "format": "bms.caf-local-input-preview",
            "version": VERSION,
            "scope": SCOPE,
            "semantics": SEMANTICS,
            "frames": frames,
        }

    def startup_profile(self, scenario, time):
        trace = self.preview(scenario)
        _number(time, "Preview frame time", maximum=scenario["duration"])
        frame = next((row for row in trace["frames"] if row["time"] == time), None)
        if frame is None:
            raise ValueError("Choose an exact time from the preview frames.")
        if any(sample["quality"] != "good" for sample in frame["inputs"].values()):
            raise ValueError(
                "Native quality encoding is unverified; only all-good frames can prepare native startup values."
            )
        profile = CafSimulationProfile(self.archive).export_profile()
        for row in profile["entries"]:
            identity = row["ref"] + "::simulationProperty:" + str(row["property_id"])
            if identity in frame["inputs"]:
                row["value"] = frame["inputs"][identity]["value"]
        # Reuse actual scalar editor validation; never create native trajectory/quality structures.
        CafSimulationProfile(self.archive).apply(profile)
        return profile


class CafScenarioStore:
    """Bounded SQLite records with optimistic saves and content-integrity guards."""

    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS caf_local_scenarios(
                id TEXT PRIMARY KEY, revision INTEGER NOT NULL, source_sha256 TEXT NOT NULL,
                name TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL,
                content BLOB NOT NULL, sha256 TEXT NOT NULL)""")

    @staticmethod
    def _identity(identity):
        if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise ValueError("Invalid local scenario identifier.")

    @staticmethod
    def _read(row):
        if row is None:
            raise ValueError("Saved local scenario not found.")
        content = row["content"]
        if (
            not isinstance(content, bytes)
            or len(content) > MAX_BYTES
            or hashlib.sha256(content).hexdigest() != row["sha256"]
        ):
            raise ValueError("Saved local scenario failed content integrity verification.")
        try:
            scenario = json.loads(content)
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Saved local scenario contains invalid JSON.") from exc
        if (
            not isinstance(scenario, dict)
            or scenario.get("source_sha256") != row["source_sha256"]
            or scenario.get("name") != row["name"]
        ):
            raise ValueError("Saved local scenario identity metadata changed.")
        return {key: row[key] for key in ("id", "revision", "created", "updated")} | {
            "scenario": scenario
        }

    def list(self, adapter):
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM caf_local_scenarios WHERE source_sha256=? ORDER BY updated DESC,id",
                (adapter.archive.hash,),
            ).fetchall()
        result = []
        for row in rows:
            saved = self._read(row)
            adapter.validate(saved["scenario"])
            result.append(
                {key: saved[key] for key in ("id", "revision", "created", "updated")}
                | {"name": saved["scenario"]["name"]}
            )
        return result

    def load(self, adapter, identity):
        self._identity(identity)
        with self.store.connect() as db:
            saved = self._read(
                db.execute("SELECT * FROM caf_local_scenarios WHERE id=?", (identity,)).fetchone()
            )
        adapter.validate(saved["scenario"])
        return saved

    def save(self, adapter, scenario, identity=None, expected_revision=0):
        scenario = adapter.validate(scenario)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("Expected revision must be a nonnegative integer.")
        identity = uuid.uuid4().hex if identity is None else identity
        self._identity(identity)
        content = _json(scenario)
        now = datetime.now(UTC).isoformat()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT * FROM caf_local_scenarios WHERE id=?", (identity,)
            ).fetchone()
            current = prior["revision"] if prior else 0
            if current != expected_revision:
                raise Conflict("Saved scenario revision changed; reopen before saving.")
            if prior:
                self._read(prior)
                if prior["source_sha256"] != adapter.archive.hash:
                    raise ValueError("Cannot replace a scenario belonging to another source CAF.")
            usage = db.execute(
                "SELECT COUNT(*) AS n,COALESCE(SUM(length(content)),0) AS bytes FROM caf_local_scenarios"
            ).fetchone()
            if (not prior and usage["n"] >= MAX_SCENARIOS) or usage["bytes"] - (
                len(prior["content"]) if prior else 0
            ) + len(content) > MAX_TOTAL_BYTES:
                raise ValueError(
                    "Local scenario storage capacity reached; delete unused scenarios."
                )
            db.execute(
                "INSERT OR REPLACE INTO caf_local_scenarios VALUES(?,?,?,?,?,?,?,?)",
                (
                    identity,
                    current + 1,
                    adapter.archive.hash,
                    scenario["name"],
                    prior["created"] if prior else now,
                    now,
                    content,
                    hashlib.sha256(content).hexdigest(),
                ),
            )
        self.store.record(
            "caf.local-scenario.save",
            {"id": identity, "source_sha256": adapter.archive.hash, "revision": current + 1},
        )
        return self.load(adapter, identity)

    def delete(self, adapter, identity, expected_revision):
        self._identity(identity)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = self._read(
                db.execute("SELECT * FROM caf_local_scenarios WHERE id=?", (identity,)).fetchone()
            )
            adapter.validate(prior["scenario"])
            if type(expected_revision) is not int or prior["revision"] != expected_revision:
                raise Conflict("Saved scenario revision changed; reopen before deleting.")
            db.execute("DELETE FROM caf_local_scenarios WHERE id=?", (identity,))
        self.store.record(
            "caf.local-scenario.delete", {"id": identity, "source_sha256": adapter.archive.hash}
        )
        return {"deleted": identity}
