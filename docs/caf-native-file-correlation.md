# CAF comparison with retained native File captures

In **Program → CAF → Compatibility**, expand **Compare CAF with retained native
records** and select **Captured BACnet File** as the comparison source type.
Choose an explicitly retained capture. The original opened CAF and retained
source remain visible. The existing Native backup source keeps its independent
selection, manifest checks and version-1 response contract.

This source family reads actual bytes from the existing BACnet File capture store.
Its wrapper, receipt checksum, complete payload hash, metadata and stream/record
boundaries are checked through the existing integrity loader on every request.
The selected parsed receipt has its own deterministic digest, separate from the
captured File byte hash. These digests bind route, recorded identity, metadata,
capture time and bytes; they do not authenticate a manufacturer or grant a write.

Actual native content determines readability. A recognized tagged-MOI payload can
be compared even when its File type hint is `.bin`; an opaque file labelled
`.moz` cannot supply a fabricated application. The same existing plain/gzip
native framing reader handles recognized `.moi`/`.moz` contents. Correlation
still requires an unambiguous framed Device root and typed engineering references.

Literal CAF/native Device and record observations use the same bounded comparison
core as native backups. File acquisition device metadata is independently checked
against the archive's Device ID, vendor 5, name and model. Its report calls this
**recorded device identity agreement**; it does not claim a verified native-backup
acquisition, current identity or current program. The File's actual object ID,
captured route, interface digest, acquisition time and original consistency
statement accompany the evidence.

A published File capture is not a coherent application/settings backup. It does
not provide saved Files 11/12 or live values. No fake three-file backup, transfer
review, journal or persistent application association is created. Equal recorded
identities do not prove matching parameters, logic, runtime behavior, packages,
resources, hardware or compiler compatibility. All reports retain the explicit
unverified full-program, compatibility, association and Apply flags.

Comparison is local and independent of the current interface. It retains direct,
explicit routed and serial/legacy recorded addresses without using a current
network-connection policy to gate offline format reading. Matching workspace
addresses remain a literal address observation. No interface opens and no BACnet,
backup, restore or write request occurs while listing or comparing retained Files.

Both source types keep independent explicit selections. Type, CAF, selected
receipt/payload, route/interface, query, navigation and A→B→A changes retire stale
reports before paint. Local CAF proposals remain excluded from the original
opened-archive baseline; raw drafts and query text survive navigation. The source
type and File picker follow the existing readable keyboard/narrow-layout controls.
The browser verifies the File-specific profile, source hashes, File/object/
interface metadata, family flags and actual response-byte digest. Exact report
download preserves the original response Blob.

`GET /api/caf/native-file-sources` lists bounded retained File candidates; it does
not infer native content from the filename. `POST
/api/caf/{id}/native-file-correlation` requires the Studio token, original CAF hash,
capture ID, parsed receipt digest and captured File byte hash, plus bounded search/
paging. The profile is `caf-native-file-source-correlation/1`; the source envelope
is `retained-native-file-comparison-source/1`. Native-backup endpoints/profile
remain unchanged; File and native-backup request/evidence fields are not mixed.

Qualification covers independent File wrappers and actual byte framing, label
mismatches, recorded identity/route disagreements, unknown sources, tampered
receipt/payload/metadata, symlinks, strict local HTTP and cross-kind refusal.
A real authored UDP File read is disconnected before comparison and adds no
further requests. The extracted common core reproduces 48 complete parent
native-backup reports and their digests exactly.

Private local qualification also compares five existing retained File captures
against seven user-provided CAFs, producing 35 literal-evidence reports while
leaving every original byte unchanged. Those combinations do not establish that
the programs are equivalent. Source files, site names/addresses and private
results are not distributed. JCI-07 remains partial for semantic/package matching
and persistent association; no site, Bluetooth or physical acceptance is inferred.
