"""Real frozen builds and independent packaging refusal of stale browser assets."""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from scripts import build_portable as portable
from scripts import ui_build_provenance as proof

SOURCE = Path(__file__).resolve().parents[1]


def build(root, **extra):
    node = shutil.which("node")
    assert node, "The UI compiler acceptance tests require Node.js on PATH."
    return subprocess.run(
        [node, str(root / "scripts/build_ui.mjs")],
        cwd=root / "web",
        env=os.environ | extra,
        text=True,
        capture_output=True,
        timeout=60,
    )


def git(root, *args):
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        env=os.environ | {"GIT_CONFIG_GLOBAL": os.devnull},
    )


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("authored-ui-source")
    profile = json.loads((SOURCE / "scripts/ui_build_profile.json").read_text())
    for name in profile["fixed"]:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE / name, target)
    (root / "web/src").mkdir()
    (root / "web/src/main.ts").write_text(
        'document.querySelector("#root")!.textContent = "original authored UI";\n'
    )
    (root / "web/src/é😀.txt").write_text("Authored Unicode input; not a filesystem location.")
    (root / "web/index.html").write_text(
        '<html><div id="root"></div><script type="module" src="/src/main.ts"></script></html>'
    )
    (root / "web/node_modules").symlink_to(SOURCE / "web/node_modules", target_is_directory=True)
    result = build(root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert proof.validate(root)["profile"] == proof.PROFILE
    (root / ".gitignore").write_text("node_modules/\nweb/dist/\nweb/.bms-ui-*\n")
    (root / "backend/bms_tool").mkdir(parents=True)
    (root / "backend/bms_tool/__init__.py").write_text('"""Authored package fixture."""\n')
    (root / "pyproject.toml").write_text('[project]\nname="authored-ui-package"\nversion="0.0.0"\n')
    (root / "docs").mkdir()
    for name in portable.PUBLIC_DOCS:
        (root / "docs" / name).write_text("{}")
    for name in ("LICENSE", "NOTICE"):
        shutil.copy2(SOURCE / name, root / name)
    shutil.copytree(SOURCE / "third_party", root / "third_party")
    git(root, "init", "-q")
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Authored test",
        "-c",
        "user.email=test@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "Authored build inputs",
    )
    return root


@pytest.fixture
def workspace(built, tmp_path):
    target = tmp_path / "source"
    shutil.copytree(built, target, symlinks=True)
    return target


def document(root):
    return json.loads((root / "web/.bms-ui-build.json").read_text())


def store(root, data, reseal=True):
    if reseal:
        data["proof_sha256"] = proof.sha(
            proof.canonical({k: v for k, v in data.items() if k != "proof_sha256"})
        )
    (root / "web/.bms-ui-build.json").write_text(json.dumps(data, ensure_ascii=False))


def test_real_snapshot_proof_is_portable_bounded_and_contains_only_paths_hashes_and_versions(
    workspace,
):
    result = proof.validate(workspace)
    assert result["inputs"]["web/src/é😀.txt"]["sha256"] == proof.sha(
        (workspace / "web/src/é😀.txt").read_bytes()
    )
    assert result["outputs"] == proof.output_files(
        workspace, json.loads((workspace / "scripts/ui_build_profile.json").read_text())["limits"]
    )
    assert "index.html" in result["outputs"] and result["tools"]["node"]
    encoded = json.dumps(result)
    assert str(workspace) not in encoded and "original authored UI" not in encoded
    assert all("node_modules" not in name for name in result["inputs"])
    assert portable.ROOT != workspace


def test_prebuilt_validation_needs_neither_node_nor_installed_node_modules(workspace, monkeypatch):
    (workspace / "web/node_modules").unlink()
    monkeypatch.setenv("PATH", "")
    assert shutil.which("node") is None
    assert proof.validate(workspace)["profile"] == proof.PROFILE


@pytest.mark.parametrize(
    "fault",
    [
        "edit",
        "add",
        "delete",
        "rename",
        "new-optional",
        "asset",
        "extra-asset",
        "missing-asset",
        "missing-proof",
    ],
)
def test_stale_inputs_or_assets_refuse_before_wheel_staging_even_allow_dirty(
    workspace, monkeypatch, fault
):
    source = workspace / "web/src/main.ts"
    assets = workspace / "web/dist/assets"
    if fault == "edit":
        source.write_text('document.title="changed after build";')
    elif fault == "add":
        (workspace / "web/src/new.ts").write_text("export const added = true;")
    elif fault == "delete":
        source.unlink()
    elif fault == "rename":
        source.rename(source.with_name("renamed.ts"))
    elif fault == "new-optional":
        (workspace / "web/.env.production").write_text("VITE_AUTHORED_CHOICE=updated")
    elif fault == "asset":
        next(assets.glob("*.js")).write_text("changed after compilation")
    elif fault == "extra-asset":
        (assets / "extra.js").write_text("unexpected output")
    elif fault == "missing-asset":
        next(assets.glob("*.js")).unlink()
    else:
        (workspace / "web/.bms-ui-build.json").unlink()
    monkeypatch.setattr(portable, "ROOT", workspace)
    output = workspace / "wheel-output"
    with pytest.raises(ValueError, match="[Rr]ebuild"):
        portable.build(output, allow_dirty=True)
    assert not output.exists()


@pytest.mark.parametrize(
    "fault",
    [
        "profile",
        "recipe",
        "mode",
        "extra",
        "seal",
        "boolean-size",
        "float-size",
        "digest",
        "unsafe-path",
        "tool-version",
        "environment",
    ],
)
def test_altered_or_unknown_proof_cannot_acquire_packaging_authority(workspace, fault):
    data = document(workspace)
    if fault == "profile":
        data["profile"] = "future/99"
    elif fault == "recipe":
        data["recipe"] = "untracked-postbuild/1"
    elif fault == "mode":
        data["mode"] = "development"
    elif fault == "extra":
        data["trusted"] = True
    elif fault == "seal":
        data["proof_sha256"] = "0" * 64
    elif fault == "boolean-size":
        data["inputs"]["web/index.html"]["bytes"] = True
    elif fault == "float-size":
        data["inputs"]["web/index.html"]["bytes"] = 1.0
    elif fault == "digest":
        data["outputs"]["index.html"]["sha256"] = "invalid"
    elif fault == "unsafe-path":
        data["inputs"]["../outside"] = data["inputs"]["web/index.html"]
    elif fault == "tool-version":
        data["tools"]["vite"] = "0.0.0"
    else:
        data["environment"]["VITE_UNKNOWN"] = "0" * 64
    store(workspace, data, reseal=fault != "seal")
    with pytest.raises(ValueError, match="[Rr]ebuild"):
        proof.validate(workspace)


def test_duplicate_keys_symlinks_and_changed_environment_are_not_proofs(workspace, monkeypatch):
    path = workspace / "web/.bms-ui-build.json"
    original = path.read_text()
    path.write_text(
        original.replace('"mode": "production"', '"mode": "production", "mode": "production"')
    )
    with pytest.raises(ValueError, match="Duplicate"):
        proof.validate(workspace)
    path.write_text(original)
    monkeypatch.setenv("VITE_AUTHORED_OPTION", "authored-change")
    with pytest.raises(ValueError, match="environment changed"):
        proof.validate(workspace)
    monkeypatch.delenv("VITE_AUTHORED_OPTION")
    copied = workspace / "proof-copy.json"
    copied.write_text(original)
    path.unlink()
    path.symlink_to(copied)
    with pytest.raises(ValueError, match="unsupported"):
        proof.validate(workspace)


def test_failed_typecheck_invalidates_previous_proof_and_preserves_previous_assets(workspace):
    old = (workspace / "web/dist/index.html").read_bytes()
    (workspace / "web/src/main.ts").write_text("const broken: number = ;")
    result = build(workspace)
    assert result.returncode != 0 and "compiler failed" in result.stderr
    assert not (workspace / "web/.bms-ui-build.json").exists()
    assert (workspace / "web/dist/index.html").read_bytes() == old
    with pytest.raises(ValueError, match="[Rr]ebuild"):
        proof.validate(workspace)


def test_source_and_profile_symlinks_are_rejected_before_reading_outside_inputs(workspace):
    secret = workspace / "authored-outside.json"
    secret.write_text('"AUTHORED_PRIVATE_SENTINEL"')
    source = workspace / "web/src/main.ts"
    source.unlink()
    source.symlink_to(secret)
    result = build(workspace)
    assert result.returncode != 0 and "must not be symlinks" in result.stderr
    assert "AUTHORED_PRIVATE_SENTINEL" not in result.stdout + result.stderr
    definition = workspace / "scripts/ui_build_profile.json"
    definition.unlink()
    definition.symlink_to(secret)
    result = build(workspace)
    assert result.returncode != 0 and "Unsupported UI build input profile" in result.stderr
    assert "AUTHORED_PRIVATE_SENTINEL" not in result.stdout + result.stderr


def test_optional_environment_input_is_bound_without_recording_raw_values(workspace):
    value = "AUTHORED_PUBLIC_FRONTEND_CHOICE"
    (workspace / "web/.env.production").write_text("VITE_AUTHORED_OPTION=" + value)
    result = build(workspace)
    assert result.returncode == 0, result.stdout + result.stderr
    record = proof.validate(workspace)
    assert "web/.env.production" in record["inputs"]
    assert value not in json.dumps(record)


@pytest.mark.parametrize("limit", [True, 2 * 1024 * 1024])
def test_profile_cannot_override_proof_bounds_with_boolean_or_oversized_limit(workspace, limit):
    path = workspace / "scripts/ui_build_profile.json"
    data = json.loads(path.read_text())
    data["limits"]["proof_bytes"] = limit
    path.write_text(json.dumps(data))
    result = build(workspace)
    assert result.returncode != 0 and "profile shape or limits" in result.stderr
    with pytest.raises(ValueError, match="profile shape or limits"):
        proof.validate(workspace)


def gated_build(root, tmp_path):
    # Only this authored config bypasses typing to inject filesystem gates. The
    # actual application source still passes its unchanged TypeScript compiler.
    (root / "web/vite.config.ts").write_text("""// @ts-nocheck
import fs from "node:fs";
export default async () => {
 fs.writeFileSync(process.env.BMS_AUTHORED_BUILD_READY, "ready");
 while (!fs.existsSync(process.env.BMS_AUTHORED_BUILD_RELEASE)) await new Promise(r=>setTimeout(r,10));
 return {};
};
""")
    ready, release = tmp_path / "ready", tmp_path / "release"
    child = subprocess.Popen(
        [shutil.which("node"), str(root / "scripts/build_ui.mjs")],
        cwd=root / "web",
        env=os.environ
        | {"BMS_AUTHORED_BUILD_READY": str(ready), "BMS_AUTHORED_BUILD_RELEASE": str(release)},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 10
    while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    if not ready.exists():
        child.terminate()
        output = child.communicate(timeout=10)
        pytest.fail("Authored build gate did not start: " + str(output))
    return child, release


@pytest.mark.parametrize("aba", [False, True])
def test_compilation_uses_frozen_bytes_and_changed_source_never_receives_a_proof(
    workspace, tmp_path, aba
):
    child, release = gated_build(workspace, tmp_path)
    source = workspace / "web/src/main.ts"
    original = source.read_bytes()
    try:
        source.write_text(
            'document.querySelector("#root")!.textContent="edited during compilation";'
        )
        if aba:
            source.write_bytes(original)
        release.write_text("continue")
        stdout, stderr = child.communicate(timeout=30)
        if aba:
            assert child.returncode == 0, stdout + stderr
            proof.validate(workspace)
            scripts = "\n".join(p.read_text() for p in (workspace / "web/dist/assets").glob("*.js"))
            assert "original authored UI" in scripts and "edited during compilation" not in scripts
        else:
            assert child.returncode != 0 and "inputs changed during compilation" in stderr
            assert not (workspace / "web/.bms-ui-build.json").exists()
    finally:
        release.write_text("continue")
        if child.poll() is None:
            child.terminate()
            child.communicate(timeout=10)


@pytest.mark.parametrize("change", ["input", "asset"])
def test_packager_rechecks_bytes_after_preflight_before_invoking_pip(
    workspace, monkeypatch, change
):
    monkeypatch.setattr(portable, "ROOT", workspace)
    original = shutil.copy2
    changed = False

    def copy(*args, **kwargs):
        nonlocal changed
        result = original(*args, **kwargs)
        if not changed:
            changed = True
            target = workspace / ("web/src/main.ts" if change == "input" else "web/dist/index.html")
            target.write_text("changed during packaging")
        return result

    original_run = subprocess.run

    def forbidden(command, *args, **kwargs):
        if "pip" in command and "wheel" in command:
            pytest.fail("Packaging invoked pip after source/output drift")
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(portable.shutil, "copy2", copy)
    monkeypatch.setattr(portable.subprocess, "run", forbidden)
    with pytest.raises(ValueError, match="[Rr]ebuild"):
        portable.build(workspace / "output", allow_dirty=True)
