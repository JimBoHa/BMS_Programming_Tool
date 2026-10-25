# Connected native application instance changes

Overview → Edit instance number → **Connected application transfer** operates on
the selected physical controller through the application's own BACnet connection.
It does not launch CCT/PCT, call a vendor SDK, require a Windows VM, or select point
inventories from controller model names. The standard property-write method
remains separate: a recorded permission denial continues to block that method.

## Operator workflow

1. Open and verify the controller through its exact IPv4 endpoint or router,
   network and station. Stop owned commands, field polling and COV monitoring.
2. Choose **Connected application transfer** in the instance editor. Configure
   the controller family's backup and application-transfer credentials once on
   this machine. Credentials are private local state, absent from receipts and
   source control.
3. **Read application backup**. The app verifies standard and native identity,
   enters backup mode, captures the actual application plus Static and Dynamic
   parameter files, ends backup mode and verifies identity again. Save the
   original backup ZIP for independent retention.
4. Enter the reserved instance and **Review application instance change**. The
   review identifies the exact station, original source, proposed number,
   application edits, parameter preservation policy and collision-query scope.
5. Confirm the number's internetwork allocation and the application transfer.
   **Apply application instance change** makes a fresh backup and collision
   query. The application and parameter directory must still match the review;
   fresh saved parameter values are merged immediately before transfer.
6. The app transfers the application once and reads back the Device identity and
   application from the same station. **Verified** requires the complete native
   application digest to match the transmitted application as well as matching
   controller identity. Then refresh discovery and review dependent references.

A transfer can interrupt controller operation while the controller activates its
application. A protocol acknowledgement alone is not verification. A timeout,
wrong reply, cancellation or lost acknowledgement after dispatch leaves an
unresolved durable receipt. Use **Read back application and instance**; do not
resend the operation or assume an automatic rollback. The app retains the
original bytes and transfer evidence across restarts.

## Implemented protocol and format family

The first native adapter covers vendor 5's MCE command envelope and tagged MOI
application generation 1, including ordinary single-member gzip archives. Native
controller-information replies must agree with the standard Device identity.
Models and expansion counts do not select the parser or manufacture application
records. Unrecognized framing, datatypes or saved parameter layouts prevent a
transfer while retaining readable original evidence.

The transport uses source-pinned BACnet/IPv4, directly or through an explicit
IPv4 router. Backup uses ReinitializeDevice start-backup/end-backup and bounded
AtomicReadFile requests for the family application's virtual Files 11, 12 and 3.
Application transfer reads the controller's application capacity (File 3 property
3380) before entering restore and refuses an oversized payload. It uses
start-restore, a five-second application-storage preparation interval,
AtomicWriteFile for File 3 only, and end-restore. A start-restore acknowledgement
precedes storage readiness; sending the first block immediately can lose that
request and leave the controller reporting download required. Preparation is
journalled, and cancellation during it retains an unresolved transfer without
sending an application block. Boot and firmware writes are excluded. Direct MS/TP, BBMD/foreign
device transfer, firmware conversion and background downloads are outside this
profile.

The independent compiler validates every length-delimited object, including
extended records and unreferenced metadata. An instance edit patches exactly two
four-byte typed identities: the root native object header and the root Device
Object_Identifier property. It does not search and replace numbers or rewrite
peer identifiers. Gzip output receives a regenerated CRC32 and size trailer.

Saved parameters are merged using the captured parameter directory's native
class, object selector, property, storage type and offset. The compiler validates
slot bounds, overlap, complete dynamic storage coverage and per-value checksums.
Supported scalar storage is Boolean, unsigned byte/short/integer, signed short,
enumerated and IEEE single precision; supported inline values retain their
BACnet tags. Unknown application parameter types fail explicitly. Other object
properties, expansion records, opaque metadata and graph bytes are preserved.
The original Static and Dynamic files are retained unchanged; only the compiled
application File is transferred.

These three files constitute an application and saved-parameter snapshot. They
are not a firmware image, full BACnet internetwork backup, or claim of arbitrary
CAF logic editing. This change implements native connected instance editing;
other application edits require their own typed editor and validation.

## Ownership and recovery

Reviews bind the selected route, interface object/configuration, current
identity, original snapshot, proposed instance and credential revision. They
expire after 900 seconds, are consumed once, and are invalidated when edited,
cancelled, disconnected or superseded for that station. A fresh preflight also
checks review expiry before any restore request.

The default operation deadline is 1,800 seconds to cover the fresh backup,
application transfer and verified readback across slower routed trunks. A backup
can require hundreds of confirmed chunks even for a modest application. Each
individual File request still has its four-second deadline and one dispatch;
lost acknowledgements do not acquire automatic retries. The current operation,
review and per-request limits are exposed by the native status endpoint. API
clients must allow their HTTP request to remain open for the operation deadline.
An expired review still stops before restore, and any uncertain dispatched
transfer retains its receipt and requires readback rather than another apply.

Original snapshots and the exact outgoing application reach private durable
storage before a restore can start. A SQLite intent and per-dispatch event are
committed before the corresponding wire request. Requests use one native
transaction attempt, bounded chunks and an overall operation deadline. No
background retransmission, automatic replay, firmware reset or inverse write is
used for recovery. The journal blocks another application or instance attempt
while a prior native transfer remains unresolved.

Responses require matching original-unicast UDP ingress, physical source,
router, socket, invoke ID, service and exact APDU bytes. Readback remains tied to
the receipt's original station even when another controller shares its old
Device instance. Verification also requires the Device to report operational
status before and after application readback. An unchanged instance alone does
not establish recovery: download-required status remains visible and unresolved.

## Verification and current limits

Authored UDP controller peers cover the complete capture/review/apply/readback
path, stale plans, checksum failures, variable models and expansion counts,
changed sources, fresh collisions, lost acknowledgements and durable recovery.
The browser test exercises the same transport through the connected workflow.

A private field capture was acquired directly by this implementation. Its
parameter merge and instance edit were compared byte for byte with offline
reference compiler output. Vendor binaries, source captures and protocol
credentials are not repository fixtures or runtime dependencies. A single
physical application transfer has now been acknowledged and verified by changed
identity, operational status and an exact expanded-application readback. This is
one field acceptance result; it does not establish support for every model.
Read-only acquisition and offline binary equivalence alone do not establish
physical application acceptance.
