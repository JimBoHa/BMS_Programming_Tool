# Unsaved native parameter slots

The native parameter directory can contain runtime selectors that have no
corresponding property in the captured application. A slot marked `0x67` or `0x27` has
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

The observed `0x27` runtime slots can repeat a selector while retaining separate
payload/checksum ranges. Only repeated `0x27` selectors with the same native
class receive this treatment. Mixed saved/unsaved flags, repeated saved selectors,
class substitutions and overlapping storage remain errors. No retired command
value becomes a default or a new controller command.

A valid saved selector can declare a property omitted from File 3 on an existing
native object. The merger now retains that captured typed value on that exact
object and reframes its record. It preserves the source storage datatype and
Float bits, including negative zero. It does not create objects or select fields
from a controller-model inventory. CRC, complete storage coverage, unambiguous
selectors and native framing remain required. Non-application objects remain in
the original backup; this does not allocate them into the application.

The merge report marks a newly materialized property with `added: true` and its
native class, instance and property. Re-merging the same snapshot is idempotent.
Identity/default/wire transfer preservation compares the complete merged image,
so these retained fields receive the same byte and saved-value verification as
properties originally present in File 3.

A root Device selector may retain the application's logical reference while
the native record header carries the assigned BACnet instance. The merger uses
the exact root reference and native class to resolve this alias. It does not
assume that Device 1 means the root. Conflicting native objects, non-Device root
selectors and two aliases targeting one property remain errors. The report uses
the resolved native instance, so preservation still checks the root's saved
settings after an instance edit without rewriting its logical reference.

This distinction prevents an unused runtime value from blocking an otherwise
supported instance edit. It never substitutes a default, repairs a stored value,
or copies invalid bytes into the application.
