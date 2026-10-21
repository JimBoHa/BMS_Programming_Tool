# Retire unsent serial requests on timeout and cancellation

A confirmed BACnet request can time out before the MS/TP client obtains a token. Retiring its BACpypes transaction alone previously left the NPDU in the serial transmit queue, allowing a stale request to transmit later.

`confirmed_exchange` now gives each serial exchange an opaque owner. The owner travels through BACpypes `pduUserData`, APDU/NPDU encoding and the link adapter into the queued frame. The caller's previous `pduUserData` is retained and restored. Completion, timeout and cancellation retire that owner's unsent application frames, including a frame waiting for turnaround. Other exchanges, unowned data and token/control frames remain intact. A retired owner's later delivery into the link layer is ignored.

Retirement and the worker's serial write share a lock. The caller either removes an unsent frame or waits for an already-started bounded write to finish. The existing one-second serial write timeout remains the upper bound for that driver operation; this is not a real-time timing guarantee. A request already transmitted cannot be unsent, and the master continues normal token/control traffic. The transmit status includes a count of retired application frames.

This change does not open an interface, discover a controller or add a command. It also does not verify physical USB/RS-485 timing, BTCVT or controller interoperability.

The real POSIX pseudoterminal regression starts a confirmed read before the first token, verifies that the owner survives the complete stack, then cancels or times out. After the real peer starts and the master obtains a token, no stale read appears. A new successful read reuses the retired invoke ID and receives the independently fixed-wire value. A separate test verifies that unrelated requests and token frames survive retirement. Existing public CRC/framing, master, application and HTTP serial checks continue to pass.
