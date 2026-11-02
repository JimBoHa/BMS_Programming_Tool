# Live calibration versus stored application verification

A native File 3/11/12 readback verifies the transferred application and retained
saved values. A calculated output may subsequently change in the running
application without updating those files. A matching archive alone cannot prove
that the current calculation still equals its stored value.

Native transfer/readback now separately reads each discovered class 570 Flow
Primitive's Autocalibrate Offset (3506) after complete image/settings verification.
The profile uses the object's captured identity, source-pinned ReadProperty and
exact property echoes. It requires one finite native Real. It performs no write,
reset, calibration command or transfer replay.

Receipts and the existing identity/default/wire/point-name outcome views show
current values alongside the transferred application value, including calculated
differences even if the saved-parameter directory still equals the archive.
A missing captured value stays unknown. Unavailable reads and the explicit
32-module budget make the live report incomplete; they cannot mean “unchanged.”
Echo mismatches or malformed/nonfinite values leave verification uncertain.

The live report covers this known calculated output only. It is separate from
the complete stored-image/settings comparison and does not certify all runtime
state, sensor calibration, physical airflow, terminal wiring or control performance.
Values can continue changing after the reported readback time. No old calibration
value is forced back into the controller.

Authored tests cover a real runtime value differing from unchanged saved files,
no-flow applications, missing captured values, request limits, unavailable reads,
wrong echoes and malformed numeric values. The browser test uses an owned UDP
peer with independent live calibration values to verify that the difference is
visible alongside a verified point-name transfer.
