# Conversion source review

In the editor, click **Review conversion formats** before exporting a portable
graph. The report compares all supported source profiles and explicitly shows
missing native encoders for FX/Metasys CAF, ALC and Honeywell Spyder. It is
calculated from the current project, not a saved table of site results.

The preview runs the actual in-process JSON, Structured Text, PLCopen XML,
GraphML, Niagara BOG and Temco Control Basic encoders and re-importers. Each
format succeeds or fails independently. Successful source artifacts include
their byte length and SHA-256; no artifact bytes are stored or returned by this
endpoint. Each artifact is bounded to 4 MiB. The result includes the source
project digest, validation diagnostics, original/expanded graph counts,
interface IDs, block kinds and schedules needing host calendar provisioning.

An exact editable project digest on re-import establishes source fidelity, not
executable semantic equivalence. A changed digest lists the changed top-level
authoring fields. For example, the stateless Temco importer may reconstruct new
node identities, physical point labels and conversion metadata. This remains
visible as `source-generated-review-required`, rather than silently treating
the changed project as identical or declaring its execution incorrect.

Per-target review notes describe numeric representation, scan/clock/I/O host
requirements, calendar provisioning, quality and event/priority differences.
Notes describe the implemented adapter profile; they are not a complete proof
of every possible semantic loss. Native compilation, resource fit, destination
modules, physical hardware configuration and controller acceptance require
separate verification. An invalid authoring project can still be preserved as
JSON while executable source encoders reject it.

Sedona performs its actual source lowering and application-XML validation only.
It explicitly reports `source-lowering-checked` with no native artifact or
round-trip assertion. The preview does not invoke Java, native compilers, SVM,
network interfaces, transfer operations or controller writes. Actual Sedona
bundle/SAX/SAB export still invokes the existing separate native toolchain;
standalone SAX/SAB needs its generated kit, while the bundle retains the graph.

**Export conversion report** saves the displayed JSON evidence. Editing any
project field invalidates the displayed review, and a response for an earlier
source cannot replace the current review. A later normal export generates its
own bytes; ZIP container timestamps can change, so the preview hash identifies
the preview artifact, not an authorization token or a promised later checksum.

`POST /api/conversion/preview` accepts `{ "program": ... }` and requires the
normal local session token. It neither saves a project nor changes a runtime.
There is no automatic preview or field discovery when opening the editor.
Tests exercise real encoders/re-importers, independent precision blockers,
invalid graphs, calendar requirements, artifact bounds, source immutability,
session protection, evidence export and late-response/editor invalidation.
