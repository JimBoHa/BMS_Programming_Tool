# Native Boolean default archive copies

In **Program → Native backup defaults**, select and inspect a retained backup.
Browse captured native records and inspect an actual Input Boolean or Output
Boolean record. For a recognized Boolean Default Value (3113), open **Save a
Boolean default archive copy**, choose the proposed true/false value, review it,
then **Save Boolean archive copy**. The original property table remains unchanged.
The exact original review JSON can also be saved.

This profile handles existing class 530/531 properties whose actual encoding is
one canonical BACnet Boolean tag (`10` or `11`) followed by the native closing
tag. The class/attribute labels come from the existing repository dictionaries;
actual bytes, full native framing and unambiguous references determine eligibility.
Model names do not select data. Other classes/properties, numeric values, unusual
Boolean encodings and ambiguous/partial sources remain unsupported.

Only the selected application-tag byte changes. The compiler reparses the output
and checks every other expanded byte, Device instance and record count. Plain and
ordinary single-member gzip sources are supported; gzip headers are retained and
CRC/size are regenerated. No-op copies preserve the entire original file exactly.
This does not create blocks, links, terminals or a general native program.

These are **original archive values**, not saved-setting-merged values. The copy
does not change retained Files 3/11/12 or merge saved settings. A saved setting may
override the archive default on a controller. Unknown saved schemas and historical
acquisition identity errors do not prevent a structurally qualified local archive
copy; the original errors remain visible. Neither the Real effective-default
compiler nor its field-transfer operation accepts these Boolean fields.

The review binds capture ID, full snapshot manifest, original archive hash,
engineering reference, exact property encoding and proposed Boolean. Export
recomputes that review. All three retained file hashes must still match. The
browser checks the review's source/station/field/value/operation flags, then checks
export headers and the actual output SHA-256 before downloading. Altered, stale
or late results cannot save a different source or revive an old review.

Up to 256 Boolean proposals remain attached to their exact capture, manifest,
record and original encoding while the application is open. Switching records,
backups, targets or tasks does not move or discard those drafts. Reviews are
retired on navigation/source changes. **Discard Boolean copy draft** restores the
archive value. Reaching the bound refuses a new draft without evicting an existing
one. This memory cache does not promise recovery after closing/reloading the app.

Token-admitted local endpoints under
`/api/bacnet/controller/native-application/inspection/boolean-default` are
`POST /preview` and `POST /export`. They require strict JSON Booleans; strings and
numbers are rejected. The operation profile is
`native-backup-boolean-default-copy/1`. They perform no controller query, backup
command, native transfer, force or transfer-journal insertion. Saving a file does
not establish CCT reopening, firmware/release compatibility or physical acceptance.

Native-backup capability analysis advances to profile
`native-backup-operation-capabilities/2`, adding the thirteenth operation for this
separate archive-only copy. Its source qualification comes from actual eligible
fields, not the presence of a class label. General logic, package/release and
physical acceptance remain separate, and the broader JCI roadmap stays partial.

Local qualification uses literal Boolean tags in complete plain/gzip and short/
extended frames, independent other-byte comparison, saved-value separation,
wrong/opaque fields, source/property/review and HTTP admission, altered original
files and a disconnected authored native UDP peer. Browser checks cover actual
download/review bytes, draft ownership, navigation, malformed reviews and altered
or late exports. No site or Bluetooth acceptance is inferred.
