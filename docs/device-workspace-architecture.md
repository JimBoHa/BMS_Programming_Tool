# Device-driven workspace

Connecting a controller establishes one authoritative protocol target. Device
tabs read that target's published configuration and values. An open local graph,
example project or CAF never supplies a connected controller's inventory.

## Common acquisition path

The BACnet adapter discovers the controller's manufacturer, model, firmware,
application version, protocol services, object types and object-list. Inventories
are paged directly from the device. They are not selected from a model template.
The same path supports new model names and different I/O counts without adding a
model registration. Standard and installed vendor object schemas select property
decoders by protocol object type and the controller's observed vendor ID.

Points & I/O loads the actual inventory and reads visible points automatically.
The default live refresh is ten seconds; reads are sequential, bounded and never
overlap within the view. Opening configuration reads exposed properties; a
property name or number can request additional attributes. The original native
evidence is retained. Standard primitive wire tags can be decoded without a
manufacturer property schema; proprietary context-tagged structures remain
opaque when their schema is unavailable.

Structured views and groups retain their actual references and annotations.
Expansion modules may be represented as their own BACnet devices, as structured
groups, or as vendor-specific assignments within their host. The common adapter
does not invent module counts, unused terminals, wiring, or physical health from
a model name. Manufacturer hardware readers can add evidence through their own
protocol/format support.

## Source and lifecycle

A source includes the interface, router endpoint, network, remote station and
Device object identifier. A Device ID alone does not identify a physical device.
Reads pin the actual transport source and validate native responses. Each batch
checks Device identity before and after acquisition; property reads also check
the selected object's identity. Target changes discard pending display results
and write reviews. Closing or leaving a live view stops future refreshes. Failed
or partial reads label old values as last known; missing values never become zero.

## Actual application information and native logic

Program defaults to the connected controller's actual application metadata and
exposed Program objects, including their state. Local graphs and files require
an explicit local-source selection and retain their own drafts.

An editable control application is not defined by standard BACnet point reads.
Native application readers implement a separate protocol/format contract and
report capabilities from observed device evidence. They must return an actual
field application and its source, rather than reconstruct a guessed program from
point values, firmware strings or a local example. The reader contract belongs
to an application protocol/format family, not an individual installed controller.

The common BACnet workspace currently reads exposed configuration and live data.
No native application reader is registered in this workspace yet. In particular,
the JCI application upload required for an editable controller logic diagram
remains unimplemented; the Program view reports that limitation. Existing offline
CAF tools and adapter-specific transfer tools remain separate capabilities.

## Verification

Authored protocol peers cover different vendor IDs and model names, inventories
with 0, 1, 5 and 7 exposed I/O groups, native value changes, inventory pagination,
source pinning and shared-Device-ID target changes. Browser checks verify that
connecting after local graph work opens actual device views and does not substitute
the local graph. No live controller writes are used to verify the workspace.
