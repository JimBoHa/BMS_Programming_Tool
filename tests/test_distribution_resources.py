"""A wheel must serve its UI/metadata without a source checkout or writable code."""

import json
import os
import re
import subprocess
import sys
import venv
import zipfile
from pathlib import Path

import pytest
from bms_tool import resources


def package_paths(tmp_path, monkeypatch, *, checkout=False):
    source = tmp_path / "root"
    package = source / "backend" / "bms_tool" if checkout else source / "installed" / "bms_tool"
    package.mkdir(parents=True)
    monkeypatch.setattr(resources, "SOURCE", source)
    monkeypatch.setattr(resources, "PACKAGE", package)
    monkeypatch.delenv("BMS_STUDIO_DATA", raising=False)
    if checkout:
        (source / "pyproject.toml").write_text("[project]\nname='test'\n")
    return source, package


def test_package_ignores_unrelated_neighboring_web_and_docs(tmp_path, monkeypatch):
    source, package = package_paths(tmp_path, monkeypatch)
    (source / "web" / "dist").mkdir(parents=True)
    (source / "web" / "dist" / "index.html").write_text("wrong application")
    (source / "docs").mkdir()
    (source / "docs" / "capabilities.json").write_text('{"wrong":true}')
    (source / "pyproject.toml").write_text("unrelated project")
    assert resources.web_directory() is None
    with pytest.raises(ValueError, match="missing"):
        resources.public_document("capabilities.json")
    assets = package / "web_assets"
    assets.mkdir()
    (assets / "index.html").write_text("correct application")
    docs = package / "data" / "app_docs"
    docs.mkdir(parents=True)
    (docs / "capabilities.json").write_text('{"correct":true}')
    assert resources.web_directory() == assets
    assert resources.public_document("capabilities.json") == {"correct": True}
    with pytest.raises(ValueError, match="Unknown"):
        resources.public_document("../../secrets")


def test_checkout_keeps_existing_state_and_resource_precedence(tmp_path, monkeypatch):
    source, package = package_paths(tmp_path, monkeypatch, checkout=True)
    assert resources.state_directory() == source / ".state"
    (source / "docs").mkdir()
    (source / "docs" / "requirements.json").write_text('["checkout"]')
    assert resources.public_document("requirements.json") == ["checkout"]
    monkeypatch.setenv("BMS_STUDIO_DATA", str(tmp_path / "chosen"))
    assert resources.state_directory() == tmp_path / "chosen"
    assert resources.web_directory() is None
    built = source / "web" / "dist"
    built.mkdir(parents=True)
    assert resources.web_directory() is None  # An empty directory is not a built UI.
    (built / "index.html").write_text("source UI")
    assert resources.web_directory() == built
    assert resources.public_document("references.json") == []


@pytest.mark.parametrize("platform", ["darwin", "win32", "linux"])
def test_installed_state_uses_user_data_directory(tmp_path, monkeypatch, platform):
    _, package = package_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(resources.sys, "platform", platform)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    expected = {
        "darwin": tmp_path / "home/Library/Application Support/BMS Studio",
        "win32": tmp_path / "home/AppData/Local/BMS Studio",
        "linux": tmp_path / "home/.local/share/bms-studio",
    }
    assert resources.state_directory() == expected[platform]
    assert package not in resources.state_directory().parents


def test_built_wheel_installs_and_serves_without_source_checkout(tmp_path):
    root = Path(__file__).resolve().parents[1]
    if not (root / "web/dist/index.html").is_file():
        pytest.skip("Build the UI first for the installed-wheel acceptance check.")
    builder = tmp_path / "builder"
    venv.EnvBuilder(with_pip=True).create(builder)
    builder_python = builder / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    # Python 3.11 may seed setuptools; newer venvs normally contain only pip.
    # Exercise the same missing-backend condition on every supported version.
    subprocess.run(
        [str(builder_python), "-m", "pip", "uninstall", "--yes", "setuptools", "wheel"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    no_build_tools = (
        "import importlib.util; "
        "assert importlib.util.find_spec('setuptools') is None; "
        "assert importlib.util.find_spec('wheel') is None"
    )
    subprocess.run([str(builder_python), "-I", "-c", no_build_tools], check=True)
    output = tmp_path / "wheel"
    subprocess.run(
        [
            str(builder_python),
            str(root / "scripts/build_portable.py"),
            "--output",
            str(output),
            "--allow-dirty",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(builder_python), "-I", "-c", no_build_tools], check=True)
    (wheel,) = output.glob("*.whl")
    installed = tmp_path / "installed"
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert "bms_tool/web_assets/index.html" in names
        assert all(".state/" not in n and "Manual_Library" not in n for n in names)
        manifest = json.loads(archive.read("bms_tool/data/distribution.json"))
        assert re.fullmatch(r"[0-9a-f]{40}", manifest["source_commit"])
        assert "index.html" in manifest["ui_files"]
        metadata_name = next(n for n in names if n.endswith(".dist-info/METADATA"))
        assert "Requires-Dist: tzdata==2026.5" in archive.read(metadata_name).decode()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(installed),
            str(wheel),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    code = """
import json,re,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import bms_tool
from bms_tool.app import create_app
from bms_tool.resources import state_directory
from fastapi.testclient import TestClient
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo,TZPATH
assert Path(bms_tool.__file__).is_relative_to(Path(sys.argv[1]))
assert TZPATH==(), 'Acceptance must exercise packaged timezone data, not the host database'
zone=ZoneInfo('America/Los_Angeles')
assert datetime(2026,1,5,tzinfo=zone).utcoffset()==timedelta(hours=-8)
assert datetime(2026,7,5,tzinfo=zone).utcoffset()==timedelta(hours=-7)
with TestClient(create_app(sys.argv[2])) as client:
    page=client.get('/')
    assert page.status_code==200 and '<div id="root">' in page.text, page.text[:200]
    asset=re.search(r'src="(/assets/[^"]+\\.js)"',page.text).group(1)
    assert client.get(asset).status_code==200
    for name in ('capabilities','requirements','references'):
        response=client.get('/api/'+name)
        assert response.status_code==200, response.text
        assert isinstance(response.json(),(dict,list))
    assert client.get('/api/session').json()['field_network_open'] is False
    headers={'X-Studio-Token':client.get('/api/session').json()['token']}
    assert client.get('/api/blocks').status_code==200
print(json.dumps({'installed_from':str(Path(bms_tool.__file__).parent),'ui_and_metadata_served':True}))
"""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONTZPATH"] = ""
    result = subprocess.run(
        [sys.executable, "-c", code, str(installed), str(tmp_path / "user-state")],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert '"ui_and_metadata_served": true' in result.stdout
