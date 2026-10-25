# CAF Device instance changes

Open a CAF file and use **Device settings · Instance number** to prepare a separate
application copy for commissioning. The editor discovers the root Device identity
from the archive; it does not choose a controller model or manufacture an I/O list.

1. Upload the full CAF obtained from the intended controller or its verified
   application archive. A standard BACnet File capture may contain only MOI data
   and is not interchangeable with a complete CAF.
2. Check the displayed application identity and current instance. Enter the
   reserved new instance, from 0 through 4194302.
3. Choose **Review CAF instance change**. The review binds the proposal to the
   original archive hash, old instance and exact new number.
4. Choose **Save CAF instance copy**. Keep the original for recovery. Open the
   resulting copy in compatible, licensed CCT/PCT and validate the application and
   required controller packages before commissioning it.
5. In CCT/PCT, select the exact physical controller and use the vendor's
   **Transfer to Device** workflow. Read back its identity at the same physical
   route afterward, check that the old instance has disappeared there, and verify
   its I/O and supervisory communication.

Saving a CAF copy is a local file operation. This feature does not provide an
application transfer endpoint or claim the controller accepted the new number.
Native transfer compatibility and physical acceptance require separate evidence.

## Native identity relationship

For the supported ZIP/XML representation, the Device instance appears in both the
root object's `objectid` attribute and property 75's `BACoid` value with type 8.
Both fields change together. Existing internal references such as `8-1`, peer
references, controller release metadata, logic, parameters, I/O and nested expansion
objects retain their exact XML bytes. ZIP entry metadata and the archive comment
are preserved. A no-op export returns the original archive bytes.

The editor refuses an ambiguous root, inconsistent identity fields, objects outside
the root, unsupported encodings for byte edits, noncanonical numbers and stale or
altered reviews. This narrow editing profile does not validate every controller
application format or perform native compilation. Other pending scalar, wiring or
terminal drafts are excluded from the saved instance copy and remain visible.

## API

After `POST /api/caf` uploads an archive, use its returned SHA-256 as `{id}`:

- `GET /api/caf/{id}/device-instance` inspects the identity.
- `POST /api/caf/{id}/device-instance/preview` takes `source_sha256`,
  `expected_instance` and `new_instance`.
- `POST /api/caf/{id}/device-instance/export` takes those fields plus the returned
  `plan_sha256` and downloads a CAF copy. Response headers retain the source,
  output and review hashes. The cached original remains unchanged.

Mutations require the existing local session token. Unknown fields, including
controller-write flags, are rejected. These endpoints never open a field interface.

The vendor documents that instance/name changes are written during
[Transfer to Device](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/15.0/Working-with-the-Trunk-Utilities/Working-with-the-Trunk-Utilities-Steps/Reading-and-Writing-Attributes-Online).
The file editor supplies the identity change in the application archive for that
workflow; an ordinary BACnet property-write denial must still remain a denial.
