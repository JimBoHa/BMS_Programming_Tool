# Local CAF Enumeration Constant creation

`FMT-CAF-ENUM-COPY-001` copies one recorded version 1.0 Enumeration Constant and
its required output into a separate local CAF. The parent uses class/type 568,
the four-property constant schema, exposed property 85 and recorded standard-name
code 12. Its class-529/type-19 output contains properties 75/32527/74/931/3365,
with optional 3113. The writer retains the recorded value, omitted default,
Number Of States, States Text and enum encoding attributes exactly.

The source schemas record property 74 as unsignedShort and property 931 as an
enum in set 802, with codes 351/886/405 in this profile. Recorded defaults use
enum encoding sets 647/351/886/405. These namespaces are distinct evidence: the
writer does not require their IDs to equal each other or treat Number Of States
as the default-code ceiling. It checks known framing and native unsigned bounds,
then copies the original representations. It assigns no undocumented state label,
allowed-code list or enum meaning; `enum_semantics_verified` remains false.

The existing identity-pair, membership, execution-order, position, XML/ZIP and
independent graph/readback writer is reused without changing either the Float
or Boolean engine. The new profile has its own output validator and source
metadata seal. Unknown types/versions/fields/sets, noncanonical unsigned values,
extra descendants or unsupported bookkeeping are refused. Two fresh local IDs
derive from actual object IDs and all typed references within the unchanged
ceiling. Original objects and unrelated parent bytes stay exact.

## Existing Program task

Open a CAF and use **Program → CAF file → Logic**. **Constant type** offers only
supported families present in the actual diagram. Choose **Enumeration Constant**,
inspect its prototype, enter a position, review and save a separate CAF copy.
**Recorded enumeration metadata** shows the original counts and encoding/code
identifiers separately. A missing default stays missing; the tool does not choose
a first state or silently replace it with zero. Existing compatible connection
creation is a separate guarded export after opening the copied CAF.

Float, Boolean and Enumeration unfinished position drafts share the existing
32-context cache without eviction. Passive inspection or type selection consumes
no slot. Only one creation task/primary action is visible; inactive reviews and
late downloads retire while raw text remains with its archive/diagram/prototype.
Source, controller, prototype, task, lifecycle and visibility ownership, exact
review JSON, artifact checking and the ordinary CAF Save contract remain intact.
Controller entry keeps its selected route and labels the local file/controller
application match unverified.

Separate strict token-protected endpoints use
`/api/caf/{id}/enum-constant-copy/source`, `/preview` and `/export`. Source binds
the original diagram/prototype/output bytes, execution/membership, derived
identities, enum metadata and position. Selection/creation/review seals and four
artifact/review/source/creation headers bind the clicked output. Requests cannot
supply guessed state metadata or semantic/field authority. There is no Apply
route, controller query/write, field plan or native File-3 compiler here.

## Qualification and remaining scope

All 151 actual Enumeration/output pairs across seven authorized private CAFs
were created/read back in memory. Six omitted defaults stay omitted; 79 recorded
default-encoding and States Text identifiers differ and are retained. The actual
Number Of States values are 7 or 11. All 125 prior Float/Boolean selections,
reports, seals and artifacts match the exact PR227 implementation. Original files
remain unchanged; no derived private CAF is saved or committed.

Authored independent expected XML tests cover the two schemas, recorded
namespace differences, unsigned bounds, omission, repeated creation, unknown
configuration, metadata/identity preservation and subsequent existing connection
export. Strict API, source/installed browser, mixed-kind unfinished drafts, stale
output, exact artifact/review, Unicode, compact controls and both entry paths
have separate checks. The local delivery report records exact case counts,
clean-wheel provenance, distribution and original-checkout preservation.

This is recorded local structural copying. Enum meanings/valid states, vendor
allocation/reserved IDs, scan/memory resources, arbitrary logic/hardware/ports,
native compilation, CCT reopening, firmware execution and physical/BTCVT transfer
remain unqualified. General new-object/compiler/download capability flags do not
grant these broader operations. JCI-02, JCI-03, JCI-06 and JCI-09 remain partial.

The manufacturer identifies Enumeration Constant 568 and Output Enumeration
Block 529 in its
[class-ID reference](https://docs.johnsoncontrols.com/bas/r/Facility-Explorer/en-US/Facility-Explorer-Site-Management-Portal-Help/Welcome/Site-Management-Portal-User-Interface/Site-Management-Portal-User-Interface-Concepts/User-Interface-Object-Icons-and-Class-IDs).
The observed CAF structures and writer qualification are separate from that
label reference and do not establish vendor compiler acceptance.
