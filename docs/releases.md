# Release construction and verification

The release workflow covers six distribution requirements: bundled runtime/UI,
desktop lifecycle, install/update/removal preservation, signing, repeatable release
checks and illustrated user documentation. A beta may explicitly report missing
signing credentials. Stable distribution requires configured signing and notarization.

## Build inputs and assets

Use Python 3.13 with Tcl/Tk, Node.js 22 and a clean committed checkout. Install
`requirements/build.txt` in a dedicated build environment. The runtime lock pins
all Python dependencies and their accepted package hashes; the browser uses
`npm ci` and its committed lock. Regenerate the runtime lock with the pinned
pip/pip-tools, review it and repeat the advisory/installation checks when updating.
Colorama is included across profiles to retain Click's Windows dependency in the
shared runtime lock generated on another platform.

```sh
python -m pip install -r requirements/build.txt
python -m pip install --require-hashes -r requirements/runtime.txt
cd web
npm ci
npm run build
cd ..
python scripts/build_portable.py --output release-output/wheel
python -m pip install --no-deps release-output/wheel/*.whl
python scripts/build_desktop.py --output release-output/desktop
python scripts/package_desktop.py --payload release-output/desktop --output release-output/assets
```

Run each native build on its target OS/architecture. The freezer refuses an
editable checkout, dirty wheel provenance or a source-commit mismatch. The
installed wheel supplies package data, public metadata, web assets and notices.
Production source maps are disabled and refused by the wheel packager. Native
toolchains, manuals, vendor binaries/licenses, user state and site archives are
excluded. Desktop builds also retain Python/Tcl/Tk and dependency license data.

The GitHub workflow builds macOS arm64, macOS Intel and Windows x64 installers,
plus a Python wheel and offline HTML documentation ZIP. It publishes asset hashes,
Python/browser CycloneDX SBOMs, platform/build provenance and acceptance/audit
receipts. Action revisions and packaging-tool versions are pinned. The workflow
creates only a draft release; publish after reviewing its receipts and signing
table. A tag is immutable release input: fix a failed candidate with a new tag
rather than silently replacing a published release's program.

## Installer and runtime acceptance

Every native job starts the actual frozen executable from outside the checkout
with isolated data and no usable Python/Node PATH. It checks the served UI and
metadata, fallback from an occupied port, verified reuse on repeated launch,
installer ownership guard, closed initial field interfaces, no owned commands,
saved-project preservation across restart and optional-tool availability reports.
Windows additionally runs actual silent install, reinstall/update and uninstall,
checking that the same user project/data remains. macOS verifies the mounted
disk-image payload, copy-to-Applications style install, replacement and app-only
removal against a separate user-data folder. These are clean-runner acceptance
checks, not qualification of every physical network adapter or controller.

Selected Python/Playwright checks cover installation resources, provenance,
privacy, launcher ownership and the guided/offline workflows. The normal field
Edit → Review → Apply → Verify contracts remain unchanged. No release check
scans the building or writes a physical controller.

The payload audit decodes ZIP members and compressed frozen Python modules.
It refuses production source maps, machine-home paths, known token/key patterns,
private-rule findings and incomplete/oversized scans. Native setup containers are
qualified by scanning their staged and installed payloads; this is not a claim
of arbitrary binary/dependency security analysis. Screenshot privacy is also
visually reviewed. Advisory checks are a point-in-time result.

## Signing and notarization

For macOS, provide a Developer ID Application identity already installed in the
build keychain via `build_desktop.py --identity` and `package_desktop.py --identity`.
For notarization, add `--notary-profile` with the name of a preconfigured
`notarytool` keychain profile; the wrapper submits, waits, staples and validates.
Keys/passwords never belong in source, command text or release notes. The optional
CI signing helper imports credentials from GitHub Actions secrets into an ephemeral
keychain and removes it at job completion. See [Apple's notarization documentation](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).

For Windows, configure an Authenticode signing service or certificate in a
protected release environment and sign both the application and setup executable.
The optional CI helper accepts `WINDOWS_CERTIFICATE_BASE64` and
`WINDOWS_CERTIFICATE_PASSWORD`, signs with SHA-256/timestamping and verifies the
result. Prefer a managed signing service when available; do not export production
keys merely to enable a beta. See [Microsoft signing options](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options).

Without those credentials, native artifacts are clearly labelled unsigned/ad-hoc
or signed-but-unnotarized. The build manifest never claims notarization from a
signature alone. Hashes establish file integrity against the release manifest;
they are not an OS publisher signature.

## Privacy and history cleanup

Run both `scripts/privacy_audit.py` on tracked source and `scripts/release_audit.py`
on the exact outgoing payload with private rules kept outside Git. Never upload
the rule file, original captures or matched values. CI runs generic checks; the
publisher also runs the private site/credential rules locally before publication.
Reports contain finding categories and locations, not raw matches.

Current source/asset cleanup does not erase older Git objects, historical PR refs,
attachments, caches or forks. GitHub PR refs cannot be force-pushed. Qualifying
sensitive-data removal can require [GitHub Support review](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).
Keep that separate from a release's clean payload; do not advertise the entire
hosting history as purged based on a clean artifact scan.

## Documentation screenshots

The getting-started guide contains the start screen, named engine/trunk selection
and a native CAF diagram. Reproduce them with the authored loopback/offline peers:

```sh
cd web
BMS_DOC_SCREENSHOTS=../docs/screenshots npx playwright test release-guide.spec.ts engine-discovery.spec.ts
```

Review every image for privacy and legibility before committing. No live site,
controller archive, account credentials or original manual screenshot is used.
