"""Qualify one immutable native-order cohort in source or installed form.

All protocol peers are authored localhost fixtures. No site credentials or private
controller files are accepted. Failed artifacts remain and no test is retried.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = [
    "native_order_recovery_proposal",
    "native_order_result_match",
    "native_order_transfer",
    "native_execution_order",
    "native_default_batch_result_match",
    "native_backup_records",
    "native_applications",
    "native_application_api",
    "native_order_capabilities",
    "distribution_resources",
]
BROWSER = [
    "native-order-recovery-proposal",
    "native-order-result-match",
    "native-order-transfer",
    "native-order-transfer-lifecycle",
    "native-execution-order",
    "native-order-capabilities",
    "native-default-batch-result-match",
    "native-capacity",
    "change-ledger",
]
PREFILL = ["connections-prefill-queue", "connections-hydration"]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def run(command, output, *, cwd=ROOT, env=None):
    print(f"Running {output.name}", flush=True)
    with output.open("x") as stream:
        result = subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"Qualification command failed ({result.returncode}); see {output}.")


def import_proof(phase):
    """Pytest plugin guard; all application modules must come from the chosen build."""
    target = Path(os.environ["BMS_QUALIFIED_PACKAGE"]).resolve()
    rows = []
    for name, module in sorted(sys.modules.copy().items()):
        if name != "bms_tool" and not name.startswith("bms_tool."):
            continue
        file = getattr(module, "__file__", None)
        if file:
            path = Path(file).resolve()
            assert path.is_relative_to(target), f"{name} imported outside the qualified build."
            rows.append({"module": name, "path": path.relative_to(target).as_posix()})
    write(Path(os.environ["BMS_QUALIFIED_IMPORTS"]).with_name(f"imports-{phase}.json"), rows)


def pytest_collection_finish(session):
    import_proof("collection")


def pytest_sessionfinish(session, exitstatus):
    import_proof("finish")


def serve(port):
    import bms_tool
    import uvicorn
    from bms_tool import resources
    from bms_tool.app import create_app

    target = Path(os.environ["BMS_QUALIFIED_PACKAGE"]).resolve()
    assert Path(bms_tool.__file__).resolve().is_relative_to(target)
    if os.environ["BMS_QUALIFIED_MODE"] == "installed":
        assert not resources.source_checkout()
        manifest = json.loads((target / "bms_tool/data/distribution.json").read_text())
        assert manifest["source_commit"] == os.environ["BMS_EXPECTED_SOURCE"]
        assert resources.web_directory().is_relative_to(target)
    uvicorn.run(create_app(), host="127.0.0.1", port=port, access_log=False)


def wheel_proof(output, head, env):
    from ui_build_provenance import validate

    run(
        [sys.executable, "scripts/build_portable.py", "--output", str(output / "wheels")],
        output / "wheel-build.log",
        env=env,
    )
    (wheel,) = (output / "wheels").glob("*.whl")
    target = output / "installed"
    with zipfile.ZipFile(wheel) as archive:
        manifest = json.loads(archive.read("bms_tool/data/distribution.json"))
        assert manifest["source_commit"] == head and manifest["source_dirty"] is False
        assert manifest["ui_build"] == validate(ROOT)
        modules = [p for p in git("ls-files", "backend/bms_tool").splitlines() if p.endswith(".py")]
        for name in modules:
            assert archive.read(name.removeprefix("backend/")) == (ROOT / name).read_bytes(), name
        assets = [p for p in (ROOT / "web/dist").rglob("*") if p.is_file()]
        for file in assets:
            name = file.relative_to(ROOT / "web/dist").as_posix()
            raw = file.read_bytes()
            assert archive.read("bms_tool/web_assets/" + name) == raw
            assert manifest["ui_files"][name] == hashlib.sha256(raw).hexdigest()
        assert set(manifest["ui_files"]) == {
            file.relative_to(ROOT / "web/dist").as_posix() for file in assets
        }
        for name in ("capabilities", "requirements", "references"):
            assert (
                archive.read(f"bms_tool/data/app_docs/{name}.json")
                == (ROOT / f"docs/{name}.json").read_bytes()
            )
        for name in (
            "cafReferenceLabels.json",
            "cafReferenceLabels-LICENSE.txt",
            "cafReferenceLabels-NOTICE.txt",
        ):
            assert (
                archive.read("bms_tool/data/" + name)
                == (ROOT / "backend/bms_tool/data" / name).read_bytes()
            )
        legal = [
            "LICENSE",
            "NOTICE",
            *[
                "third_party/" + name
                for name in (
                    "OCT-LICENSE.txt",
                    "Sedona-LICENSE.md",
                    "Temco-T3000-LICENSE.txt",
                    "pybog-LICENSE.txt",
                    "web-NOTICES.txt",
                    "Tcl-LICENSE.txt",
                    "Tk-LICENSE.txt",
                )
            ],
        ]
        for name in legal:
            assert archive.read("bms_tool/data/legal/" + name) == (ROOT / name).read_bytes()
        assert not any(
            "local-reports" in name
            or "/.state/" in name
            or "Manual_Library" in name
            or "tests/" in name
            for name in archive.namelist()
        )
        archive.extractall(target)
    proof = {
        "commit": head,
        "python_modules_exact": len(modules),
        "ui_files_exact": len(assets),
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "ui_proof_sha256": manifest["ui_build"]["proof_sha256"],
        "public_metadata_exact": 3,
        "reference_data_files_exact": 3,
        "bundled_legal_files_exact": len(legal),
    }
    write(output / "wheel-proof.json", proof)
    return target


def backend(output, env):
    files = ["tests/test_" + name + ".py" for name in BACKEND]
    config = output / "pytest.ini"
    config.write_text("[pytest]\nasyncio_mode = auto\n")
    args = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--rootdir",
        str(ROOT),
        "-c",
        str(config),
        "-p",
        "qualify_native_order",
        *files,
    ]
    run([*args, "--collect-only"], output / "backend-collection.log", env=env)
    planned = [
        line
        for line in (output / "backend-collection.log").read_text().splitlines()
        if line.startswith("tests/") and "::" in line
    ]
    assert len(planned) == len(set(planned)) == 326
    write(output / "backend-planned-case-ids.json", planned)
    run([*args, "--junitxml=" + str(output / "backend.xml")], output / "backend.log", env=env)
    root = ET.parse(output / "backend.xml").getroot()
    assert all(
        int(s.get(k, 0)) == 0
        for s in root.iter("testsuite")
        for k in ("failures", "errors", "skipped")
    )
    actual = [
        s.get("classname").replace(".", "/") + ".py::" + s.get("name")
        for s in root.iter("testcase")
    ]
    assert len(actual) == 326 and set(actual) == set(planned)
    return {"passed": len(actual), "planned_case_ids": planned, "retries": 0, "skips": 0}


def browser_group(output, env, mode, browser, number, name):
    group = output / f"browser-{number:02}-{name}"
    group.mkdir()
    state = group / "state"
    config = ROOT / "web" / f".bms-ui-qualification-{mode}-{browser}-{number}.config.ts"
    settings = {
        "testDir": "./tests",
        "fullyParallel": False,
        "workers": 1,
        "maxFailures": 1,
        "retries": 0,
        "timeout": 30000,
        "projects": [{"name": browser, "use": {"browserName": browser}}],
        "use": {
            "baseURL": "http://127.0.0.1:8766",
            "viewport": {"width": 1440, "height": 1000},
            "trace": "retain-on-failure",
        },
        "outputDir": str(group / "artifacts"),
        "reporter": [["line"], ["json", {"outputFile": str(group / "results.json")}]],
        "webServer": {
            "command": "../.venv/bin/python "
            + shlex.quote(str(Path(__file__).resolve()))
            + " --serve 8766",
            "env": {
                **{
                    key: value
                    for key, value in env.items()
                    if key == "PYTHONPATH"
                    or key.startswith("BMS_QUALIFIED_")
                    or key in ("BMS_EXPECTED_SOURCE", "BMS_TEST_INSTALLED_TARGET")
                },
                "BMS_STUDIO_DATA": str(state),
                "BMS_TEST_COMPILER_STATE": str(state),
            },
            "url": "http://127.0.0.1:8766/api/session",
            "reuseExistingServer": False,
            "timeout": 20000,
        },
    }
    config.write_text(
        "import {defineConfig} from '@playwright/test';\nprocess.env.BMS_TEST_COMPILER_STATE="
        + json.dumps(str(state))
        + ";\nexport default defineConfig("
        + json.dumps(settings)
        + ");\n"
    )
    args = [
        "npx",
        "playwright",
        "test",
        "--config",
        config.name,
        r"(^|/)" + name + r"(\.unit)?\.spec\.ts$",
    ]
    try:
        run([*args, "--list"], group / "collection.log", cwd=ROOT / "web", env=env)
        (group / "results.json").rename(group / "collection.json")
        planned = json.loads((group / "collection.json").read_text())
        run(args, group / "run.log", cwd=ROOT / "web", env=env)
        result = json.loads((group / "results.json").read_text())
    finally:
        config.unlink(missing_ok=True)

    def ids(data, check=False):
        rows = []

        def walk(suite):
            for spec in suite.get("specs", []):
                rows.append((spec["file"], spec["title"]))
                if check:
                    assert spec["ok"] and len(spec["tests"]) == 1
                    test = spec["tests"][0]
                    assert test["expectedStatus"] == "passed" and len(test["results"]) == 1
                    assert test["results"][0]["status"] == "passed" and not test["results"][0].get(
                        "errors"
                    )
            for child in suite.get("suites", []):
                walk(child)

        for suite in data["suites"]:
            walk(suite)
        return rows

    actual, expected = ids(result, True), ids(planned)
    assert actual == expected and len(actual) == len(set(actual))
    assert (
        all(result["stats"][key] == 0 for key in ("unexpected", "skipped", "flaky"))
        and not result["errors"]
    )
    return {"spec": name, "passed": len(actual), "case_ids": actual}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["source", "installed"])
    parser.add_argument("--browser", choices=["chromium", "webkit"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--serve", type=int)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve)
        return
    assert args.mode and args.browser and args.output
    head = git("rev-parse", "HEAD")
    assert not git("status", "--porcelain"), "Qualification requires a clean committed checkout."
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    target = wheel_proof(output, head, env) if args.mode == "installed" else ROOT / "backend"
    env.update(
        PYTHONPATH=os.pathsep.join([str(target), str(ROOT / "scripts"), str(ROOT)]),
        BMS_QUALIFIED_PACKAGE=str(target),
        BMS_QUALIFIED_MODE=args.mode,
        BMS_QUALIFIED_IMPORTS=str(output / "imports.json"),
        BMS_EXPECTED_SOURCE=head,
    )
    if args.mode == "installed":
        env["BMS_TEST_INSTALLED_TARGET"] = str(target)
    else:
        env.pop("BMS_TEST_INSTALLED_TARGET", None)
    report = {
        "commit": head,
        "tree": git("rev-parse", "HEAD^{tree}"),
        "mode": args.mode,
        "browser": args.browser,
        "platform": sys.platform,
        "groups": [],
        "backend": None,
        "no_site_or_private_files": True,
        "retries": 0,
        "skips": 0,
        "complete": False,
        "planned_backend_modules": BACKEND,
        "planned_backend_cases_per_build": 326,
        "planned_browser_groups": BROWSER,
        "planned_browser_cases_per_matrix": 425,
        "connection_prefill": [],
        "planned_connection_prefill_cases_per_matrix": 6,
    }
    write(output / "qualification.json", report)
    for number, name in enumerate(PREFILL, 100):
        report["connection_prefill"].append(
            browser_group(output, env, args.mode, args.browser, number, name)
        )
        assert git("rev-parse", "HEAD") == head and not git("status", "--porcelain")
        write(output / "qualification.json", report)
    assert sum(group["passed"] for group in report["connection_prefill"]) == 6
    if args.browser == "chromium":
        report["backend"] = backend(output, env)
    for number, name in enumerate(BROWSER, 1):
        report["groups"].append(browser_group(output, env, args.mode, args.browser, number, name))
        assert git("rev-parse", "HEAD") == head and not git("status", "--porcelain")
        write(output / "qualification.json", report)
    assert sum(group["passed"] for group in report["groups"]) == 425
    report["complete"] = True
    write(output / "qualification.json", report)
    print(json.dumps({k: v for k, v in report.items() if k not in ("groups", "backend")}))


if __name__ == "__main__":
    main()
