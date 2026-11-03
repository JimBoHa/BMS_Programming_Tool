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

Wheel creation uses pip's isolated build environment to install the
`[build-system]` requirements from `pyproject.toml`. The invoking environment
needs pip; it does not need `setuptools` or `wheel` preinstalled. Resolving build
requirements needs access to a package index or a configured local package source.

The build requires committed source by default. `--allow-dirty` permits an
explicit development build and records that fact in the embedded provenance.
The builder copies Git-tracked package files, three named public JSON documents,
and the known Vite asset layout into a temporary staging directory. It excludes
user state, controller programs, manuals, credentials, VMs and local toolchains.
The embedded `bms_tool/data/distribution.json` records the source commit, dirty
state, SHA-256 hashes of browser files and the separate
`bms-ui-build-provenance/1` proof. The standard `npm run build` compiles a frozen
copy of the declared UI inputs with the locked TypeScript/Vite versions. Source,
public assets, build configuration, package lock and optional production dotenv
files are hashed before compilation. Other source edits cannot alter that frozen
copy. Publication also requires that the current inputs and relevant environment
hashes still match. A failed build invalidates its old proof and keeps the prior
assets available without making them eligible for packaging.

The Python packager independently checks the known proof, every current input,
every emitted asset and the recorded compiler versions against the lock file.
It copies the checked asset bytes and checks again before invoking pip. Missing,
stale, added, removed or altered inputs/assets/proof require a fresh `npm run
build`; `--allow-dirty` does not bypass these checks. A valid prebuilt cache remains
usable when those exact inputs, assets and relevant environment hashes match.
Packaging prebuilt assets still requires no Node.js. The receiving installed
application also needs no Node.js or source checkout.

The proof records relative paths, byte lengths, hashes and tool versions, with
hashes of `NODE_ENV` and `VITE_*` values rather than their raw values. Its generated
file is `web/.bms-ui-build.json`, outside the distributed browser directory. The
supported recipe uses the standard production build without extra arguments.
The proof establishes declared input/output identity; it does not establish a
hermetic toolchain, bit-for-bit reproducibility across platforms, native
manufacturer compiler acceptance or physical controller compatibility.

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

The declared dependencies include the first-party `tzdata` fallback for IANA
calendar and acknowledgement-clock timezones. Windows and minimal containers
may lack a system IANA database; Python's [zoneinfo data-source documentation](https://docs.python.org/3/library/zoneinfo.html#data-sources)
recommends declaring this dependency for portable applications. Version
2026.5 is pinned from the [official package release](https://pypi.org/project/tzdata/2026.5/).
System timezone data retains its normal precedence. Installed-wheel acceptance
disables system timezone paths and checks both winter and summer offsets from
the packaged fallback. This emulates missing timezone data; it does not claim
execution on a Windows host.

Source checkouts keep the existing `.state` location. Installed distributions
default to the user's application-data folder: `~/Library/Application Support/BMS
Studio` on macOS, `%LOCALAPPDATA%\BMS Studio` on Windows, or
`${XDG_DATA_HOME:-~/.local/share}/bms-studio` on Linux. `--data` and
`BMS_STUDIO_DATA` retain precedence. The installed application does not write into
its package directory. All interfaces remain closed until explicitly connected.

Native Sedona/Temco/IEC toolchains, licensed CCT/PCT and controller packages are
separate dependencies. Packaging adds no BTCVT driver, adapter, license or vendor
acceptance beyond the application's separately qualified operations. Local manual links need the corresponding manual
library on the receiving computer.

Acceptance tests build and install the actual wheel into a separate directory,
import that installed package from outside the checkout, serve its browser assets
and metadata, and verify that field networking stays closed. Resource tests also
check source-checkout compatibility, unrelated neighboring directories and user
data paths on the three operating-system profiles.


Local captures and process locks have a separate
[portable storage profile](portable-storage.md). Windows uses native byte-range
ownership and handle-based reparse checks. File data is flushed; Windows
namespace/power-loss durability remains unverified. Native IEC execution remains
an explicit POSIX-only optional profile.
