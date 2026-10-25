# Change a connected controller name

Open the exact controller from its router/trunk scan or verified direct address.
Choose **Overview → Edit controller name**, read its application backup, enter the
new name and select **Review name change**. Confirm the name-only change and the
reviewed application transfer, then select **Apply controller name**. Require the
verified receipt and application readback before another change.

This workflow uses the connected native application protocol/format family. It
does not launch a vendor runtime or select replacement programs by controller
model. Unsupported formats and character encodings stop before transfer.

The compiler edits the root Device-name property, retaining its native character
encoding and reframing the root record if its length changes. It preserves the
Device instance, engineering references, physical address, unknown records and
all other application properties. Names must be nonempty, bounded to 128 UTF-8
bytes, and contain no control characters or surrounding whitespace.

A name-only review must request the existing instance. It cannot combine a rename
with an instance reassignment and does not allocate another number. The operator
confirms the name separately from an instance reservation.

Each application transfer retains the controller's own original application and
parameter files. Immediately before transfer it captures and merges fresh saved
values. The native readback must match the reviewed payload; a separate byte and
parameter comparison permits only the reviewed name change and documented
runtime outputs. Source/route changes, expired reviews, capacity
failures and missing confirmations prevent dispatch.

Runtime outputs include advancing counters and the native Flow Primitive's
**Autocalibrate Offset**. The latter is a calculated zero-flow correction that
the application's automatic calibration sequence can refresh after a reload;
the receipt records its previous and current values separately. This exception
does not permit changes to manual offsets, K factors, flow limits or setpoints.
See Johnson Controls' [Flow Calculation attributes](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/14.0/Setpoint/Miscellaneous-Modules/Flow-Calculation/Flow-Calculation/Attributes-Flow-Calculation)
and [autocalibration states](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/13.1/State-Generation-Modules/VAV-Specific-Sequencing/Autocalibration-Sequence-v50/Primary-States-Autocalibration-Sequence).

The existing one-use plan, owned transactions and durable transfer receipt apply.
A lost acknowledgement or an unverified name/application keeps the result
uncertain and blocks another transfer. Use **Read back application and name**;
do not resend a transfer to resolve an uncertain outcome.
