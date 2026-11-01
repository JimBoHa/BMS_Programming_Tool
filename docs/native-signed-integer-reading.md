# Native signed Integer inspection

The MOI reader recognizes a single BACnet application Integer tag (tag 3) with
one through four payload bytes. It decodes two’s-complement signed values exactly,
including `-2147483648` and `2147483647`, and returns datatype `Integer` with an
integer JSON value. The browser record inspector displays the same value without
unsigned conversion or decimal rounding.

This extends stored-property inspection in native records, diagrams and local
record responses. It does not turn an archive value into a live measurement.
Reading an original application and reading its separately saved-parameter-merged
copy can therefore show different signed values; their respective source hashes
and byte evidence remain authoritative.

Zero-width and wider Integer encodings, multiple tags and structured values remain
opaque under this profile. The reader retains their original encoded bytes,
offsets and hashes; it does not relabel them as signed32 or discard them. Signed64
or another proprietary integer profile would require separate format evidence.

No editor, compiler setting, hardware allocation or transfer operation is added.
The existing native Real-default editor still requires an actual Real payload;
recognizing an Integer in the same property does not qualify it for that editor.

Qualification uses independently written literal tag/payload bytes covering
signed boundaries and compression, original-byte/hash checks, saved parameter
inspection, the production record HTTP API and actual UDP controller File reads
through Chromium/WebKit. No site or Bluetooth acceptance is inferred.
