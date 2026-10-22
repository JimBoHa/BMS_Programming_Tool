"""Authored ephemeral SQLite/API history for browser identity acceptance only."""

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bms_tool.notification_outbox import NotificationOutbox
from bms_tool.observability import ObservabilityStore

HIGH_ID = 9007199254740993


def verify_package_target():
    """Installed acceptance must not silently import checkout code or assets."""
    import bms_tool
    from bms_tool import resources

    package = Path(bms_tool.__file__).resolve()
    target = os.environ.get("BMS_TEST_INSTALLED_TARGET")
    web = resources.web_directory()
    if target:
        target = Path(target).resolve()
        if not package.is_relative_to(target):
            raise RuntimeError("History fixture package is outside installed test target")
        if resources.source_checkout():
            raise RuntimeError("Installed history fixture resolved a source checkout")
        if web is None or not web.is_relative_to(target):
            raise RuntimeError("Installed history fixture lacks bundled UI")
        for name in ("requirements.json", "capabilities.json"):
            if not (package.parent / "data" / "app_docs" / name).is_file():
                raise RuntimeError("Installed history fixture lacks bundled metadata")
    return {
        "history_fixture": "installed" if target else "source",
        "package": str(package),
        "web": str(web),
    }


async def seed(directory):
    directory = Path(directory)
    observations = ObservabilityStore(directory)
    clock = datetime(2026, 1, 5, tzinfo=UTC)
    for project in ("chromium", "webkit"):
        observations.record_scan(
            f"simulation/identity-normal-{project}",
            clock,
            {"temperature": 90},
            {"hot": {"active": True, "message": "Authored identity alarm"}},
        )
    for name in ("alarm", "event"):
        observations.record_scan(f"simulation/identity-high-{name}", clock, {}, {"hot": True})
    for index in range(100):
        observations.record_scan(
            "simulation/identity-high-trend", clock + timedelta(seconds=index), {"flow": index}
        )
    outbox = NotificationOutbox(directory / "notifications", observations)
    routes = {}
    try:
        for project in ("chromium", "webkit", "high"):
            route = outbox.create_route(
                "Identity " + project,
                "http://127.0.0.1:1/paused-fixture",
                sources=["simulation/identity-normal-" + project],
            )
            routes[project] = route["id"]
        with outbox.connect() as db:
            for project, start in (("chromium", 11), ("webkit", 21), ("high", HIGH_ID)):
                for offset, state in enumerate(("failed", "failed", "delivered")):
                    identifier = start + offset
                    payload = json.dumps(
                        {"fixture": project, "record": identifier, "opaque_record_id": HIGH_ID}
                    )
                    digest = hashlib.sha256(payload.encode()).hexdigest()
                    db.execute(
                        "INSERT INTO notification_deliveries(id,route_id,record_key,kind,"
                        "event_sequence,payload,payload_sha256,idempotency_key,state,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            identifier,
                            routes[project],
                            str(identifier),
                            "event",
                            1,
                            payload,
                            digest,
                            digest,
                            state,
                            clock.isoformat(),
                            clock.isoformat(),
                        ),
                    )
    finally:
        await outbox.close()
    with observations.connect() as db:
        source = "simulation/identity-high-alarm"
        old = db.execute("SELECT id FROM alarm_occurrences WHERE source=?", (source,)).fetchone()[0]
        # Explicitly update all fixture references, preserving the authored rows.
        db.execute("UPDATE alarm_conditions SET occurrence=NULL WHERE source=?", (source,))
        db.execute("UPDATE alarm_occurrences SET id=? WHERE id=?", (HIGH_ID, old))
        db.execute("UPDATE alarm_conditions SET occurrence=? WHERE source=?", (HIGH_ID, source))
        db.execute("UPDATE alarm_events SET alarm_id=? WHERE source=?", (HIGH_ID, source))
        db.execute(
            "UPDATE alarm_events SET sequence=sequence+? WHERE source=?",
            (HIGH_ID, "simulation/identity-high-event"),
        )
        db.execute(
            "UPDATE trend_samples SET sequence=sequence+? WHERE source=?",
            (HIGH_ID, "simulation/identity-high-trend"),
        )
    return routes


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    directory = Path(os.environ["BMS_STUDIO_DATA"])
    print(json.dumps(verify_package_target()), flush=True)
    asyncio.run(seed(directory))
    import uvicorn
    from bms_tool.app import create_app

    uvicorn.run(create_app(directory), host="127.0.0.1", port=args.port, access_log=False)
