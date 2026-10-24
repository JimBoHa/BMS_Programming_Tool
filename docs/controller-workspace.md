# Using the controller workspace

Start with **Connect to a controller** or **Open a CAF file**. Library, History,
Settings and Help hold reusable assets, recorded information, communications and
reference material. Opening the start screen does not open a field interface.

## Connect and commission

1. Choose the connection transport and open the interface. Advanced BACnet/IP
   parameters are available under Advanced connection settings.
2. Under Discover & select, choose Router & trunk. Find local routers, select a
   router, choose one of its reported networks, then scan that trunk. A known
   router can also be queried by address. Direct IP discovery and known controller
   addresses provide shortcuts.
   If the router does not advertise its networks, the app discovers that router's
   Device identity and reads its cached address bindings. Those network choices
   are labelled cached and require a fresh scan; they do not prove current device
   liveness, an exhaustive network list or a physical trunk type.
3. Select the controller by its physical route and choose **Open controller**.
   The application opens the required route and reads the controller identity.
   An open interface alone is not a verified controller.
   Scan results read each responding controller's BACnet Device object-name and
   show that name beside its address and instance. Search by a name such as
   TB-3-201 or HP-3A. Names arrive sequentially for all returned controllers,
   without waiting for program inventories or browsing through pages. Failed
   lookups display Name unavailable and can be retried. The name read verifies
   the exact Device identity and route; it does not merge duplicate Device IDs.
4. Work in Overview, Points & I/O, Program, Schedules, Trends & Alarms or Changes.
   The selected target supplies downstream address and route fields. The header
   retains its name, Device instance, route and last verification age.
   Points & I/O opens the controller's object inventory and reads live values,
   units and native quality fields automatically. It does not require manually
   entering object IDs. Program defaults to actual controller application
   information and exposed Program objects. Local graph and CAF views require
   an explicit local-source selection. Native editable logic requires a supported
   application reader; the common BACnet reader does not provide that transfer.

To change an instance number, open **Overview → Edit instance number**, enter the
new allocated number and choose **Review instance change**. Review the exact
physical target, identity, old/new values and collision-query limitations. Confirm
the allocation, then apply. Read the result and readback; uncertain outcomes retain
receipts for recovery. Changing controllers or leaving the task discards an unused
review. This standard BACnet operation requires controller firmware that permits
writing its Device object identifier. It does not change a MAC or network number.

## Open and edit a CAF offline

Open the local CAF and use Program → CAF file for objects, parameters, logic,
hardware proposals and compatibility evidence. These task views retain drafts
while moving around the workspace. Local scalar changes appear under
**Changes → CAF changes**. **Save CAF copy** downloads a separate file without
writing to a controller. Logic and hardware proposals retain their own guarded
exports; they are not silently combined with a scalar export.

You can connect while the file remains open. Its match to the controller stays
explicitly unverified. A BACnet metadata connection does not provide native JCI
application upload or download. CAF simulation inputs describe the original opened
archive; export and reopen a copy to include application edits.

## Working modes and results

Edit is for local application work. Simulate groups graph and supported native
simulation tools. Commission groups addressed device operations. Temco application
transfer is under Changes and retains its adapter-specific inspection and review
requirements; it is not available as an action within the simulation view.

Field tools retain their own review, apply, verification, ownership and receipt
rules. Changes is a common place to find them, not a batch transaction. Recorded
history identifies its original source. A closed interface or an older identity
read is labelled separately from a freshly verified controller.
