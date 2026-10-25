# Unsaved native parameter slots

The native parameter directory can contain runtime selectors that have no
corresponding property in the captured application. A slot marked `0x67` has
no valid saved application value. Its old payload and checksum can remain in
storage after the selector becomes unsaved; neither is used to build a program.

The compiler first reserves and validates each slot's complete byte range.
It rejects unknown storage types, overlapping/out-of-range slots and unexplained
trailing storage. An unsaved slot that resolves to an application property still
blocks compilation because the application setting has no valid saved value.

For an explicitly unsaved, unreferenced slot, the compiler skips decoding the
unused payload and checksum. The original bytes remain in the private backup.
All valid `0x6F` and `0xEF` values still require their per-value checksum before
decoding or merging. This includes valid slots outside the application.

This distinction prevents an unused runtime value from blocking an otherwise
supported instance edit. It never substitutes a default, repairs a stored value,
or copies invalid bytes into the application.
