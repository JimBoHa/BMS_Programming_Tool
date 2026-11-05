"""Run the bundled app with isolated data, occupied port and a repeated launch."""

from __future__ import annotations

import argparse
import json
import os
import re
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
                    record = json.loads((data / "desktop.lock").read_text())
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
