# Read-only BACnet Device details

`DeviceDetails` reads standard metadata from an explicit Device object through
an already open BACnet/IPv4 interface. It neither opens an interface nor changes
controller values, subscriptions, programs, the engineering connection
configuration or owned-command records. No discovery broadcasts or private
services are issued.

`POST /api/bacnet/device-details` accepts:

```json
{ "address": "192.0.2.42", "device": "device,132007" }
```

A routed request additionally supplies its exact next hop and network:

```json
{
  "address": "3001:7",
  "device": "device,132007",
  "router": "192.0.2.32",
  "dnet": 3001
}
```

These are documentation addresses, never automatic test targets. Direct targets
must be literal unicast IPv4 addresses with an optional UDP port. Routed targets
must be explicit matching `DNET:MAC` addresses with 1–8 MAC bytes and a selected
IPv4 router. Wildcard Device instance 4194303, broadcast targets, hostnames,
prefixes and conflicting embedded routes are refused.

The selected read-only route may differ from the main engineering route. A
scoped handler pins outgoing requests to that router with the selected remote
destination and Hop Count 255, and rejects replies for that remote source that
arrive through another IPv4 router. The main connection configuration and
command journal remain unchanged. Normal native peer/route caches can learn
from accepted BACnet traffic. Temporary handlers are restored on success,
failure, cancellation and deadline. Unrelated in-flight reads retain their
normal delivery path.

The first property verifies the requested Device's actual `object-identifier`.
The ACK source, object, property and array index must match the request, and the
identifier property must equal the acknowledged Device. Failed identity checks
stop collection and retain the requested identity with `identity_verified:
false`; they never replace it with the unexpected responder's identity.

## Metadata and genuine Program names

The report keeps Device name, description, vendor identifier/name, model,
firmware revision, application software version, protocol revision,
segmentation support, accepted APDU size, system status and location. Every
requested field is present in `properties`, with `null` until a valid supported
value is read. `property_status` distinguishes `ok`, `unsupported`, `error` and
`not_read`, with a local UTC receipt time and error text. Unknown optional
properties and timeouts retain other completed values.

`application-software-version`, Device descriptions and firmware revisions are
never relabelled as program names. Names come only from actually advertised
standard BACnet Program objects, with each object's own `object-name`,
`description` and numeric `program-state`. `program_names` contains only names
successfully read from those objects; `programs` retains their object identities
and per-property evidence.

`programs_status` means:

| Status           | Evidence                                                                                  |
| ---------------- | ----------------------------------------------------------------------------------------- |
| `exposed`        | A completed bounded inventory found Program objects and their requested fields were read. |
| `not_exposed`    | A completed, validated object list contained zero standard Program objects.               |
| `partial`        | A deadline or Program metadata failure left some requested evidence incomplete.           |
| `unavailable`    | The inventory could not be validated or read.                                             |
| `limit_exceeded` | The object-list or Program-object count exceeded the bounded profile.                     |
| `not_read`       | Identity failed or inventory collection did not start.                                    |

An empty name array alone does not establish `not_exposed`. Controllers may run
native logic without exposing standard Program objects; this service does not
decode that logic, obtain an editable CAF or guess its authoring filename.

## Bounds and provenance

The default whole network collection, including connector-lock admission, has
a 15-second deadline. Each read has a 1.5-second timeout and requests start at
least 50 milliseconds apart. Collection is sequential. Stopping a client batch
does not start subsequent device requests; an admitted request remains bounded.
Tests may explicitly instantiate shorter limits and zero gaps for owned peers.

Object-list discovery refuses counts above 512. A whole-array request is used
only when known local/remote APDU capacities allow five encoded bytes per
ObjectIdentifier plus 32 bytes of reserved framing, and at most 85 entries.
Otherwise bounded indexed reads retain their progress. The final count must
match; duplicate/reserved object identities or a missing verified Device stop
validation. A completed ordered list receives a SHA-256 hash. In particular,
84 objects fit the conservative whole-array profile at a 480-byte APDU capacity,
so a normal no-Program inventory does not require 84 separate reads.

At most 16 Program objects are enriched. Their original total and truncation
remain explicit. Metadata strings above 4096 UTF-8 bytes and nonstandard scalar
values fail visibly instead of being silently shortened or renamed. Deadlines,
large inventories and caps never become a claim that no programs are exposed.

Each report retains the selected address/Device/router/network, original
connection configuration, requested property statuses, inventory method/counts,
errors and local UTC start/finish/receipt times. These are acquisition times,
not fabricated controller clock values or quality assessments. A changed list
of the same size or values changing between reads can still escape count checks;
the report is read evidence, not an atomic device snapshot or program backup.
Local audit failure is separate from successfully retrieved data.

## Local verification

`tests/test_device_details.py` uses actual native BACpypes UDP Device/Program
objects and an authored router that independently checks literal BVLC/NPDU
framing and only accepts ReadProperty. It verifies real Program names, an
84-object device with no Program objects, APDU-aware whole/indexed inventories,
identity and ACK failures, metadata faults, caps, deadlines, and exact routed
source pinning. A second actual local command remains owned and releasable while
details use a different route; an unrelated in-flight read survives temporary
handlers. Cancellation removes the owned transaction and restores hooks.

These tests use loopback peers. They do not access site devices, credentials,
Bluetooth or an external VM, and do not establish native application upload or
universal manufacturer compatibility.
