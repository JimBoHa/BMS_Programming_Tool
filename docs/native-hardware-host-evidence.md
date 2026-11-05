# Captured hardware host evidence

`IO-NATIVE-HOST-EVIDENCE-001` corrects host resolution in new native/CAF hardware
analyses. A controller-root input reference can coexist with SA modules and does
not establish that the input is on the base controller. Such inputs retain their
original identity, terminal and raw record evidence, with an unknown host and a
specific explanation. Ambiguity makes inventory incomplete and spare candidates
unverified; it cannot free a terminal or enable a relocation review.

A valid explicit positive SA address now resolves only when it identifies one
configured module. It can identify a root-scoped input without conflicting with
an invented local assignment. Conflicting parent/address bindings, duplicate
module references/addresses, orphan addresses, unsupported address encodings and
unqualified Device Reference properties remain unresolved. A unique module-parent
reference remains usable. Controller-only archives retain their existing local
root interpretation when no SA module record or unresolved host property exists.

The existing Points & I/O hardware task now also opens without a connected controller,
so local archive/report inspection does not require field access. The disconnected
state keeps field actions unavailable and preserves the current CAF or graph.

The same resolver serves native MOI and scalar CAF analysis. It consumes the actual
captured property references and configured modules, without model-selected point
inventories. Neither configured models nor host evidence verify installed labels,
physical wiring or current controller state. Field survey reads, all native
compilers/writers, transfer profiles, recovery, historical journals remain separate. Compact input tables use a bounded horizontal
scroller with readable columns; the existing teal/neutral workspace remains. Original source bytes stay intact and downloadable after restart.

Tests exercise actual native/CAF parsing, explicit and conflicting addresses,
ambiguous/duplicate host evidence, conservative occupancy and relocation, API
persistence and exact downloads. The older positive survey fixture now records its
input beneath an explicit configured module; its original root-scoped variant is
retained as the regression fixture. Existing loopback survey, serial, workbench,
capacity and sensor-plan tests exercise the supported paths. Browser checks use
current Points & I/O entry with graph/CAF continuity at desktop and compact widths.

This delivery corrects new analyses and reimports. Previously persisted archive
metadata and historical reports retain their original evidence; they are not
silently rewritten. Next, add explicit reanalysis of saved archive source bytes,
then qualify additional typed Device Reference and hardware reassignment semantics.
SA/cross-host writes, general allocation/electrical edits, resources/packages and
CCT/physical/BTCVT acceptance remain separate work. IO-02/JCI-09 remain partial.
