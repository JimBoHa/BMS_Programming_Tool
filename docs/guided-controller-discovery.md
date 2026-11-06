# Connect through an NAE or BACnet router

The connection task follows **computer network → engine → reported network →
controller**, within the existing controller workspace.

1. Choose a detected **Computer network** and **Open interface**. A fresh setup
   suggests the operating system's default-route interface, or its sole IPv4
   interface. Saved connection settings and focused/manual drafts take priority.
   The list uses actual interface prefixes; listing it sends no discovery packets
   and does not open BACnet. Manual bind and advanced connection fields remain.
2. Choose **Find NAEs & routers**. One explicit action performs the existing
   local router-advertisement search and a separate local BACnet/IP Who-Is search.
   The latter also finds engines that do not advertise themselves as routers.
   A configured BBMD uses the existing IP discovery scope; local router broadcasts
   are omitted for that transport. No address range is guessed or swept.
3. Select an engine by its verified Device name, or filter by name/IP. Selecting
   it reads its reported networks, including the existing cached-binding fallback
   when no network advertisement arrives. Focus moves to the network selector.
4. Select a network and choose **Scan controllers**. Names are read for the
   responders and focus moves to the controller selector. **Open controller**
   verifies the exact endpoint, router, network and Device identity before opening
   its workspace.

Ordinary IP I-Am replies establish candidates, not proof of downstream routing or
NAE hardware. No vendor/model inventory supplies candidates or trunk numbers.
Endpoints merge using the default BACnet UDP port without merging separate
stations that share a Device instance. Conflicting identities at one IP endpoint
remain explicit and do not receive an arbitrary name. Engine names stay in the
engine picker, rather than populating the controller explorer before a trunk scan.

Names require identity/name/identity readback and matching interface/target evidence.
The engine picker requests a three-second optional metadata budget; the existing
Device-name endpoint retains its six-second default and accepts only a 1–6 second
budget. Slow labels can be retried and do not prevent selecting a candidate by IP.
Connection changes and same-configuration reopen retire pending engine, name,
network and controller replies. Name data from an old interface is never adopted.

Reported BACnet network numbers are retained. Cached short-address networks appear
first, with cached-address counts; other reported networks remain selectable.
The tool does not fabricate FC-1/FC-2 labels or assert MS/TP bus type from a cached
address. Cached choices require an explicit scan for current controller responses.
An empty search provides a next step: check the selected computer network or use
**Enter an engine IP address instead**. Numeric bounds, protocol settings and
response evidence are progressively disclosed.

## Verification

Authored loopback engines exercise genuine HTTP/UDP name reads, network selection,
trunk scans and controller opening with no typed network identities. Discovery
lists use authored evidence because Darwin does not deliver subnet broadcasts on
loopback; the underlying packet collectors have independent UDP tests. Checks also
cover duplicate Device IDs, old IP/name replies after reconnect, saved/manual
connection drafts, empty discovery, and the read-only interface-list endpoint.
Private field checks supplement these fixtures without entering the repository.

Legacy BBMD/point-command browser scripts still use obsolete pre-workspace
navigation. Their failures at that navigation do not qualify those separate
workflows; their protocol/backend checks remain independent of this UI slice.
