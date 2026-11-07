# Retained application size and observed controller capacity

In **Program → Native backup defaults**, select and inspect a retained backup.
Open **Application size and capacity**. **Inspect retained application size**
reads only the original files on this machine and reports actual archive bytes,
expanded native bytes and record/diagram counts. It remains useful offline and
does not merge saved values, modify originals or populate a model inventory.

With the backup's original controller and plain BACnet/IPv4 interface open,
**Read controller application capacity** makes a separate read-only observation.
The selected route/interface is reused; no address is re-entered. The response
shows the controller-reported File3 capacity, observation time and the headroom
for the **original retained archive**. A retained archive exceeding the reported
capacity is displayed as such. That comparison is advisory.

This implements `COMM-NATIVE-CAPACITY-001`, source profile
`native-file3-size-evidence/1` and observation profile
`native-file3-capacity-evidence/1`, under JCI-06/RES-001/UI-003. It extends the
existing native transfer path's File3 capacity check into an explicit resource
view; that transfer admission check is unchanged.

## Scope of the measurements

- Archive bytes and expanded-image bytes come from the actual original File3.
  Class and diagram counts come from the parsed original records. They describe
  historical source, including metadata records, rather than a current live
  program or a generated inventory.
- The current observation checks the responding identity and reads File3
  property 3380 through the existing owned, single-attempt native exchange.
  It requires the original route, Device, recorded identity and interface;
  mismatch, stale source and another active native operation are refused.
- The response must match the requested object/property without an array index
  and contain one positive one-to-four-byte native Unsigned. Full receive
  attribution and interface/socket guards remain in force. The browser checks
  source/observation seals, native APDU fields/value, route/interface and the
  exact arithmetic of the size comparison before displaying or exporting it.
- This query reads no backup credentials or application files, changes no
  credentials, sends no backup-state/restore/write command, and creates no
  review token or transfer journal intent. Timeout or cancellation never
  retries the query or sends a recovery write. A later query uses a new ID.

The observed capacity is **not free RAM, free flash, scan time or complete
resource accounting**. The current program is not read. Saved settings remain
unmerged in the archive-size comparison, so a freshly compiled restore payload
can have a different size. Field transfer still captures and compiles fresh
settings and checks the controller-reported capacity immediately before
dispatch. Neither a positive comparison nor loading/exporting this evidence
creates transfer authority or qualifies packages, runtime, CCT or physical
controller acceptance.

## Ownership and evidence

Source, target, interface, task, disclosure and page-lifetime changes retire
pending observations and cached export handlers. The in-flight query shares the
existing native operation gate and workspace busy ownership. **Cancel capacity
query** retires its result and requests cancellation of its exact operation ID;
the next query remains usable. Late responses cannot populate a different
source or selected controller. Historical source measurements retain their
source label separately from observed controller data.

**Save exact capacity evidence** downloads the original verified JSON response
bytes. It includes the original source, selected route/interface, responding
identity, native reply evidence and observation time. It is a recorded
observation, not an imported review or current-program assertion.

## API and qualification

| Token-protected route | Behavior |
| --- | --- |
| `POST /api/bacnet/controller/native-application/resources/source` | Inspect actual retained source sizes; no interface required. |
| `POST /api/bacnet/controller/native-application/resources/read` | Explicit selected-controller identity/capacity query, with the exact capture/snapshot and operation ID. |
| Existing native cancel route | Cancel only the owned query ID; no replay or write. |

Qualification uses authored localhost direct and routed BACnet peers, malformed
native replies, source/identity/interface mismatch, lost-response/cancellation,
busy-operation guards, original-file preservation and source/installed browser
workflows. It uses no site device, Bluetooth adapter or VM. Wider RAM/flash/scan
budgets, arbitrary native allocation and physical acceptance remain unfinished.
