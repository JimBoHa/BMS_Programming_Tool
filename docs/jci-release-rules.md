# Documented JCI tool/release rules

**CAF files → Target readiness → Documented tool/release compatibility** reviews
one planned native operation against specific downloaded primary manuals. Enable
**Include documented operation rules**, declare the application origin and other
relevant facts, and run target preflight. The destination product/release and
required package/license facts come from the existing inventory JSON.

This implements the documented-rule portion of **MF-e54b1129d6**. It never invokes
CCT/PCT, changes release mode, upgrades a CAF, performs simulation, defines native
hardware or transfers an application. `can_execute_native`, `can_deploy` and
`manufacturer_tool_executed` remain false. A cleared prerequisite is separate
from the still unknown exact model/package/firmware and vendor acceptance.

## Separate version namespaces

Declare the source tool product/release, source production/alpha/beta channel,
CAF release mode and active tool mode independently. The inspected CAF **Appl SW
Version** property remains an observed scalar. It is never substituted for a
source tool release, CAF mode or firmware version. Controller firmware stays in
the existing target fields. The tool's release/build, mode database, application
software and firmware versions do not share an assumed numeric scale.

Rule parsing accepts bare `major.minor` release identifiers only. Build suffixes,
prerelease suffixes, future versions and unknown origins remain unresolved. The
review bounds destination general CCT rules to 10.1–18.0, CCT Help mode rules to
18.0, package-security rules to 16.0–18.0 and the PCT workflow to 10.3. Historical
PCT mode checks are bounded to 10.0–10.3. These conservative implementation
coverage limits are labeled separately from manufacturer rules. Source-origin
coverage accepts declared CCT 1.0–18.0 and PCT 1.0–10.3 identifiers; it does not
assert that every numeric release exists or authenticate the declaration.

## Evaluated operations and predicates

| Operation | Documented condition reviewed | Remaining limit |
| --- | --- | --- |
| Open / commission | CCT 10.1 or greater can open/commission an earlier CCT application. | Equal/newer-source and cross-product combinations are not inferred; attribute display, actual tooling and target support remain unverified. |
| Edit logic / simulate in CCT 18 | Exact CAF/current-mode match, or a separately supported upgrade workflow. | A mismatch conflicts with the current declared configuration; the tool does not switch or upgrade anything. |
| Edit defaults in CCT 18 | Matching mode, or an older CAF opened without upgrade with default-value changes only. | This exception does not enable logic editing or simulation; attributes can display unexpectedly. |
| Review automatic CAF upgrade | Newer active mode and the same explicitly declared device-family identifier; production/alpha/beta exception reviewed separately. | Alpha/beta applications do not automatically upgrade. Exact target firmware/package availability and post-upgrade logic/connections/capacity validation remain required. |
| Define hardware / transfer CAF | CCT 16+ package-security generation and CCT 18 required-package license restrictions. | Old-only packages conflict; updated-generation declarations clear only that boundary. Unlicensed field devices cannot be assigned or receive CAFs. No package or license is probed. |
| Mixed firmware on engine MS/TP | Declared mixed controller firmware can coexist on an engine MS/TP integration. | Engineering enumeration display can remain incomplete; no inventory, wiring, router or transfer is tested. |
| Open CAF across SQL versions | CCT CAF portability is independent of Microsoft SQL Server version. | SQL/Windows runtime and supported installation versions remain separate prerequisites. |
| Earlier FX-PCT CAF modes | FX-PCT 10.3 documents switching among historical 10.x modes; matching declared modes clears this condition. | Earlier than 10.0 requires the documented clean-installation workflow. PCT/CCT consolidation instructions do not establish arbitrary cross-product CAF compatibility. |

Mode-sensitive CCT 18 reviews separately check reference coverage. The reviewed
Help 18 references explicitly name modes 10.0/10.1 (PDF 122–123), 10.2 (PDF 51/130),
10.3/10.4/10.5 (PDF 51/121–123), 10.6 (PDF 259) and 10.7 (PDF 766).
This is a non-exhaustive set of cited identifiers, not a complete installed-mode
or controller-support table. Either CAF or active mode outside that set produces
an unknown coverage finding, even when both labels are equal or an upgrade's
numeric ordering matches. No mode ceiling is inferred from tool release 18.0.

Missing operation facts produce unknown findings. Mode equality does not resolve
an unknown or unreviewed application origin. No device family is inferred from a
model prefix, network firmware value or brand name. Package security generation
requires an explicit declaration and provenance description; a filename, version
number or declared file hash alone does not establish it. Existing exact support
lists continue to be evaluated separately and remain operator declarations.

## Primary source evidence

All rules carry document, revision, PDF page, official URL and reviewed PDF SHA256.
Proprietary PDFs and installation artifacts are not included in the code.

| Source | Reviewed PDF pages | SHA256 |
| --- | --- | --- |
| Metasys System Configuration Guide 11.0, LIT-12011832, 2022-02-07 | 54 | `cd4ec7ba7d8012a1dbfa8ced59ae6d14cf025a08f99614473be41af889543a73` |
| Metasys System Configuration Guide 16.0, LIT-12011832, 2026-06-17 | 53 | `0c12f1988f5be8c46cc9d779d782139fe2b41994d98afc54d7dfc91e234d20d4` |
| Controller Tool Help 18.0, LIT-12011147, copyright 2025 | 37–38,51,79,89–90,121–123,130,259,766 | `68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903` |
| FX-PCT Installation Instructions 10.3, LIT-12011673, March 2019 | 2,4 | `46aeeb12517462f3eae28e177dff57bd38ea319cd98dcb7a067eb2aed9006248` |

The guides' general statements do not replace exact controller/package release
notes. Guide 11 and CCT 18 retain the mixed-enumeration caveat; its omission from
the brief Guide 16 summary is not evidence that the limitation disappeared.

## API, evidence and bounds

`GET /api/jci/preflight/release-rules` returns the catalog, operation list, unknown
input template and ruleset SHA256. Existing session-protected preflight and export
POSTs accept optional strict `release_review`; omitting it preserves the existing
inventory-only workflow. Text identifiers are bounded to 80 characters, package
provenance to 2000, and operation/product/channel/generation values to explicit
enums. The existing inventory remains bounded to 256 KiB. Unknown fields and
coerced Boolean strings are refused.

The nested `bms.jci-release-review` report contains exact CAF hash, submitted
release declarations, normalized destination inventory, observed Appl SW Version,
findings and cited sources, ruleset hash, unresolved acceptance and explicit
nonexecution flags. Its `content_sha256` covers the report without that field
using sorted-key compact UTF-8 JSON, no ASCII escaping and finite values. These
hashes bind declarations and source evidence; they are not manufacturer
authentication, installed-tool detection or runtime-build attestations.

The browser checks CAF, inventory, target, operation/declaration and ruleset
identity before accepting a result. Edits mark evidence stale and disable
export; bad response shapes/identities clear old results. Hidden/closed/replaced
CAF workspaces retire pending reviews/downloads. Export uses the authoritative
server response from the same immutable CAF and exact submitted inputs. Rules
and review results contain no native floating-point receipts; no client reseal
is performed. Reports are exported evidence, not a persistent plan store.

Tests use authored CAFs and declarations. Numeric/version boundaries, defaults
versus logic/simulation, same-family upgrades, prerelease exceptions, package and
license conflicts, SQL independence, enum-display caveats, unknown origins and
cross-product gaps have independent expectations. API and real local browser
workflows verify source guards, unchanged original CAF bytes and an independently
checked exported report seal. No field, Bluetooth, Windows-tool or controller
acceptance test is implied.
