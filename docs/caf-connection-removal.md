# Remove an existing CAF connection

In **Program → Logic**, select an actual connection and open its removal task.
Review the selected source, destination, ports and original occurrence before
saving a separate CAF copy. The original graph remains displayed until you
explicitly open the verified copy.

Removal deletes one recorded connection and its aligned continuation record.
Identical connection tuples remain separate occurrences. The review reports how
many other recorded connections still address that destination port; zero means
no recorded writer remains. It does not establish the controller's fallback,
retained-value or runtime behavior after the change.

All blocks, object identities, execution order, layout and destination
configuration remain intact. The operation preserves every other XML byte and
the original archive metadata. Removing the final connection leaves empty
connection and continuation collections. An empty diagram has nothing to remove.

Only the observed CAF diagram schema is supported: class 536 or 575, version 1.0,
with coherent connection and continuation collections in patchable original XML.
Unknown selected-record metadata, inconsistent collections, stale selections or
changed source evidence are refused. A diagram that can be displayed is not
automatically eligible for this edit.

Removal copies start from the original opened CAF. Other scalar, hardware,
instance, block-creation and wiring proposals are separate; they are not silently
combined into the copy. Retained removal proposals survive task navigation, but
reviewed results and openable-copy evidence retire when their source or context
changes. Export a supported change and reopen its copy before building on it.

Saving a copy does not open it automatically or send it to a controller. Explicit
opening rechecks the received bytes and the server's opened-file identity. A
canceled replacement or failed upload leaves the current file and its drafts
available. Constant-creation copy checks retain their separate contract.

The source, preview and export APIs are under
`/api/caf/{source_sha256}/connection-removal`. They bind the original diagram,
wire occurrence, tuple, count, continuation and exact encoded row/property hashes.
Preview recomputes the removal; export recomputes it again and requires the same
review hash. The browser checks report bindings and received artifact bytes before
presenting a successful save or copy-opening action.

This is a local source-copy operation. It provides no vendor compilation result,
package compatibility, native execution proof, physical acceptance or controller
transfer authority. General JCI authoring and deployment remain separate work.
