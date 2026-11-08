"""Qualify one frozen read-only engineering slice in source and installed form."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import qualify_native_order as support

ROOT = Path(__file__).resolve().parents[1]
BACKEND = [
    "jci_source_inspection",
    "formats_caf",
    "controller_application",
    "program_source",
    "caf_validation",
    "caf_zip_attributes",
    "distribution_resources",
]
BACKEND_CASES = 278
BROWSER_CASES = 41


def backend(output, env):
    # Exercise the existing optional-directory cases rather than skipping them.
    # These are explicitly authored originals, not private building archives.
    samples = output / "authored-caf-regressions"
    code = """
from pathlib import Path
import hashlib,json,os,sys
import bms_tool
from tests.test_caf_zip_attributes import FAMILIES,original,repack
from qualify_native_order import import_proof
assert Path(bms_tool.__file__).resolve().is_relative_to(Path(os.environ['BMS_QUALIFIED_PACKAGE']).resolve())
samples=Path(sys.argv[1]);samples.mkdir()
fingerprints={}
for name in FAMILIES:
    raw=repack(original(name),attributes=0)
    path=samples/(name+'.caf');path.write_bytes(raw)
    fingerprints[path.name]=hashlib.sha256(raw).hexdigest()
(samples.parent/'authored-fixture-hashes.json').write_text(json.dumps(fingerprints,indent=2)+'\\n')
import_proof('authored-fixtures')
"""
    support.run(
        [sys.executable, "-c", code, str(samples)], output / "authored-fixtures.log", env=env
    )
    fingerprints = json.loads((output / "authored-fixture-hashes.json").read_text())
    env = {**env, "BMS_TEST_CAF_DIR": str(samples)}
    support.write(
        output / "authored-directory-fixtures.json",
        {
            "origin": "independently authored regression originals",
            "private_or_manufacturer_reference": False,
            "sha256": fingerprints,
        },
    )
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
        *["tests/test_" + name + ".py" for name in BACKEND],
    ]
    support.run([*args, "--collect-only"], output / "backend-collection.log", env=env)
    planned = [
        line
        for line in (output / "backend-collection.log").read_text().splitlines()
        if line.startswith("tests/") and "::" in line
    ]
    assert len(planned) == len(set(planned)) == BACKEND_CASES
    support.write(output / "backend-planned-case-ids.json", planned)
    support.run(
        [*args, "--junitxml=" + str(output / "backend.xml")], output / "backend.log", env=env
    )
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
    assert len(actual) == len(set(actual)) == BACKEND_CASES and set(actual) == set(planned)
    assert sum(name.startswith("tests/test_jci_source_inspection.py::") for name in actual) == 51
    assert all(
        hashlib.sha256((samples / name).read_bytes()).hexdigest() == value
        for name, value in fingerprints.items()
    )
    return {
        "passed": len(actual),
        "new_source_cases": 51,
        "case_ids": actual,
        "retries": 0,
        "skips": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("source", "installed"), required=True)
    parser.add_argument("--browser", choices=("chromium", "webkit"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    head = support.git("rev-parse", "HEAD")
    assert not support.git("status", "--porcelain")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    target = (
        support.wheel_proof(output, head, env) if args.mode == "installed" else ROOT / "backend"
    )
    catalog = Path("bms_tool/data/jciEngineeringInventory.json")
    assert (target / catalog).read_bytes() == (ROOT / "backend" / catalog).read_bytes()
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
        "profile": "jci-engineering-qualification/1",
        "commit": head,
        "tree": support.git("rev-parse", "HEAD^{tree}"),
        "mode": args.mode,
        "browser": args.browser,
        "backend": None,
        "groups": [],
        "new_catalog_bytes_exact": True,
        "complete": False,
        "retries": 0,
        "skips": 0,
        "no_site_or_private_sources": True,
    }
    support.write(output / "qualification.json", report)
    report["groups"].append(
        support.browser_group(output, env, args.mode, args.browser, 1, "jci-engineering")
    )
    assert report["groups"][0]["passed"] == BROWSER_CASES
    if args.browser == "chromium":
        report["backend"] = backend(output, env)
    assert support.git("rev-parse", "HEAD") == head and not support.git("status", "--porcelain")
    report["complete"] = True
    support.write(output / "qualification.json", report)
    print(json.dumps({k: v for k, v in report.items() if k not in ("groups", "backend")}))


if __name__ == "__main__":
    main()
