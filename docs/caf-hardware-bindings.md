# Offline native CAF terminal edits

**CAF files → Offline CAF terminal binding** can move an existing local analog
or binary input between universal terminals on the same base controller. It
downloads a separate native CAF containing the actual edited records. It does
not compile that file, transfer it, change a running controller, or move wires.

The initial profile covers the observed `MS-VMA1630-0`, `FX-PCV1630-0`, and
`FX-PCV1615-0` models, CAF release modes 10.1/10.2, and hardware class version
1.0. All have three universal inputs. Manufacturer capacity references are the
[VMA installation guide, revision K](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/VMA1615/1626/1628/1630-VAV-Controllers-Installation-Guide/K/Technical-specifications)
and [FX-PCV installation instructions, revision H](https://docs.johnsoncontrols.com/bas/r/Facility-Explorer/en-US/FX-PCV1615/1626/1628/1630-Programmable-VAV-Box-Controllers-Installation-Instructions/H/Accessories/Technical-specifications).
These establish physical capacity, not a published CAF editing specification.

The reader verifies one native controller root, its model and external Device
identity, and the exact local parent references of existing physical inputs.
Class 240 identifies observed AI hardware records; class 242 identifies BI
hardware records. Property 75 retains the external BACnet identity, which is
different from the native class number. A movable input must have matching
property 519 (`unsignedByte` slot) and property 31 (`string`, `UI INn`).

A reviewed edit changes only those two scalar leaves. Object identity, item
references, signal setup/curve, application logic, connections, unknown
properties, and unrelated XML bytes remain unchanged. The original ZIP entry
metadata and archive comment are retained. An unchanged request returns the
original archive bytes exactly. Exported bytes are reopened and the resulting
hardware bindings must match the exact requested change.

Source SHA-256, original slot, and a deterministic preview-plan SHA-256 guard
export. Source or destination changes require another preview. Occupied slots,
conflicting identities, unknown physical-looking records, unsupported models
or versions, SA/IOM hardware, and explicit SA/device-host bindings are refused.
The integrated differential-pressure input (`AI1-Int`, slot 4) is fixed and
cannot be moved. This profile neither creates new points nor changes electrical
signal modes. It cannot relocate an alarm between expansion modules.

Review also checks that the two edited leaves support loss-preserving byte
replacement. CDATA and comment-bearing leaf encodings are refused before an
edit can be reviewed; an unchanged request can still return the original bytes.

Authored public fixtures test the native record edits and refusal cases without
redistributing building programs. Optional compatibility tests edit authorized
private CAFs entirely in memory and verify the source files remain unchanged.
Reparsing our output establishes observed archive consistency. Acceptance in the
matching CCT/PCT, vendor compilation/simulation, bench transfer, readback,
restart persistence, and restoration remain unverified. Those checks are still
required before relying on an edited file for field work.
