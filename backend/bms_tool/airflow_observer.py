"""Bounded read-only airflow observation using the existing controller reader.

The site selects every target and object explicitly in a private configuration.
No controller command, backup, restore, schedule or tuning operation is exposed.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import html
import json
import math
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bacpypes3.primitivedata import ObjectIdentifier

from .connections import Bacnet
from .controller_workspace import ControllerPropertiesRequest, ControllerWorkspace
from .storage import Store


def utc():
    return datetime.now(UTC)


def stamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("Observation timestamps must include a timezone.")
    return result


def private_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, allow_nan=False))
    temp.chmod(0o600)
    temp.replace(path)


def load_config(path):
    cfg = json.loads(path.read_text())
    ZoneInfo(cfg["timezone"])
    start, deadline, stop = map(
        stamp, (cfg["collection_from"], cfg["startup_deadline"], cfg["hard_stop"])
    )
    if not start < deadline < stop or not 600 <= cfg["minimum_monitor_seconds"] <= 86400:
        raise ValueError("Use a bounded observation window and monitoring duration.")
    if (stop - start).total_seconds() > 2 * 86400:
        raise ValueError("The observation is limited to two days.")
    if not 1 <= cfg["startup_confirmations"] <= 10 or not 60 <= cfg["checkpoint_seconds"] <= 3600:
        raise ValueError("Use bounded startup confirmations and checkpoint intervals.")
    if not 0 < cfg["startup_min_static"] < 10:
        raise ValueError("The startup pressure threshold must be positive and below 10 in. w.g.")
    if not 600 <= cfg.get("minimum_qualified_seconds", cfg["minimum_monitor_seconds"]) <= 86400:
        raise ValueError("Use a bounded qualified observation duration.")
    aliases = []
    groups = set()
    for group in cfg["groups"]:
        if group["name"] in groups:
            raise ValueError("Read group names must be distinct.")
        groups.add(group["name"])
        if not group["points"] or not 10 <= group["interval_seconds"] <= 3600:
            raise ValueError("Every read group needs explicit points and a bounded interval.")
        for offset in range(0, len(group["points"]), 16):
            ControllerPropertiesRequest(
                **group["target"],
                object_ids=[p["object"] for p in group["points"][offset : offset + 16]],
                properties=[
                    "object-name",
                    "present-value",
                    "reliability",
                    "status-flags",
                    "out-of-service",
                ],
            )
        aliases.extend(p["alias"] for p in group["points"])
    if len(set(aliases)) != len(aliases) or len(aliases) > 256:
        raise ValueError("Use distinct explicit observation aliases, at most 256.")
    if not set(cfg["startup_fans"] + [cfg["startup_pressure"]]) <= set(aliases):
        raise ValueError("Startup evidence must refer to observed points.")
    startup_keys = set(cfg["startup_fans"] + [cfg["startup_pressure"]])
    if not any(startup_keys <= {p["alias"] for p in g["points"]} for g in cfg["groups"]):
        raise ValueError("Startup proof must be read together in one group.")
    for suffix in ("damper", "flow", "flow_sp"):
        if cfg["target_name"] + "." + suffix not in aliases:
            raise ValueError("The target requires explicit damper, flow and flow_sp aliases.")
    return cfg


def scalar(value):
    if isinstance(value, dict):
        return scalar(value.get("value"))
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def point_value(item, expected):
    fields = item.get("properties", {})
    errors = []
    values = {}
    for name in ["object-name", "present-value", "reliability", "status-flags", "out-of-service"]:
        row = fields.get(name, {})
        if row.get("status") != "ok":
            errors.append(name + ": " + str(row.get("error", "unavailable"))[:200])
        values[name] = scalar(row.get("value"))
    flags = values["status-flags"]
    named = values["object-name"] == expected
    quality = (
        item.get("identity_verified") is True
        and not errors
        and named
        and type(values["present-value"]) in (int, float, bool)
        and values["reliability"] == 0
        and values["out-of-service"] is False
        and isinstance(flags, list)
        and len(flags) == 4
        and not flags[1]
        and not flags[3]
    )
    if not named:
        errors.append("Published point name differs from the reviewed source.")
    return {
        "value": values["present-value"] if named and item.get("identity_verified") else None,
        "quality_ok": bool(quality),
        "reliability": values["reliability"],
        "flags": flags,
        "override_flag": bool(flags[2]) if isinstance(flags, list) and len(flags) == 4 else None,
        "out_of_service": values["out-of-service"],
        "received_at": fields.get("present-value", {}).get("received_at"),
        "errors": errors,
    }


async def read_group(reader, group):
    record = {
        "utc": utc().isoformat(),
        "group": group["name"],
        "source": group["source"],
        "points": {},
        "errors": [],
    }
    try:
        async with asyncio.timeout(25):
            await _read_group(reader, group, record)
    except (ValueError, OSError, TimeoutError) as exc:
        record["errors"].append((str(exc) or type(exc).__name__)[:300])
    for point in group["points"]:
        record["points"].setdefault(
            point["alias"], {"value": None, "quality_ok": False, "errors": ["Read unavailable."]}
        )
    record["finished_utc"] = utc().isoformat()
    return record


async def _read_group(reader, group, record):
    identity = await reader.properties(
        **group["target"], object_ids=[group["target"]["device"]], properties=["object-name"]
    )
    name = (identity.get("objects") or [{}])[0].get("properties", {}).get("object-name", {})
    if (
        not identity.get("identity_verified")
        or scalar(name.get("value")) != group["expected_device_name"]
    ):
        raise ValueError("The actual Device identity/name differs from this observation.")
    for offset in range(0, len(group["points"]), 16):
        selected = group["points"][offset : offset + 16]
        report = await reader.properties(
            **group["target"],
            object_ids=[p["object"] for p in selected],
            properties=[
                "object-name",
                "present-value",
                "reliability",
                "status-flags",
                "out-of-service",
            ],
        )
        record["errors"].extend(report.get("errors", []))
        if not report.get("identity_verified"):
            raise ValueError("Source identity was not verified for the read group.")
        items = {p["object"]: p for p in report.get("objects", [])}
        for point in selected:
            record["points"][point["alias"]] = point_value(
                items.get(str(ObjectIdentifier(point["object"])), {}), point["expected_name"]
            )


def startup_ready(points, cfg):
    fans = [points.get(p, {}) for p in cfg["startup_fans"]]
    pressure = points.get(cfg["startup_pressure"], {})
    return (
        any(p.get("quality_ok") and p.get("value") == 1 for p in fans)
        and pressure.get("quality_ok") is True
        and type(pressure.get("value")) in (int, float)
        and pressure["value"] >= cfg["startup_min_static"]
    )


def series(records, alias, since=None):
    return [
        (stamp(r["utc"]).timestamp(), p["value"])
        for r in records
        if (since is None or stamp(r["utc"]).timestamp() >= since)
        and (p := r["points"].get(alias, {})).get("quality_ok")
        and type(p.get("value")) in (int, float)
    ]


def observed_seconds(records, alias, since, *, require_air=False, required_aliases=()):
    """Count actual adjacent good samples; never backfill downtime."""
    values = []
    for record in records:
        if alias not in record["points"]:
            continue
        t = stamp(record["utc"]).timestamp()
        if since is not None and t < since:
            continue
        qualified = (not require_air or record.get("airflow_available") is True) and all(
            record["points"].get(p, {}).get("quality_ok") for p in [alias, *required_aliases]
        )
        values.append((t, qualified))
    return sum(
        min(30, b[0] - a[0])
        for a, b in zip(values, values[1:], strict=False)
        if a[1] and b[1] and 0 < b[0] - a[0] <= 65
    )


def reversals(values, deadband=5):
    if not values:
        return 0
    anchor, direction, count = values[0], 0, 0
    extreme = anchor
    for value in values[1:]:
        if not direction:
            if abs(value - anchor) >= deadband:
                direction = 1 if value > anchor else -1
                extreme = value
        elif direction * (value - extreme) > 0:
            extreme = value
        elif direction * (value - extreme) <= -deadband:
            count += 1
            direction *= -1
            extreme = value
    return count


def metrics(records, name, since=None):
    records = [r for r in records if r.get("airflow_available") is True]
    automatic = [
        r for r in records if not r["points"].get(name + ".damper", {}).get("override_flag")
    ]
    d = [v for _, v in series(automatic, name + ".damper", since)]
    samples = []
    for record in automatic:
        if since is not None and stamp(record["utc"]).timestamp() < since:
            continue
        p = record["points"]
        f, s = p.get(name + ".flow", {}), p.get(name + ".flow_sp", {})
        if f.get("quality_ok") and s.get("quality_ok") and s["value"] >= 20:
            samples.append((f["value"], s["value"]))
    errors = [f - s for f, s in samples]
    sp = [s for _, s in samples]
    stable = bool(sp) and max(sp) - min(sp) <= max(10, 0.1 * statistics.median(sp))
    signs = [
        1 if e > max(10, 0.1 * s) else -1 if e < -max(10, 0.1 * s) else 0
        for (f, s), e in zip(samples, errors, strict=True)
    ]
    meaningful = [s for s in signs if s]
    crossings = sum(a != b for a, b in zip(meaningful, meaningful[1:], strict=False))
    count = reversals(d)
    return {
        "damper_samples": len(d),
        "damper_min": min(d) if d else None,
        "damper_max": max(d) if d else None,
        "damper_median": statistics.median(d) if d else None,
        "damper_reversals_5pp": count,
        "active_flow_samples": len(errors),
        "flow_error_rmse_cfm": math.sqrt(statistics.mean(e * e for e in errors))
        if errors
        else None,
        "maximum_overshoot_cfm": max(0, max(errors)) if errors else None,
        "within_10cfm_or_10pct": statistics.mean(
            abs(e) <= max(10, 0.1 * s) for (_, s), e in zip(samples, errors, strict=True)
        )
        if errors
        else None,
        "stable_flow_setpoint": stable,
        "large_error_crossings": crossings,
        "possible_hunting": bool(
            len(d) >= 40 and stable and count >= 4 and crossings >= 3 and max(d) - min(d) >= 15
        ),
    }


def matched_demand(records, names, since):
    """Compare commands only where requested-flow bins overlap (not equal pressure)."""
    result = {}
    for name in names:
        bins = {}
        for record in records:
            if not record.get("airflow_available") or (
                since and stamp(record["utc"]).timestamp() < since
            ):
                continue
            p = record["points"]
            d, s = p.get(name + ".damper", {}), p.get(name + ".flow_sp", {})
            if (
                d.get("quality_ok")
                and s.get("quality_ok")
                and not d.get("override_flag")
                and type(s.get("value")) in (int, float)
                and s["value"] >= 20
            ):
                key = int(s["value"] // 20) * 20
                bins.setdefault(key, []).append(d["value"])
        result[name] = {
            key: {"samples": len(values), "median_damper": statistics.median(values)}
            for key, values in bins.items()
        }
    return result


def read_records(path):
    if not path.exists():
        return []
    records = []
    lines = path.read_text().splitlines(keepends=True)
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            # A power-loss fragment is not a measurement. Preserve it for review.
            if index != len(lines) - 1 or line.endswith("\n"):
                raise
    return records


def recover_tail(path):
    """Preserve an interrupted append before allowing a resumed job to append."""
    if not path.exists():
        return None
    data = path.read_bytes()
    if not data or data.endswith(b"\n"):
        return None
    boundary = data.rfind(b"\n") + 1
    try:
        json.loads(data[boundary:])
    except (json.JSONDecodeError, UnicodeDecodeError):
        retained = path.with_name(path.name + ".interrupted-" + utc().strftime("%Y%m%dT%H%M%S%f"))
        retained.write_bytes(data[boundary:])
        retained.chmod(0o600)
        temp = path.with_suffix(".recovering")
        temp.write_bytes(data[:boundary])
        temp.chmod(0o600)
        temp.replace(path)
        return str(retained)
    with path.open("ab") as stream:
        stream.write(b"\n")
    return None


def window_end_reason(cfg, state, now):
    if now >= stamp(cfg["hard_stop"]):
        return "The bounded observation window ended."
    if not state.get("monitor_started_utc") and now >= stamp(cfg["startup_deadline"]):
        return "No qualified startup was detected before the startup deadline."
    return None


def svg_plot(records, names, key, since=None, timezone="UTC"):
    colors = ["#007f86", "#b45309", "#7352a0", "#2766b3", "#647d2d", "#be375f"]
    lines = [(name, series(records, name + "." + key, since)) for name in names]
    allpoints = [p for _, values in lines for p in values]
    if not allpoints:
        return "<p>No qualified samples yet.</p>"
    lo, hi = min(p[0] for p in allpoints), max(p[0] for p in allpoints)
    high = max(1, max(p[1] for p in allpoints))
    low = min(0, min(p[1] for p in allpoints))
    result = [
        '<svg viewBox="0 0 1000 270" role="img" aria-label="Observed time series"><path d="M55 15V210H980" fill="none" stroke="#71818a"/>'
    ]
    for index in range(5):
        value = low + (high - low) * index / 4
        y = 210 - 190 * index / 4
        result.append(
            f'<path d="M55 {y}H980" stroke="#e0e8eb"/><text x="3" y="{y + 4}" font-size="11">{value:.1f}</text>'
        )
    for i, (name, values) in enumerate(lines):
        segments, points, previous = [], [], None
        for t, v in values:
            if previous is not None and t - previous > 150:
                segments.append(points)
                points = []
            points.append(
                f"{55 + 925 * (t - lo) / max(1, hi - lo):.1f},{210 - 190 * (v - low) / max(1, high - low):.1f}"
            )
            previous = t
        segments.append(points)
        for part in segments:
            result.append(
                f'<polyline points="{" ".join(part)}" fill="none" stroke="{colors[i % len(colors)]}" stroke-width="1.5"><title>{html.escape(name)}</title></polyline>'
            )
        result.append(
            f'<text x="{55 + i * 170}" y="260" font-size="12" fill="{colors[i % len(colors)]}">{html.escape(name)}</text>'
        )
    for t, x, anchor in [(lo, 55, "start"), ((lo + hi) / 2, 517, "middle"), (hi, 980, "end")]:
        label = datetime.fromtimestamp(t, ZoneInfo(timezone)).strftime("%H:%M:%S %Z")
        result.append(f'<text x="{x}" y="231" font-size="11" text-anchor="{anchor}">{label}</text>')
    result.append("</svg>")
    return "".join(result)


def render_report(cfg, state, records, output):
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    start = (
        stamp(state["monitor_started_utc"]).timestamp()
        if state.get("monitor_started_utc")
        else None
    )
    names = [cfg["target_name"], *cfg["reference_names"]]
    summary = {name: metrics(records, name, start) for name in names}
    demand = matched_demand(records, names, start)
    checks = read_records(output / "checkins.jsonl")
    for name, row in summary.items():
        row["hunting_checkpoints"] = sum(
            c.get("last_hour", {}).get(name, {}).get("possible_hunting", False) for c in checks
        )
    private_json(
        output / "analysis.json",
        {
            "status": state["status"],
            "state": state,
            "metrics": summary,
            "flow_request_bins": demand,
            "limits": cfg["limits"],
        },
    )
    rows = []
    for name, m in summary.items():

        def number(key, m=m):
            return "Unavailable" if m[key] is None else f"{m[key]:.1f}"

        rows.append(
            "<tr><td>"
            + html.escape(name)
            + "</td><td>"
            + number("damper_median")
            + "</td><td>"
            + number("damper_min")
            + "–"
            + number("damper_max")
            + "</td><td>"
            + number("flow_error_rmse_cfm")
            + "</td><td>"
            + number("maximum_overshoot_cfm")
            + "</td><td>"
            + str(m["damper_reversals_5pp"])
            + "</td><td>"
            + (
                "Review possible hunting"
                if m["possible_hunting"] or m["hunting_checkpoints"]
                else "No screening flag"
                if m["active_flow_samples"] >= 40 and m["stable_flow_setpoint"]
                else "Insufficient steady-flow data"
            )
            + "</td></tr>"
        )
    body = (
        '<!doctype html><html><meta charset="utf-8"><title>Airflow and damper observation</title><style>body{font:16px/1.5 system-ui;max-width:1250px;margin:30px auto;padding:0 20px;color:#203840}h1,h2{color:#006b72}table{width:100%;border-collapse:collapse}td,th{padding:9px;border:1px solid #cbd8dc;text-align:left}th{background:#e5f1f2}svg{width:100%;max-height:330px}pre{white-space:pre-wrap}.note{background:#fff4d7;padding:12px}</style><h1>'
        + html.escape(cfg["target_name"])
        + ": airflow and damper observation</h1><p><b>Status: "
        + html.escape(state["status"])
        + "</b>. Updated "
        + utc().astimezone(ZoneInfo(cfg["timezone"])).strftime("%Y-%m-%d %H:%M:%S %Z")
        + "</p><p>Observed startup: "
        + html.escape(state.get("monitor_started_utc", "Not detected yet"))
        + ". Qualified target observation: "
        + str(round(state.get("observed_target_seconds", 0) / 3600, 2))
        + " hours. "
        + html.escape(state.get("reason", ""))
        + '</p><p class="note">Read-only observation. Screening flags are candidates for engineering review, not PID-tuning instructions. No tuning, overrides, transfers, schedule changes or NAE trend/alarm objects are created. No normal damper percentage is assumed.</p><h2>Damper command / estimated position (%)</h2>'
    )
    body += svg_plot(records, names, "damper", start, cfg["timezone"])
    body += "<h2>Measured flow (CFM)</h2>" + svg_plot(
        records, names, "flow", start, cfg["timezone"]
    )
    body += "<h2>Requested flow (CFM)</h2>" + svg_plot(
        records, names, "flow_sp", start, cfg["timezone"]
    )
    if cfg.get("startup_pressure"):
        prefix, key = cfg["startup_pressure"].rsplit(".", 1)
        body += "<h2>Air-handler duct static pressure (in. w.g.)</h2>" + svg_plot(
            records, [prefix], key, start, cfg["timezone"]
        )
    body += (
        "<h2>Summary</h2><table><tr><th>Box</th><th>Median damper %</th><th>Damper range %</th><th>Flow error RMSE CFM</th><th>Peak overshoot CFM</th><th>Reversals ≥5 percentage points</th><th>Screening</th></tr>"
        + "".join(rows)
        + "</table>"
    )
    body += (
        "<h2>Similar requested airflow</h2><p>Median damper command by 20-CFM request band. This does not establish equal duct pressure or equal occupancy/fan states. At least ten samples per box are needed to display a comparison.</p><table><tr><th>Request CFM</th>"
        + "".join("<th>" + html.escape(n) + " median % (samples)</th>" for n in names)
        + "</tr>"
    )
    for band, target in sorted(demand[names[0]].items()):
        if target["samples"] < 10:
            continue
        body += f"<tr><td>{band}–&lt;{band + 20}</td>"
        for name in names:
            values = demand[name].get(band, {})
            body += (
                "<td>"
                + (
                    f"{values['median_damper']:.1f} ({values['samples']})"
                    if values.get("samples", 0) >= 10
                    else "Insufficient overlap"
                )
                + "</td>"
            )
        body += "</tr>"
    body += "</table><h2>Ten-minute checkpoints</h2><table><tr><th>Local time</th><th>Target reversals in steady-flow window</th><th>Target airflow RMSE CFM</th><th>Screening</th></tr>"
    for check in checks:
        m = check.get("last_hour", {}).get(names[0], {})
        error = m.get("flow_error_rmse_cfm")
        label = (
            "Review possible hunting"
            if m.get("possible_hunting")
            else "No flag; inspect coverage and flow request"
        )
        body += (
            "<tr><td>"
            + stamp(check["utc"]).astimezone(ZoneInfo(cfg["timezone"])).strftime("%H:%M:%S %Z")
            + f"</td><td>{m.get('damper_reversals_5pp', 0)}</td><td>"
            + (f"{error:.1f}" if error is not None else "Unavailable")
            + "</td><td>"
            + label
            + "</td></tr>"
        )
    body += "</table>"
    body += "<h2>Interpretation</h2><p>Compare similar flow requests, occupancy and heating/fan states. Startup and setpoint changes, pressure variation, sensor faults, overrides and an unverified airflow calibration can explain movement. Ten-minute checks use the preceding hour for hunting screening. A flag requires a stable requested flow, substantial damper reversals and repeated large airflow-error crossings. A missing flag is not proof of good tuning, particularly with missing data.</p><h2>Configuration and limits</h2><ul>"
    body += "".join("<li>" + html.escape(s) + "</li>" for s in cfg["limits"])
    body += (
        "</ul><p>"
        + html.escape(cfg.get("scheduled_start_note", ""))
        + '</p><p>Raw samples: <a href="samples.csv">samples.csv</a>; ten-minute checks: <a href="checkins.jsonl">checkins.jsonl</a>; analysis: <a href="analysis.json">analysis.json</a>.</p></html>'
    )
    (output / "report.html").write_text(body)
    (output / "report.html").chmod(0o600)
    with (output / "samples.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "utc",
                "group",
                "source",
                "point",
                "value",
                "quality_ok",
                "reliability",
                "flags",
                "errors",
            ]
        )
        for record in records:
            for alias, p in record["points"].items():
                writer.writerow(
                    [
                        record["utc"],
                        record["group"],
                        record["source"],
                        alias,
                        p.get("value"),
                        p["quality_ok"],
                        p.get("reliability"),
                        json.dumps(p.get("flags")),
                        "; ".join(p.get("errors", [])),
                    ]
                )
    (output / "samples.csv").chmod(0o600)


async def run(config_path, state_dir, sample_only=False):
    import fcntl

    cfg = load_config(config_path)
    digest = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = (state_dir / ("preflight.lock" if sample_only else "job.lock")).open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    state_path = state_dir / "state.json"
    state = (
        json.loads(state_path.read_text())
        if state_path.exists()
        else {"status": "scheduled", "config_sha256": digest}
    )
    if state["config_sha256"] != digest:
        raise ValueError("The retained observation configuration changed; use a separate job.")
    output = Path(cfg["output_directory"])
    if sample_only:
        output = state_dir / "preflight"
    elif state["status"] in ("complete", "incomplete"):
        return
    else:
        recovered = [
            recover_tail(p) for p in [state_dir / "samples.jsonl", output / "checkins.jsonl"]
        ]
        if any(recovered):
            state.setdefault("retained_interrupted_appends", []).extend(p for p in recovered if p)

    def save():
        if not sample_only:
            state["updated_utc"] = utc().isoformat()
            private_json(state_path, state)

    save()
    if not sample_only:
        render_report(cfg, state, read_records(state_dir / "samples.jsonl"), output)
        while utc() < stamp(cfg["collection_from"]):
            await asyncio.sleep(min(30, (stamp(cfg["collection_from"]) - utc()).total_seconds()))
    if not sample_only and (reason := window_end_reason(cfg, state, utc())):
        state["status"] = "incomplete"
        state["reason"] = reason
        save()
        render_report(cfg, state, read_records(state_dir / "samples.jsonl"), output)
        return
    bacnet = Bacnet(Store(state_dir / ("preflight-network" if sample_only else "network")))
    reader = ControllerWorkspace(bacnet, bacnet.store)
    next_read = {g["name"]: 0.0 for g in cfg["groups"]}
    latest, gate_count, first_gate = {}, 0, None
    last_air_read = None
    startup_keys = set(cfg["startup_fans"] + [cfg["startup_pressure"]])
    last_checkpoint = state.get("last_checkpoint_seconds", -600)
    records = read_records(state_dir / "samples.jsonl") if not sample_only else []
    try:
        await bacnet.connect(**cfg["interface"])
        state.pop("reason", None)
        while True:
            now = utc()
            if not sample_only and (reason := window_end_reason(cfg, state, now)):
                state.update(status="incomplete", reason=reason)
                save()
                render_report(cfg, state, records, output)
                return
            for group in cfg["groups"]:
                if not sample_only and window_end_reason(cfg, state, utc()):
                    break
                if time.monotonic() < next_read[group["name"]]:
                    continue
                read_started = time.monotonic()
                record = await read_group(reader, group)
                record["airflow_available"] = bool(
                    last_air_read
                    and (utc() - last_air_read).total_seconds() <= 150
                    and startup_ready(latest, cfg)
                )
                records.append(record)
                latest.update(record["points"])
                next_read[group["name"]] = read_started + group["interval_seconds"]
                path = state_dir / ("preflight-samples.jsonl" if sample_only else "samples.jsonl")
                with path.open("a") as stream:
                    stream.write(json.dumps(record, allow_nan=False) + "\n")
                path.chmod(0o600)
                if startup_keys <= set(record["points"]):
                    last_air_read = utc()
                if startup_keys <= set(record["points"]) and not state.get("monitor_started_utc"):
                    if startup_ready(record["points"], cfg):
                        gate_count += 1
                        first_gate = first_gate or record["utc"]
                    else:
                        gate_count, first_gate = 0, None
                    if gate_count >= cfg["startup_confirmations"]:
                        state["monitor_started_utc"] = first_gate
                        state["status"] = "monitoring"
            if sample_only:
                state = {**state, "status": "preflight-only"}
                render_report(cfg, state, records, output)
                private_json(
                    state_dir / "preflight-result.json",
                    {
                        "records": records,
                        "complete": all(
                            not r["errors"] and all(p["quality_ok"] for p in r["points"].values())
                            for r in records
                        ),
                    },
                )
                return
            state["status"] = (
                "monitoring" if state.get("monitor_started_utc") else "waiting-for-startup"
            )
            elapsed = (
                (utc() - stamp(state["monitor_started_utc"])).total_seconds()
                if state.get("monitor_started_utc")
                else 0
            )
            start = (
                stamp(state["monitor_started_utc"]).timestamp()
                if state.get("monitor_started_utc")
                else None
            )
            state["observed_target_seconds"] = (
                observed_seconds(
                    records,
                    cfg["target_name"] + ".damper",
                    start,
                    require_air=True,
                    required_aliases=[
                        cfg["target_name"] + ".flow",
                        cfg["target_name"] + ".flow_sp",
                    ],
                )
                if start
                else 0
            )
            if (
                state.get("monitor_started_utc")
                and elapsed - last_checkpoint >= cfg["checkpoint_seconds"]
            ):
                last_checkpoint = (
                    int(elapsed // cfg["checkpoint_seconds"]) * cfg["checkpoint_seconds"]
                )
                state["last_checkpoint_seconds"] = last_checkpoint
                check = {
                    "utc": utc().isoformat(),
                    "elapsed_seconds": elapsed,
                    "last_hour": {
                        name: metrics(records, name, max(start + 1200, utc().timestamp() - 3600))
                        for name in [cfg["target_name"], *cfg["reference_names"]]
                    },
                    "latest": latest,
                }
                with (output / "checkins.jsonl").open("a") as stream:
                    stream.write(json.dumps(check, allow_nan=False) + "\n")
                (output / "checkins.jsonl").chmod(0o600)
                render_report(cfg, state, records, output)
            if elapsed >= cfg["minimum_monitor_seconds"] and state[
                "observed_target_seconds"
            ] >= cfg.get("minimum_qualified_seconds", cfg["minimum_monitor_seconds"]):
                state["status"] = "complete"
            elif utc() >= stamp(cfg["hard_stop"]) or (
                not start and utc() >= stamp(cfg["startup_deadline"])
            ):
                state["status"] = "incomplete"
                state["reason"] = window_end_reason(cfg, state, utc())
            save()
            if state["status"] in ("complete", "incomplete"):
                render_report(cfg, state, records, output)
                return
            await asyncio.sleep(1)
    except Exception as exc:
        state.update(status="retry-needed", reason=(str(exc) or type(exc).__name__)[:300])
        save()
        if not sample_only:
            render_report(cfg, state, records, output)
        raise
    finally:
        await bacnet.disconnect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--sample-only", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    asyncio.run(run(args.config, args.state, args.sample_only))


if __name__ == "__main__":
    main()
