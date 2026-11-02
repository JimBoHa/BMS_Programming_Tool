# Application types for omitted saved fields

A valid saved-parameter checksum establishes storage integrity. It does not
establish that the storage datatype is valid in a controller application. The
binary event timestamp described in [parameter storage](native-parameter-storage.md)
is one example: PSS uses an integer while the application defines a read-only
date/time structure.

Native field transfers now qualify every saved field materialized onto an
existing application record. Qualification uses the actual native class and
property, the recorded application version where required, and the resulting
application tags. It does not select objects, programs or inventories by model.
Root properties use the actual root record rather than an assumed Device class.

The first qualified group covers root timezone/DST settings, configured binary
counts and elapsed time, input-presence state, retained PID tuning fields, flow
calibration and control-sequence identifiers. The legacy actuator property 978
is qualified as an application-persistent Unsigned only for ACS/DMCS 60/60; later
data models do not inherit that declaration. An unknown property or mismatched
application datatype blocks capture eligibility and transfer review before a
restore can begin. Original application and PSS files remain available locally.

The storage merger remains independently usable for local analysis. Its ability
to decode a saved slot does not grant field-transfer eligibility. Identity,
point-name, Real/Boolean-default and wire-source transfers all enforce the same
qualification boundary before compiling a proposed field change.

Tests use authored native records and checksummed slots: unknown properties,
known properties with incorrect tags, unlisted Device classes, binary timestamps,
version-scoped actuator fields and an owned UDP capture/review with zero restore
requests for an unqualified field. This is an omitted-field datatype guard, not
general application compilation or support for every native property.
