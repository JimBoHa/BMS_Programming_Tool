# Saved CAF/source references

In **Program → CAF → Compatibility**, a saved source reference records an explicit
selection of a retained native backup or BACnet File capture for the original
opened CAF. Reopening the same CAF bytes restores its saved references. An edited
or exported CAF with a different SHA-256 has its own reference list.

Saving recomputes the existing literal identity comparison on the server from the
opened CAF and integrity-checked retained source. It does not accept a comparison
report uploaded by the caller. Search text and the currently displayed comparison
page do not narrow this saved comparison: coverage and classification account for
all supported records, while the saved detail list contains a bounded first page.

The reference retains the source family, exact recorded target and source hashes,
comparison classification, creation time and original comparison bytes. References
can record differences or incomplete identity evidence. Equal identities do not
establish matching parameters, logic, execution order, runtime behavior, packages,
resources, hardware or compiler compatibility.

The original saved report remains available across backend restarts and after a
source capture is removed. Listing or downloading it does not revalidate current
source availability, read a controller or reopen an interface. A saved reference
does not select another source or change the current controller. Download preserves
the stored report bytes. Removing a reference removes only that reference and its
saved report; it does not remove the CAF, source capture or controller program.

Storage serializes duplicate detection, capacity checks and insertion. Repeating
the same save returns the existing reference rather than replacing its creation
time or evidence. Capacity exhaustion requires explicit removal; older references
are not evicted. Limits are 256 references and 32 MiB of combined reports and
metadata across CAF files, with a 1 MiB limit for each report and metadata record.
Stored report digests detect accidental corruption, not manufacturer authenticity.
A damaged reference appears as unavailable without hiding valid neighbors. Its
report download is refused, while explicit removal remains available. Unavailable
or malformed evidence cannot supply a compatibility or field-action grant.

The collection is `/api/caf/{caf_sha256}/source-references`. POST accepts a strict
backup or File source selection and requires the original CAF to be open. GET
lists stored references without requiring the CAF or source to remain open.
`GET /{reference_id}/report` returns the original comparison bytes with their
`X-Studio-Artifact-Sha256` header. `DELETE /{reference_id}` removes only a reference
belonging to that CAF hash. Save and removal use the existing Studio session token.

The existing [native-backup comparison](caf-native-source-correlation.md) and
[retained File comparison](caf-native-file-correlation.md) retain their distinct
source and integrity contracts. A File capture still has no paired saved-setting
files or coherent full-backup guarantee. Local CAF proposals remain excluded from
the original opened archive; open an exported copy separately to reference it.

JCI-07 remains partial. These user-selected historical references do not establish
semantic or package compatibility, a current live application match, a verified
compiler path or physical controller acceptance. The stored comparison's
`full_program_match_verified`, `compiler_compatibility_verified`,
`application_association_granted`, `can_apply`, `controller_queries` and
`field_actions` flags remain false.
