# Legacy actuator runtime state verification

The native ACS/DMCS 60 application definition declares actuator class 251,
property 978 as application-persistent, frequently changing UnsignedLong seconds.
It has no configuration/edit flags. Later data models remove that declaration.
The app retains a technical field description rather than inventing a vendor
display name or selecting an exception by controller model.

After a native transfer, the expanded application must still match the reviewed
image exactly except for the explicitly reviewed edit. Its original actuator
state default remains unchanged. A separately captured PSS value for 251:978 may
have advanced as the controller operated. For ACS/DMCS 60/60 only, an unsigned
32-bit, nondecreasing value is reported as changing runtime state. A decrease,
another datatype, another class/property, another data-model version or altered
application bytes still prevents verification. Counter wrap/reset requires
review rather than silently passing.

The receipt retains application and current saved values separately, including
existing binary change counts and elapsed times. The readback view displays
these differences within the existing transfer result. Stored/PSS readback is
not represented as a simultaneous live measurement or proof of motor movement.
This adds no actuator command, calibration, tuning adjustment or state write.

Authored tests cover version/class/property boundaries, decreased values,
changed application bytes and a complete owned UDP transfer with a separately
advanced PSS field and no PSS writes. The existing point-name browser workflow,
including phone layout and live-calibration evidence, remains qualified.
