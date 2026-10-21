# Installable browser distribution

Build a wheel containing the Python application, built browser UI and public
capability/requirements/reference metadata. The receiving computer needs Python
3.11 or later and the declared Python dependencies, but does not need Node.js or
the source checkout to open the editor.

From a reviewed source checkout:

```sh
cd web
npm ci
npm run build
cd ..
.venv/bin/python scripts/build_portable.py --output local-reports/distribution
```

The build requires committed source by default. `--allow-dirty` permits an
explicit development build and records that fact in the embedded provenance.
The builder copies Git-tracked package files, three named public JSON documents,
and the known Vite asset layout into a temporary staging directory. It excludes
user state, controller programs, manuals, credentials, VMs and local toolchains.
The embedded `bms_tool/data/distribution.json` records the source commit, dirty
state and SHA-256 hashes of browser files. Browser assets must be freshly built
from the reviewed source; their hashes establish artifact identity, not compiler
acceptance or physical controller compatibility.

On the other computer, copy the wheel, create an environment and install it:

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install /path/to/bms_programming_tool-0.1.0-py3-none-any.whl
.venv/bin/python -m bms_tool serve --open-browser
```

Dependency installation normally needs network access. The wheel is portable
Python code and browser assets, not a bundled Python interpreter or an offline
dependency installer. Platform-specific Python dependencies still need compatible
wheels. Apple silicon, Windows and Linux need their own environments; copying a
virtual environment between computers is not an installation method.

Source checkouts keep the existing `.state` location. Installed distributions
default to the user's application-data folder: `~/Library/Application Support/BMS
Studio` on macOS, `%LOCALAPPDATA%\BMS Studio` on Windows, or
`${XDG_DATA_HOME:-~/.local/share}/bms-studio` on Linux. `--data` and
`BMS_STUDIO_DATA` retain precedence. The installed application does not write into
its package directory. All interfaces remain closed until explicitly connected.

Native Sedona/Temco/IEC toolchains, licensed CCT/PCT and controller packages are
separate dependencies. This wheel does not add BTCVT drivers, native JCI program
transfer or vendor acceptance. Local manual links need the corresponding manual
library on the receiving computer.

Acceptance tests build and install the actual wheel into a separate directory,
import that installed package from outside the checkout, serve its browser assets
and metadata, and verify that field networking stays closed. Resource tests also
check source-checkout compatibility, unrelated neighboring directories and user
data paths on the three operating-system profiles.
