# SCT/JCT engineering source inspection

`JCI-ENGINEERING-SOURCE-001` is the first delivered SJ-01 slice. Open **Help →
Reference desk → SCT/JCT engineering sources and parity inventory**. This keeps
the existing controller/file workspace and its drafts; it adds no global feature
destination.

## Operator workflow

Select an engineering source, then choose **Inspect source**. The result names
the selected file and actual reader profile, represented object/class or graph
counts, partial coverage and operation-specific availability. **Save exact
inspection report** saves the original received JSON after checking its file
fingerprint, byte-digest headers, closed schema and report seal.

Switch to **Parity inventory** to search the 48 parent work packages by product
and feature. Each package retains priority, dependencies, workspace placement,
acceptance and planned/partial status. Expand artifact families, implemented
reader operations or versioned manual sources for evidence. This inventory maps
the initial inspection slice; exhaustive manual-operation mapping remains partial.

Changing/clearing the selected file, leaving the source pane, closing the desk or
leaving Help retires in-flight inspection results. Returning to an old selection
does not adopt its late response. No inspector action changes the selected
controller, CAF, graph, unfinished edits or transfer receipt.

## Source profiles and evidence boundaries

| Content admitted by an existing reader | Useful result | Remaining evidence |
| --- | --- | --- |
| Single-XML JCI object ZIP, including observed CAF sources | Represented objects, native class IDs and class versions, root metadata count and explicit omitted coverage | Namespace/root alone does not establish CCT/PCT versus SCT origin or tool release. No complete supervisory schema is inferred. |
| Tagged MOI field image, raw or gzip | Represented records/classes, framing, readable diagrams and parser errors | A detached image supplies no saved Files11/12, verified Device identity, live values, whole-controller backup or supervisory archive. |
| Explicit schema-1 BMS portable Program JSON | Program identity/name, exact integer revision text, node and edge counts | This is our field graph, separately from SCT archives, supervisory LCT and JCT graphics. |
| Unknown, malformed, encrypted or future source | Exact selected-source fingerprint, declared filename family, diagnostic and unavailable decoder state | A file extension or container signature grants no native import/export, compilation, conversion or deployment support. |

The declared family and detected reader remain separate. Renaming a readable
object ZIP `.dbexport` may expose an object projection, but does not qualify a
native SCT decoder. SCT XML exports, SQL-dependent database backups, protected
`.sDbExport`/`.sBackup`, item exports and JCT resources retain distinct gaps.
The SCT Pro18 backup topic documents these separate families; their native codecs
remain SCT-02 work.

The selected original is untouched. This slice does not retain/import source
attachments or round-trip native archives; immutable staging follows under SJ-02.
Unknown native sections remain with that original. Report hashes prove byte
consistency and do not authenticate a vendor or prove hardware behavior.

## API and resource profiles

`GET /api/jci/engineering/inventory` serves the bundled
`jci-engineering-inventory/1` operation/fixture register in source and installed
builds. `POST /api/jci/engineering/inspect` accepts exactly one multipart
`file`, under the existing local session/origin/host checks. It accepts no target,
filesystem path, write or compilation fields.

The upload profile is 1 byte through 8 MiB. Existing CAF XML and MOI expansion,
depth, record and datatype bounds remain unchanged. Structured JSON rejects
duplicate/nonfinite/deep input and requires an explicit supported Program
shape/schema; it does not normalize an unknown file into a default application.
Oversized labels/IDs/version lists and native errors have explicit bounded
report coverage. Every upload stream closes on success and refusal.

The closed `jci-engineering-source-inspection/1` report includes the original
fingerprint, declared and detected profiles, representation coverage, diagnostics,
six operation outcomes and explicit read-only/no-field-authority flags. The
browser checks the exact response digest and independently binds it to the
selected File. A malformed/future/resealed capability claim is refused.

No inspection opens an interface, queries a controller/SQL server, creates a
review, stores a source attachment or performs a transfer. Existing native
transfer writers and field command ownership are unchanged.

## Qualification and remaining SJ-01 work

Authored sources cover valid/renamed object ZIPs, raw/gzip tagged records, partial
native graph coverage, explicit portable graphs and large integer revisions.
Malformed/encrypted/multiple ZIPs, DTDs/entities, corrupt/trailing/over-expanded
gzip, ambiguous/nonfinite/deep/future JSON, oversized metadata, deceptive file
labels and unknown supervisory/graphics sources retain their actual outcomes.

The qualification runs 278 backend cases per source/installed build and 41
browser/contract cases per source/installed × Chromium/WebKit matrix: 720
executions. The 51 new backend cases and 25 contract cases are included. Browser
work covers desktop/compact keyboard operation, actual exports, search, partial
and unavailable readers, same-source/lifecycle invalidation and preservation of
existing controller/CAF/graph contexts. Existing reader/distribution regressions,
ordinary deadlines, import guards and no-retry/no-skip gates remain.
The existing optional-directory CAF regressions run unchanged on explicitly
authored originals in the hosted qualifier. Private building archives are not
uploaded or substituted for hosted fixtures.

See `scripts/qualify_jci_engineering.py` and the dedicated GitHub workflow.
Failures retain their original evidence. This is authored software qualification;
native supervisory/reference and physical/BTCVT acceptance remain separate.

SJ-01 remains partial: exhaustive manual-operation coverage, additional native
artifact/release samples, complete per-operation interoperability evidence and
the remaining fixture inventory still need work. Native SCT/JCT decoding and
deployment, site projects, object editing and graphics remain on
[the detailed parity roadmap](sct-jct-parity-roadmap.md).
