# IPv4 receive provenance on the shared Windows socket

The pinned BACpypes3 stack uses the same datagram protocol and transport for
local and broadcast IPv4 traffic on Windows. Its setup then assigns
`LocalBroadcast` to that shared protocol's destination metadata. Native Windows
testing confirmed that legitimate direct and routed unicast replies therefore
arrive with `*` as their native destination. Device reads using source identity
alone succeeded, while the stricter Schedule, COV and event receivers rejected
the inconsistent metadata.

That diagnostic used native Windows 10 x64 with the Proactor event loop and
`_ProactorDatagramTransport`. It does not establish Windows 11 ARM or physical
controller compatibility. Native acceptance of the corrected whole-wheel build
is recorded separately from the diagnostic and host alias-emulation tests.

The connector now installs one locally owned, bounded receive-context wrapper
around its ready native protocol callback. It does not patch the dependency,
change packet destination/user data, create a receive queue, or add requests,
retries or timeouts. Each native dispatch task inherits only its original UDP
datagram's context. Closing the interface retires that context and restores its
owned callback while preserving unrelated wrappers.

Strict services retain their native endpoint check. The additional shared-socket
path requires the exact owned callback, native protocol/server, live transport,
underlying socket object and bound endpoint to remain unchanged. Local and
broadcast protocol **and** transport must actually alias, and the native
destination must still be `LocalBroadcast`. No arbitrary broadcast metadata is
accepted without this callback evidence.

For property reads, COV and event notifications, the original datagram must be
a valid-length BVLC Original-Unicast-NPDU (`0x0a`). At the raw boundary its bytes
must match exactly. At the NPDU boundary its payload, source/destination routing
fields, version, network-message/vendor ID, hop count, priority and
expecting-reply flag must match the native decode of that same datagram.
Original-Broadcast (`0x0b`), Forwarded-NPDU (`0x04`), unrelated/forged contexts,
changed sockets/callbacks and retired captures cannot use the additional path.
Existing selected peer, router/DNET:MAC, Device, object, process, invoke ID, mode,
segmentation and finite-lifecycle checks remain in their owning services.

BBMD table inspection and reviewed administration use the same socket/peer
evidence for only the existing management functions Result/Read-BDT-ACK/
Read-FDT-ACK (`0x00/0x03/0x07`). Exact length, table count, native Result and
readback rules remain in those services. A malformed management datagram can be
retained **as malformed evidence**, with `bvlc_length_valid: false`; this is not
acceptance of a valid table or write outcome. BVLC still has no invocation IDs,
and desired-state observation does not prove authorship or atomicity.

## Evidence limits

Receive evidence states its basis and preserves the native `*` destination.
The shared callback reports the actual UDP peer and bound receiving socket,
**not the datagram's physical IP destination**. That value remains `null`.
Original-Unicast is the observed BVLC function, not a kernel-level proof of an
IP-unicast destination. A sender that places Original-Unicast bytes inside an
IP-broadcast datagram cannot be distinguished by this callback alone. This
profile therefore never claims that distinction or network authentication.

The same caveat applies to BBMD management functions, which carry no
unicast/broadcast discriminator of their own. Only the explicitly selected peer,
owned bound socket and exact raw frame are established. No support is added for
BBMD hosting, BACnet/SC, direct serial/BTCVT or manufacturer-specific transfer.

Real loopback UDP regressions emulate the pinned shared-protocol condition on
non-Windows hosts and exercise direct/routed property evidence, confirmed and
unconfirmed COV/events, routed ACKs, read-only tables, reviewed local-test table
administration, malformed replies, rogue peers, broadcast/forwarded rejection,
concurrent contexts, callback/socket replacement and close with a dispatch in
flight. These surrogate tests are separate from native Windows execution and
physical controller acceptance.
