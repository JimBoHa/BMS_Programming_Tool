"""Run the bundled app with isolated data, occupied port and a repeated launch."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def check(executable, *, directory=None):
    executable = str(Path(executable).resolve())
    with tempfile.TemporaryDirectory(prefix="bms-installed-check-") as temporary:
        data = Path(directory or (Path(temporary) / "user-data"))
        data.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env["PYTHONTZPATH"] = ""
        # A frozen app must use its bundled interpreter rather than a PATH Python.
        if sys.platform != "win32":
            env["PATH"] = "/usr/bin:/bin"
        else:
            env["PATH"] = env.get("SystemRoot", r"C:\Windows") + r"\System32"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        access_code = secrets.token_urlsafe(32)
        code_file = Path(temporary) / "authored-lan-code"
        code_file.write_text(access_code)
        code_file.chmod(0o600)
        share_config = Path(temporary) / "authored-lan-config.json"
        with socket.socket() as selected:
            selected.bind(("127.0.0.1", 0))
            share_port = selected.getsockname()[1]
        share_url = f"http://127.0.0.1:{share_port}"
        share_config.write_text(
            json.dumps(
                {
                    "profile": "bms-studio-lan/1",
                    "host": "127.0.0.1",
                    "port": share_port,
                    "allowed_networks": ["127.0.0.0/8"],
                    "access_code_file": str(code_file),
                }
            )
        )

        def request(url, payload=None, token=None):
            headers = {"Content-Type": "application/json"}
            if token:
                headers["X-Studio-Token"] = token
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode() if payload is not None else None,
                headers=headers,
            )
            with opener.open(req, timeout=8) as response:
                return response.read()

        def launch(port):
            process = subprocess.Popen(
                [
                    executable,
                    "--headless",
                    "--no-browser",
                    "--data",
                    str(data),
                    "--port",
                    str(port),
                    "--share-config",
                    str(share_config),
                ],
                cwd=temporary,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(
                        "Installed app exited before readiness; inspect isolated logs."
                    )
                try:
                    record = json.loads((data / "desktop-session.json").read_text())
                    url = f"http://127.0.0.1:{record['port']}"
                    if json.loads(request(url + "/api/desktop/identity")) == record:
                        return process, url
                except (OSError, ValueError, KeyError):
                    pass
                time.sleep(0.1)
            process.terminate()
            process.wait(timeout=40)
            raise RuntimeError("Installed app did not become ready.")

        def stop(process):
            process.terminate()
            process.wait(timeout=40)

        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen(1)
            port = occupied.getsockname()[1]
            process, url = launch(port)
            try:
                assert int(url.rsplit(":", 1)[1]) != port
                session = json.loads(request(url + "/api/session"))
                identity = json.loads(request(url + "/api/desktop/identity"))
                # Desktop publishes its local record before the optional LAN
                # listener. Wait for the child to finish that startup as well.
                lan_deadline = time.monotonic() + 10
                lan_request = urllib.request.Request(
                    share_url + "/api/session",
                    headers={
                        "Authorization": "Basic "
                        + base64.b64encode(("operator:" + access_code).encode()).decode()
                    },
                )
                while True:
                    try:
                        with opener.open(lan_request, timeout=2) as reply:
                            assert json.load(reply)["field_network_open"] is False
                        break
                    except OSError:
                        if time.monotonic() > lan_deadline:
                            raise RuntimeError(
                                "Installed authenticated LAN listener did not become ready."
                            ) from None
                        time.sleep(0.1)
                try:
                    request(share_url + "/")
                except urllib.error.HTTPError as exc:
                    assert exc.code == 401
                else:
                    raise AssertionError("Installed LAN listener allowed anonymous access.")
                assert session["field_network_open"] is False
                status = json.loads(request(url + "/api/bacnet/status"))
                assert status["commands"] == [] and status["connected"] is False
                html = request(url + "/").decode()
                asset = re.search(r'src="(/assets/[^\"]+\.js)"', html).group(1)
                assert len(request(url + asset)) > 100
                for endpoint in ("capabilities", "requirements", "references", "native/status"):
                    request(url + "/api/" + endpoint)
                templates = json.loads(request(url + "/api/templates"))
                program = templates[0]
                program["id"] = "release-install-check"
                program["name"] = "Release install preservation example"
                existing = json.loads(request(url + "/api/projects"))
                revision = next((p["revision"] for p in existing if p["id"] == program["id"]), 0)
                program["revision"] = revision
                request(
                    url + "/api/projects",
                    {"program": program, "expected_revision": revision},
                    session["token"],
                )
                subprocess.run(
                    [executable, "--headless", "--no-browser", "--data", str(data)],
                    cwd=temporary,
                    env=env,
                    check=True,
                    timeout=15,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                assert process.poll() is None
                assert (
                    subprocess.run(
                        [executable, "--data", str(data), "--check-not-running"],
                        env=env,
                        timeout=15,
                    ).returncode
                    == 1
                )
            finally:
                stop(process)
        # Restart/upgrade the same installation without replacing the user store.
        # A second check after an installer upgrade uses this same directory.
        process, url = launch(0)
        try:
            projects = json.loads(request(url + "/api/projects"))
            assert any(p["id"] == "release-install-check" for p in projects)
            assert json.loads(request(url + "/api/session"))["field_network_open"] is False
        finally:
            stop(process)
        assert (
            subprocess.run(
                [executable, "--data", str(data), "--check-not-running"], env=env, timeout=15
            ).returncode
            == 0
        )
    return {
        "profile": "bms-desktop-acceptance/1",
        "platform": identity["platform"],
        "architecture": identity["architecture"],
        "bundled_startup": "passed",
        "occupied_port": "passed",
        "repeated_launch": "passed",
        "ui_and_metadata": "passed",
        "data_survives_restart": "passed",
        "installer_running_guard": "passed",
        "authenticated_lan_startup": "passed",
        "first_start_field_interfaces": "closed",
        "owned_commands": 0,
        "field_hardware_tested": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = check(args.executable, directory=args.data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
