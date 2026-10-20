# BACnet point-command ownership

Commands target existing commandable output/value objects at an unused priority
8 through 16. They change `present-value`; they do not create inputs, edit a
controller application or transfer a CAF.

Binary output/value preflight verifies the known native present-value datatype
is BACnet `BinaryPV`. Supported inputs are exactly `active`, `inactive`, numeric
0 or 1, and booleans. The plan shows the normalized integer 0/1 and retains
`requested_value`. The durable ownership journal stores the normalized value
before transmission, so typed priority-array readback and release still match
after restart. Other binary scalars are refused before a WriteProperty request.

Apply and release use a typed WriteProperty request. A successful acknowledgement
must have the exact peer, invoke identifier and WriteProperty service. Native
readback still checks the requested priority slot; an acknowledgement alone is
not a verified command.

Analog output/value preflight accepts finite JSON numbers, excluding booleans
and strings, and verifies the native datatype is BACnet Real or Double. The
plan preserves `requested_value` and journals the exact IEEE-754 wire value;
overflow is refused before transmission. Multistate output/value preflight
requires a positive JSON integer and a verified Unsigned datatype, then checks
the device's `number-of-states`. These checks do not infer engineering units or
application-specific operating limits.

The shared confirmed-exchange helper owns dispatch in the calling task instead
of creating a detached BACpypes task. Every exit retires only its matching native
client state machine and application future, including cancellation during the
native device-cache lookup before the state machine has populated its invoke
identifier. Closing the interface cancels those still-dispatching operations.
An uncertain operation cannot keep retrying after it has returned.

Cancellation or timeout may occur after a remote device accepted a command.
Neither event proves the command failed. Ownership stays in the local journal;
no automatic null write, retry after return, or restart recovery write occurs.
Reconnect the same saved interface and explicitly inspect/relinquish the owned
slot. A changed slot is not automatically overwritten or released.

`tests/test_bacnet_commands.py` exercises actual loopback UDP for canonical
BinaryPV inputs, invalid-value refusal, preview/apply/readback/release, restart
ownership, accepted-write cancellation, acknowledgement-service mismatch and
timeout. Held native cache lookups prove cancelled dispatch cannot send later.
`tests/test_bacnet_read.py` independently exercises the same early-cancellation
case and interface shutdown, with no later UDP packets. These checks do not
operate building equipment or prove physical MS/TP timing.

`tests/test_bacnet_command_scalars.py` checks actual UDP analog Real/Double
round trips, restart ownership, multistate bounds, and refusal of numeric
strings, booleans, nonfinite values and wire overflow before any write.
