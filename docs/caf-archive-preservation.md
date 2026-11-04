# CAF edited-copy archive attributes

`FMT-CAF-ZIP-ATTRIBUTES-001` preserves the recorded external ZIP entry attributes
across supported edited CAF copies. All seven authorized private CAF
originals record `external_attr = 0`. Python's `zipfile` assigns Unix permission
bits when writing an entry with a zero value. Copying `ZipInfo` alone therefore
changed metadata from `0` to `25165824` even when that metadata was unrelated to
the requested program edit.

All five CAF writer families now use `CafArchive._copy_xml`: scalar/Enum copies,
graph rewires/prototype connections, hardware bindings, instance changes and saved
simulation profiles. Scenario startup copies reuse the simulation writer. The
helper copies the original entry metadata and archive comment, writes the changed
XML, then restores the recorded external attributes before the central directory
is written. It retains both zero and nonzero values and leaves source `ZipInfo`
unchanged. CRC and sizes are recomputed for the actual XML. Edited containers may
have different compressed bytes; this is not a promise of raw ZIP-header identity.

Existing XML readbacks, source/old-value/review guards, profile versions and API
hashes remain. No-op paths continue to return the original archive bytes exactly.
The profile version 2 fix already delivered is retained; version 1 and other
legacy edited-copy paths now receive the same preservation behavior. That changes
the artifact digest of an affected edited copy, as expected. Request/source proof
and native values retain their existing contracts.

Tests cover nine operation variants across zero, DOS archive bits and Unix
permissions, DOS/Unix origins and stored/deflate compression. They inspect actual
output XML and ZIP metadata, independent CRC/size, source immutability and existing
no-op paths. Read-only private tests keep all seven originals unchanged. The
previous installed wheel reproduces attribute replacement in eight variants;
version 2 simulation is the already-correct control. Browser checks verify actual
zero-attribute ordinary Enum, version 2 and separate version 1 scenario downloads.
All existing CAF tests, UI source/styles and previous test files remain unchanged.

This is local container preservation. It adds no native compilation, controller
transfer, native execution or CCT/physical acceptance.
