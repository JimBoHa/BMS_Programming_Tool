# Change a controller's BACnet instance

**Connect → Change controller instance** sends a standard `WriteProperty` to the
selected controller's `Device.object-identifier`. It changes the controller's
Device instance, separate from the **Client device instance** used to open the
engineering interface. The MAC, DNET, application and supervisor references are
unchanged. Supported transports are direct BACnet/IPv4 and an explicit IPv4
router plus routed `DNET:MAC`. Direct serial MS/TP and foreign-device connections
are outside this UI profile.

## Web UI steps

1. Open the intended BACnet/IPv4 interface in **Connect**. Stop field polling and
   COV monitors, and release this app's owned point commands.
2. In **Routed BACnet discovery**, click **Find local routers**, then choose a
   **Router**. Its advertised networks load into the **Trunk / BACnet network**
   dropdown. For a known or remote router, enter its address and click **Read
   router networks** instead. Local discovery sends one bounded local-subnet
   Who-Is-Router-To-Network query; it does not search remote networks.
3. Choose a trunk, click **Scan selected routed network**, choose a **Controller**
   from that scan, then click **Modify selected controller**. The app fills the
   exact router, network, MAC address and current Device object and scrolls to
   the instance-change panel. Verified names from the shared Scan inventory
   appear when available; duplicate instances remain separate by address/route.
   Changing the router/trunk or starting another scan clears the old target and
   review. Direct-IP targets can still be entered manually or chosen in **Scan**.
4. In **Change controller instance**, check the controller address, current
   `device,instance`, and router/network for routed targets. Enter a new integer
   from **0 through 4194302** that is reserved across the BACnet internetwork.
5. Choose **Review instance change**. This is read-only. Review the live name,
   model, firmware, old/new instances and physical route. The app queries only
   the new number, for one second, on the selected remote network or bound local
   IPv4 subnet. A response blocks Apply. Silence does not prove uniqueness,
   especially for offline devices or other networks.
   Review also shows a separate **Instance write method** assessment. A clear
   collision query does not establish property-write permission. Without a
   matching retained denial, support is explicitly **unverified**; Apply remains
   a single attempt that the controller can reject.
6. Confirm the site-wide allocation and choose **Apply controller instance
   change** within 60 seconds. The app repeats the collision query and identity
   reads before sending one typed `ObjectIdentifier` write to the old Device
   object. There is no priority, array index, retry, reset or application download.
7. Look for **Result: verified** and **Readback: verified_new** at the same
   station with the same name/vendor/model/firmware/application version. Download
   the receipt. Refresh discovery, use the new ID, and update any supervisor,
   trend, alarm or project references through their normal commissioning process.

Changing a target or proposal invalidates the displayed review. A newer review
for the same station supersedes older tokens. A token is usable once and belongs
to the exact application instance, interface configuration, target and identity.

## Rejection and uncertain outcomes

Some controllers expose `Object_Identifier` as read-only or require a vendor
transfer workflow. A BACnet Error/Reject is shown explicitly, with the native
reason. This profile does not claim support for a particular manufacturer's
firmware merely because its Device metadata is readable. Johnson Controls CCT
[documents that its Read/Write Attributes operation does not write device name
or instance](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/15.0/Working-with-the-Trunk-Utilities/Working-with-the-Trunk-Utilities-Steps/Reading-and-Writing-Attributes-Online);
those settings are written during Transfer To Device. This feature supplies the
standard BACnet property-write path, not CCT application transfer or a guessed
proprietary command.

A lost reply, cancellation, delayed application, or failed readback can leave
**unknown** even if the controller changed. A valid SimpleACK alone is not a
verified change. The app never retries or rolls back automatically. Choose the
retained receipt and **Read back instance (no write)**. It tries the proposed ID,
the old ID, then the wildcard Device read at the original exact station; it
never broadcasts a write or locates the target by instance ID alone.

`verified_old` after an uncertain dispatch does not prove that a delayed change
will never apply. Another write to that station remains blocked until a matching
`verified_new` readback resolves it. A different identity remains unresolved.
For routed targets this admission check uses the canonical network number and
MAC, independent of the selected IPv4 next hop. Choosing another router or
opening another app instance cannot permit a second uncertain write to that
station. The receipt retains its exact original router for readback. Reused or
ambiguous network numbers are blocked conservatively; this is not proof that
two routes identify the same physical controller. Existing journal records and
their evidence bytes are retained without a schema migration.
Continue vendor commissioning outside this profile if a controller requires it.

## Retained write permission and native commissioning

After a validated `property: write-access-denied` reply, a fresh review at that
station with matching name/vendor/model/firmware/application metadata returns
`method_assessment.state = write_access_denied` and `can_apply = false`. This
decision applies to any manufacturer. A model name or manufacturer ID alone
never determines writability. Timeouts, uncertain dispatches, generic Rejects
and unrelated property errors do not become permission evidence.

The backend checks the retained denial again after fresh identity reads and
before dispatch. A prior review cannot authorize another write after a different
app instance records a matching denial. Restarting the app, changing the proposed
number, changing the routed next hop or spelling a MAC in hexadecimal does not
erase it. Other stations with the same Device instance remain independent.
Changed identity metadata receives a new, unverified assessment. Metadata is not
device authentication, and a denial does not prove a permanent read-only property
or identify the controller's internal reason.

The assessment cites the original receipt and its hash/time. Older sealed
receipts with the exact native error text remain usable without rewriting their
bytes or adding a database migration. New receipts also retain the validated
error class and code separately. Existing uncertain-write guards take precedence;
this change does not permit retrying an uncertain operation.

For CCT-managed Johnson Controls families, blocked reviews include the documented
**Define Hardware → Network Settings → Instance Number (BACnet ID)** and
**Transfer to Device** route. The family match selects guidance only. The
manufacturer's documentation explicitly excludes instance changes from Read/Write
Attributes Online. Obtain a compatible tool/package and a verified original CAF,
then review the application and interruption before an external transfer. A
standard BACnet File capture is not a complete CAF backup. Duplicate-ID device
selection limitations must be resolved in the manufacturer's tool before transfer.

**Native CAF transfer is not implemented in this app.** The repair prevents
another known-denied standard write and explains the missing commissioning
method; it does not make that property writable, implement the vendor loader,
or claim that a controller was modified. No private-property fallback, reset,
application download, retry or rollback is attempted.

**Download commissioning handoff (JSON)** exports the exact reviewed target,
identity, current/proposed instance, dated collision check and documented next
steps. It excludes the one-use token and review hash. It is instructions only,
not a CAF, backup, executable transfer or write authorization. After an external
transfer, select the original receipt and use **Read back instance (no write)**.
Only matching `verified_new` readback establishes the observed new identity;
the original rejected attempt remains immutable. Start any post-change observation
period after that verification, not after a rejection or a handoff download.

Regression checks use authored direct and routed UDP controllers. They cover
permission assessment across manufacturers, legacy receipts, app restart,
different proposals, alternate routers, duplicate-ID station separation, a denial
arriving after review, continued readback, API bypass attempts and the browser's
blocked Apply/handoff behavior. No further site write is needed for these tests.

## Evidence and API

`/api/bacnet/device-instance` provides `GET /status`, `POST /preview`, `POST
/apply`, `POST /cancel`, `POST /readback` and `GET /receipts/{id}`. Mutations
require the existing loopback session token. Number fields reject Boolean,
fractional, wildcard and string values. Preview and readback send no writes.

The local `studio.sqlite3` retains immutable intent/result records and append-only
readbacks with SHA-256 evidence seals. The intent commits before the confirmed
write can transmit; a missing result after restart is explicitly uncertain.
Results bind their original intent bytes. Receipts are not evicted automatically:
the journal admits at most 1024 attempts, 4096 readbacks and 32 KiB per record.
Export receipts and archive the state database before managing a full journal.
Hashes detect changes to retained evidence; they do not authenticate a device or
prove that its new number survives a later reboot.

Actual UDP tests cover direct and routed typed writes, two duplicate-ID routed
stations, a wrong cached next hop, replies arriving from the wrong router,
collisions, stale identities, replay/expiry, write rejection, lost/wrong ACKs,
unchanged readback, cancellation, journal failure, intent-only restart and
read-only reconciliation. API/browser tests exercise the production routes and
UI with authored BACnet peers. No physical-controller instance write was used
to validate this feature; acceptance and persistence on site hardware remain
unverified.

## Interface observations and retained receipts

The target and new-instance fields become editable after the current connection
status and its default target have loaded. Receipt history and receipt downloads
remain available while disconnected. A readback is attached only to the receipt
that requested it; an earlier history request cannot replace that receipt while
the readback is pending.

Scan history is retained when an interface changes. The guided selectors reuse a
name only when its metadata was observed in the current UI connection context
and the original metadata connector configuration matches the current interface.
Opening or closing an interface invalidates that reuse, including reopening the
same configuration. Otherwise, the selector shows the address and Device object
without presenting an old name as a current observation. Reopen the interface
when moving to another network; an unchanged address alone cannot identify a
physical network or authenticate a controller. Review still reads live identity
before every instance write.

Cancellation runs on the operation's event loop. Cancelling a dispatched write
still leaves an uncertain receipt when its outcome cannot be verified; it does
not undo a transmitted request.
