"""Exercise actual installer payload, replacement and app-only removal."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from check_desktop import check
from privacy_audit import rules
from release_audit import audit


def check_installer(asset, output):
    asset, output = Path(asset).resolve(), Path(output).resolve()
    with tempfile.TemporaryDirectory(prefix="bms-installer-check-") as temporary:
        temporary = Path(temporary)
        data = temporary / "user-data"
        data.mkdir()
        marker = data / "preserve-example-capture.txt"
        marker.write_text("Authored preservation witness; not controller data.\n")
        if sys.platform == "darwin":
            mount = temporary / "disk-image"
            mount.mkdir()
            subprocess.run(
                [
                    "hdiutil",
                    "attach",
                    str(asset),
                    "-mountpoint",
                    str(mount),
                    "-readonly",
                    "-nobrowse",
                    "-quiet",
                ],
                check=True,
            )
            installed = temporary / "Applications/BMS Studio.app"
            executable = installed / "Contents/MacOS/BMS Studio"
            try:
                shutil.copytree(mount / "BMS Studio.app", installed, symlinks=True)
                result = check(executable, directory=data)
                shutil.rmtree(installed)
                shutil.copytree(mount / "BMS Studio.app", installed, symlinks=True)
                check(executable, directory=data)
                privacy = audit([installed], rules({}))
                assert privacy["complete"] and not privacy["findings"]
                shutil.rmtree(installed)
            finally:
                subprocess.run(["hdiutil", "detach", str(mount), "-quiet"], check=True)
        elif sys.platform == "win32":
            env = os.environ.copy()
            env["BMS_STUDIO_DATA"] = str(data)
            installed = Path(os.environ["LOCALAPPDATA"]) / "Programs/BMS Studio"
            executable = installed / "BMS Studio.exe"
            for _iteration in range(2):
                subprocess.run(
                    [str(asset), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"],
                    check=True,
                    env=env,
                    timeout=180,
                )
                result = check(executable, directory=data)
            privacy = audit([installed], rules({}))
            assert privacy["complete"] and not privacy["findings"]
            subprocess.run(
                [str(installed / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                check=True,
                env=env,
                timeout=90,
            )
            deadline = time.monotonic() + 30
            while executable.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            assert not executable.exists()
        else:
            raise ValueError("Native installer acceptance requires macOS or Windows.")
        assert marker.read_text() == "Authored preservation witness; not controller data.\n"
        assert (data / "studio.sqlite3").is_file()
        result.update(
            installer_install="passed",
            installer_update="passed",
            app_only_removal="passed",
            user_data_preserved="passed",
            installed_payload_audit="passed",
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    check_installer(args.asset, args.output)
