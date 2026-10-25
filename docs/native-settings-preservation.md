# Preserve the selected controller's application and settings

A native instance change must use the selected controller's own application and
saved parameter files. A controller model, program label or expansion-module
count must never select a substitute application or a fixed list of settings.

Before accepting a transfer as verified, BMS Studio now also checks:

1. Merge the actual pre-transfer saved parameters into its original application.
2. Reverse only the Device-instance edit in the expanded readback and require
   byte-for-byte equality with that merged original. This includes program
   records, unknown expansion properties, defaults and configuration values.
3. Compare every captured saved application parameter with the readback,
   accounting for the changed Device object's native identifier.
4. Decode the readback's current saved parameters and reject unexplained value
   differences. Documented elapsed-active-time and change-of-state counters may
   advance while the controller operates.

The transfer receipt includes a `preservation` evidence record with verified
parameter counts, hashes and any advancing counters. A smaller regenerated
parameter directory is not treated as data loss when those values are preserved
as application defaults. Any unexplained program or saved-setting difference
keeps the transfer unresolved and requires review before another write.

This is configuration evidence from the actual captured formats. It does not
assert that live operating values remain constant, replace point/I/O quality
checks, or establish physical equipment performance. Preserve the original
private backup and complete operational/supervisory verification separately.
