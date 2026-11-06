# BMS Studio 0.2.0 beta 2

This update fixes `crypto.subtle.digest` errors when opening the editor through
an authenticated LAN HTTP address. It also fixes UUID creation on the same
origins. SHA-256 checks and secure random identifiers remain enabled, including
CAF/source verification, native evidence and discovery report downloads. Native
browser providers remain preferred on HTTPS and loopback.

Regression coverage now runs real ordinary-HTTP workflows in Chromium and
WebKit: application startup, source hashing, byte-preserving CAF opening/saving,
authored router/trunk discovery and downloaded report verification. These tests
use isolated data and make no physical controller changes.

## Packaged desktop features

This first packaged beta adds native macOS (Apple silicon/Intel) and Windows x64
desktop distributions, plus the Python wheel and illustrated offline HTML guide.
The desktop downloads include Python, runtime dependencies and the web UI.

- A local launcher waits for readiness, reopens a verified running instance,
  handles an occupied port and provides Open editor, Open logs and guarded Quit.
- Optional authenticated LAN sharing restricts the configured client subnet,
  Host and Origin while retaining the existing loopback editor and field guards.
  Addresses, access codes and startup configuration remain private runtime data.
- Guided connection discovers named NAEs/routers, selects reported/cached trunks,
  scans named controllers and verifies the selected route before opening it.
- Current source documentation removes field names/topology and obsolete setup
  history. Production source maps are disabled and refused in the wheel.
- Distribution notices include root/third-party/browser dependency attributions.
- Automated clean-runner checks exercise bundled startup, install, update,
  app-only removal and user-data preservation with authored isolated data.
- Release assets include checksums, dependency SBOMs, build provenance, privacy
  receipts and platform acceptance results. The getting-started guide has three
  screenshots made from authored examples, with no building connection.

## Installation and supported scope

See [Getting started](https://github.com/JimBoHa/BMS_Programming_Tool/blob/main/docs/getting-started.md)
or extract the documentation ZIP and open `START-HERE.html`. Select the installer
for your OS/architecture. Linux uses the alternative Python wheel in this beta.
Optional native toolchains, vendor software/licenses, manuals and adapter drivers
remain separate. Contextual capability reports retain the actual operation and
source limits; packaging does not grant new controller-write authority.

## Signing and qualification

Signing/notarization credentials are not configured for every platform. This beta
may trigger OS publisher warnings. Each `*-build.json` reports the exact signature
and notarization status of its corresponding installer; SHA256SUMS.txt lists the
outgoing file hashes. Unsigned/ad-hoc assets are beta test distributions, not
notarized or Authenticode-verified products. Stable releases are gated on signing.

Runner acceptance uses isolated, authored data and checks that first startup
leaves field interfaces closed with no owned commands. It does not qualify every
network/USB adapter, firmware, controller or physical I/O operation. Supported
controller writes keep their existing backup, review and readback requirements.

Source/artifact privacy scans cover the published payload. Older GitHub PR refs,
caches, attachments or forks are a separate historical-removal scope; this release
does not claim those copies have been purged.
