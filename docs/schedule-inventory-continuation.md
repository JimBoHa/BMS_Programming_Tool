# Continue an interrupted schedule inventory

A finite Calendar/Schedule discovery read now retains its last completed
Object_List offset even when its operation deadline expires or the operator
cancels during a later indexed read. The unfinished index remains the first
index of the next explicit page. Completed property evidence and the original
report seal remain available.

In Schedules, **Prepare next Object_List page** copies that report's offset into
the current form. It is available only for the same explicit controller and
route. Preparation performs no controller query. Choose **Read native schedules**
to acquire another independent page; reduce the page limit if the response
budget expires. Pages do not establish a frozen or exhaustive inventory.

The cursor tracks completed Object_List entries, not completion of every
discovered schedule or calendar's fields. If an interrupted page identified an
object without inspecting it, select that object explicitly for a separate read.
Continuing discovery does not fill missing fields from an earlier report.

Request and operation deadlines, source and identity guards, read budgets,
transaction cleanup and the single-attempt policy are unchanged. There is no
automatic retry or background continuation.

Independent UDP checks interrupt discovery after two completed entries, verify
the cursor and evidence seal, and resume only through another explicit request.
The browser check follows the controller workspace and verifies that preparing
the next page changes the form without another field request.
