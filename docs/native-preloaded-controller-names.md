# Native preloaded controller names

This backend pilot supports a CVM family's discovered native loader **Device
Name** configuration point. It reads the selected VAV Balancer's exposed area,
maximum, occupied minimum and pickup gain separately. Those flow settings remain
read-only: a readable output or owner property does not qualify a write method.
Instance changes retain their existing commissioning workflow.

The API is under `/api/bacnet/controller/native-vav`: `source`, `preview`, `apply`
and explicit read-only `reconcile/{operation-id}`. The selected route, Device and
discovered Balancer travel with every request. The caller supplies the discovered
CharacterString Value object; no fixed object instance or site inventory is used.
There is no new navigation destination or tile. Selected-controller interface
integration remains to be completed before treating this as a finished UI workflow.

Before review and dispatch, the service verifies the exact interface/router/trunk,
operational Device identity, vendor/model/firmware/application version, native root
reference, loader-point label, absence of a priority array and matching current
point and native-owner names. A 120-second one-use review precedes one typed
configuration write with no BACnet priority. Durable intent, exact reply evidence,
point readback and independent native-owner readback distinguish verified,
rejected and uncertain results. Observed VAV scalars and other identity fields
must remain unchanged. This is a bounded property snapshot, not an application
backup or proof that every controller setting has been inventoried.

Native Name property 2390 and standard Device Object_Name property 77 are recorded
separately. The latter can lag the loader configuration. Reconciliation verifies
both the bound configuration point and native owner and does not infer a lost
acknowledgement or repeat a write. An uncertain attempt blocks further changes at
the physical station, including when a caller supplies another Balancer identifier.

Field qualification on a CVM with firmware 10.0.0.2125 and application version 10.5
confirmed one native name change by configuration-point readback, native Name,
native controller information and subsequent supervisory discovery. No vendor
runtime was used. Ordinary flow-property and exposed-point writes were rejected;
those attempts did not establish balancing support. Full factory-image editing,
output reallocation, persistent airflow commissioning across a restart and other
firmware/controller families remain unqualified.

Authored peer regressions exercise typed dispatch without a priority, one-use and
stale-source rejection, native versus standard-name lag, uncertainty/reconciliation,
observed-setting preservation and rejection of unsupported flow/instance edits.
Field archives, routes, names, credentials and receipts stay outside the repository.
