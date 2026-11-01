# CAF/native source correlation

In Program, open a CAF and select **Compatibility**. **Compare CAF with retained
native records** compares the original opened archive with an explicitly chosen
retained native backup. It is useful offline or alongside a selected controller.
The source station, acquisition time, both source hashes and comparison coverage
remain visible. No controller query or backup/restore command occurs.

The profile is `caf-native-source-correlation/1`. It checks the CAF's unambiguous
root Device BACoid and native File 3's fully framed Device identity. The Device
table compares literal root reference/class, Device instance, typed name and
model. Retained acquisition qualification is recomputed against the native root,
vendor 5, recorded Device ID, name, model and original verified-acquisition flag.
It does not verify a current controller identity or current program.

The record table joins actual engineering references and compares recorded class
numbers and native object instance numbers. Missing records, different IDs,
noncanonical or unavailable CAF IDs, duplicate identities and conflicting CAF
reference properties remain explicit. Native metadata records and CAF root
metadata are counted separately. Search and bounded pagination retain exact
request/source ownership; the complete counts include records outside the page.
The profile accepts at most 20,000 CAF objects and 512-character references.

These observations are literal evidence. Different CAF/native encodings can use
different record identities while implementing related behavior. Equal identities
also do not establish matching behavior: parameters, child properties, links,
execution order, retained saved/live values, schemas/releases, packages, resource
limits and hardware suitability are not compared. Every report explicitly leaves
full-program match, compiler compatibility, application association and Apply
unverified. This JCI-07 slice does not complete semantic file-to-live association.

All three immutable backup file hashes and the manifest are checked on each call.
Unknown saved File 11/12 schemas do not prevent comparison of the original File 3.
Original CAF bytes and native backup bytes remain unchanged; no transfer review,
journal or hidden file link is created. Source folders must remain original,
regular private storage. The current implementation does not accept uploaded
comparison JSON as authority.

A workspace controller reuses its exact authoritative target; addresses are not
entered again. The interface identifies whether the workspace and retained source
name the same station. This address comparison does not grant a live program
match. Target/interface, CAF, source/manifest, query, navigation and A→B→A changes
retire old reports before paint and ignore late replies. Local CAF proposals and
comparison query text survive navigation independently. Reports compare the
original opened CAF; a visible notice excludes local proposals. Open an exported
copy separately to compare those exported bytes.

`POST /api/caf/{id}/native-correlation` requires the Studio token, original CAF
SHA-256, capture ID and immutable snapshot SHA-256. Query, offset and limit are
strictly bounded; network mutation fields are rejected. The response contains
a source-bound report digest and an independent actual-response byte SHA header.
The browser verifies request, both sources, station, profile, scope flags and
response bytes. **Save exact source comparison** downloads the original JSON
response Blob, preserving the evidence without regenerating it in JavaScript.

Qualification uses independently authored CAF and native archives, plain/gzip and
extended framing, literal expected record IDs, unknown saved schemas, mismatches,
membership/ambiguity/source-integrity/resource guards and strict HTTP admission.
An actual authored UDP capture is disconnected before local comparison, with no
further peer requests. Chromium/WebKit checks cover both entry paths, exact bytes,
drafts, source/file/navigation changes, delayed/altered replies, routed context,
zero additional BACnet requests, keyboard use and an 820-pixel layout.
No site, Bluetooth, CCT reopening or physical acceptance is inferred.

The separate [retained File source profile](caf-native-file-correlation.md) extends
the same literal comparison to existing BACnet File captures. The native-backup
version-1 contract and its immutable three-file checks remain unchanged.
