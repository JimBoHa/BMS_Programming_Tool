"""Strict isolated browser-fixture bootstrap; no installed application overlays."""

import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
from pathlib import Path, PurePosixPath

EXPECTED_PROFILE = "39f2f931b40402dc1e50240a5d5b1a23e85f860ce9ef3eb44bd1fa59ced88058"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def required_path(name):
    value = os.environ.get(name, "")
    if not value or not Path(value).is_absolute():
        raise ValueError(name + " requires an explicit absolute path")
    return Path(value).resolve()


assert sys.flags.isolated and sys.flags.no_site, "Launch with -I -S"
initial_path = list(sys.path)
identity = required_path("BMS_UI_POWER_IDENTITY_PATH")
post_identity = Path(str(identity) + ".post.json")
if os.environ.get("BMS_SERVER_IDENTITY_PATH"):
    assert identity != Path(os.environ["BMS_SERVER_IDENTITY_PATH"]).resolve()
    assert post_identity != Path(os.environ["BMS_SERVER_IDENTITY_PATH"]).resolve()
assert not identity.exists() and not post_identity.exists(), "Never overwrite an existing identity"
helper = required_path("BMS_UI_POWER_HELPER_PATH")
assert helper.is_file() and helper.name == "operation_power_server.py"
dependency = required_path("BMS_UI_POWER_DEPENDENCY_ROOT")
assert dependency.is_dir()
installed = os.environ.get("BMS_TEST_INSTALLED_TARGET", "").strip()
manifest_path, wheel_sha, expected_payload, expected_ui = None, None, {}, {}

if installed:
    root = Path(installed).resolve()
    manifest_path = required_path("BMS_TEST_INSTALLED_MANIFEST")
    manifest = json.loads(manifest_path.read_bytes())
    assert Path(manifest["target"]).resolve() == root
    expected_source = os.environ.get("BMS_EXPECTED_SOURCE")
    assert expected_source and manifest["source_commit"] == expected_source
    wheel_sha = manifest["wheel_sha256"]
    assert isinstance(wheel_sha, str) and len(wheel_sha) == 64
    expected_payload, expected_ui = manifest["payload"], manifest["ui_files"]
    assert expected_payload and expected_ui
else:
    root = required_path("BMS_UI_POWER_BACKEND_ROOT")
    assert (root / "bms_tool/app.py").is_file()
    expected_source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root.parent, text=True
    ).strip()
    if os.environ.get("BMS_EXPECTED_SOURCE"):
        assert os.environ["BMS_EXPECTED_SOURCE"] == expected_source
    expected_payload = {
        p.relative_to(root).as_posix(): digest(p) for p in sorted((root / "bms_tool").rglob("*.py"))
    }

assert not Path.cwd().resolve().is_relative_to(helper.parents[2]), (
    "Fixture cwd must be outside checkout"
)
# -I -S excludes PYTHONPATH/site/.pth processing. Only these explicit roots
# follow the interpreter's original stdlib paths. The installed root wins.
sys.path[:] = [str(root), *initial_path, str(dependency)]


def verify_payload():
    for relative, checksum in expected_payload.items():
        logical = PurePosixPath(relative)
        assert not logical.is_absolute() and ".." not in logical.parts
        path = root.joinpath(*logical.parts)
        assert path.is_file() and not path.is_symlink()
        assert path.resolve().is_relative_to(root)
        assert digest(path) == checksum, relative
    actual_python = {p.relative_to(root).as_posix() for p in (root / "bms_tool").rglob("*.py")}
    expected_python = {
        name for name in expected_payload if name.startswith("bms_tool/") and name.endswith(".py")
    }
    assert actual_python == expected_python, "Unexpected application source file"


verify_payload()  # Hash original whole-wheel payload before importing app code.
from bms_tool import operation_power, resources  # noqa: E402 - verified explicit roots above

assert operation_power.PROFILE_SHA == EXPECTED_PROFILE
assert (
    hashlib.sha256(
        json.dumps(operation_power.PROFILE, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    == EXPECTED_PROFILE
)
if installed:
    assert not resources.source_checkout()
    distribution = json.loads((root / "bms_tool/data/distribution.json").read_bytes())
    assert distribution["source_commit"] == expected_source and not distribution["source_dirty"]
    assert distribution["ui_files"] == expected_ui
else:
    assert resources.source_checkout()
    expected_ui = {
        p.relative_to(resources.web_directory()).as_posix(): digest(p)
        for p in resources.web_directory().rglob("*")
        if p.is_file()
    }
    assert expected_ui

spec = importlib.util.spec_from_file_location("_bms_owned_operation_power_fixture", helper)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
uvicorn = importlib.import_module("uvicorn")


def proof(stage):
    verify_payload()
    web = resources.web_directory().resolve()
    if installed:
        assert web.is_relative_to(root) and not resources.source_checkout()
    actual_ui = {p.relative_to(web).as_posix(): digest(p) for p in web.rglob("*") if p.is_file()}
    assert actual_ui == expected_ui
    loaded = {}
    for name, module in list(sys.modules.items()):
        if name != "bms_tool" and not name.startswith("bms_tool."):
            continue
        path = Path(module.__file__).resolve()
        assert path.is_relative_to(root), name
        relative = path.relative_to(root).as_posix()
        assert relative in expected_payload and digest(path) == expected_payload[relative], name
        loaded[name] = str(path)
    assert loaded and operation_power.PROFILE_SHA == EXPECTED_PROFILE
    return {
        "status": "passed",
        "stage": stage,
        "mode": "installed" if installed else "source",
        "source_commit": expected_source,
        "wheel_sha256": wheel_sha,
        "target": str(root),
        "cwd": str(Path.cwd()),
        "dependency_root": str(dependency),
        "isolated": bool(sys.flags.isolated),
        "no_site": bool(sys.flags.no_site),
        "no_pth_processing": True,
        "ignored_inherited_PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        "source_checkout": bool(resources.source_checkout()),
        "web_directory": str(web),
        "payload_members_verified": len(expected_payload),
        "ui_files_verified": len(actual_ui),
        "loaded_application_modules": loaded,
        "profile_sha256": EXPECTED_PROFILE,
        "fixture_helper": str(helper),
        "fixture_helper_sha256": digest(helper),
        "manifest": str(manifest_path) if manifest_path else None,
        "fixture_injection": "Owned simulated power provider and private fixture controls; actual application routes/assets. No OS power requests or controller operations.",
    }


def publish(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(json.dumps(value, indent=2) + "\n")


publish(identity, proof("startup"))
port = int(os.environ["BMS_UI_POWER_SERVER_PORT"])
assert 1 <= port <= 65535


def finished_signal(signum, frame):
    # Uvicorn captures these signals for graceful server shutdown, restores
    # the original handler, then re-emits. Raise through our finally instead
    # of default SIGTERM process termination before post-identity publication.
    raise SystemExit(0)


signal.signal(signal.SIGTERM, finished_signal)
signal.signal(signal.SIGINT, finished_signal)
try:
    uvicorn.run(fixture.app, host="127.0.0.1", port=port, access_log=False)
finally:
    try:
        final = proof("post_shutdown")
    except BaseException as exc:
        publish(post_identity, {"status": "failed", "stage": "post_shutdown", "error": repr(exc)})
        raise
    else:
        publish(post_identity, final)
