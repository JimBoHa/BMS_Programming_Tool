# BACnet property values in JSON

`backend/bms_tool/bacnet_values.py` converts actual BACpypes datatypes for point-service responses. This is a value representation, not a proprietary application decoder.

Ordinary finite numbers, text, lists and Choice wrappers retain the existing API shapes. BACpypes `Boolean` inherits from Python `int`; it must be handled before integer conversion so a real BACnet Boolean becomes JSON `true` / `false`. Standard enumerations remain numeric codes. BACnet Date/Time tuples retain raw protocol fields; generic reads do not infer a timezone.

Schema-backed constructed Sequences become mappings of their actual populated fields. This preserves object/property references and other standard configuration records instead of returning Python object-memory representations. Optional absent fields stay absent. Unknown unsupported Python datatypes fail explicitly rather than masquerading as meaningful text.

Nonfinite numeric values become typed evidence: `{"type":"nonfinite-number","value":"NaN"}` or `Infinity` / `-Infinity`. They never become JSON NaN, null, or zero. Integers outside JavaScript's exact range become decimal-string records. Numeric trend acquisition rejects these records as invalid numeric samples; reading their evidence is not a good-quality process value.

Octet strings retain exact base64 bytes. An unmodeled BACnet `Any` retains encoded byte count, full SHA-256, and up to 1024 encoded bytes with an explicit truncation flag. No vendor meaning is guessed from those tags. This does not make an unknown JCI object/property type decodable: an unregistered proprietary type still requires an authoritative schema and a decoder.

The traversal bounds are 16 levels, 4096 values/tags, 256 KiB of source text/byte payload, 64 KiB per opaque/octet value, and 4096 bits per integer. Recursive references, exceeded bounds and unsupported types raise visible errors before returning a partial value. The bounds apply to this serializer; wire APDU, segmentation and whole-operation limits belong to the connector.

`tests/test_bacnet_values.py` checks actual protocol datatypes, strict JSON encoding, schema-backed structures, exact opaque hashes, nonfinite values and traversal bounds. A real loopback UDP application returns a BACnet Boolean and a NaN numeric property. No site, physical router, RS-485 cable or controller program is accessed by these tests.
