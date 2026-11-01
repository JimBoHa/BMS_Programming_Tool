# CAF workspace race and draft validation

The CAF workflow regression suite now uses the current **Open a CAF file** entry,
**Program → Objects & parameters / Logic**, **Changes → Compare applications**
and **Save CAF copy**. It does not restore retired global CAF feature buttons.
All Python fixture/readback children explicitly import the feature checkout's
backend. Paths resolve from the test file rather than the caller's directory.

Eight existing scenarios remain intact:

1. A delayed property response cannot overwrite another selected object's values
   or redirect its scalar edit.
2. A later selected archive wins over an earlier upload delivered late.
3. Unexported scalar drafts survive refused replacement and task navigation;
   exported drafts no longer require discard confirmation.
4. An export preserves its submitted scalar snapshot while a newer local draft
   remains unsaved and protected.
5. Explicitly reopening the same archive resets discarded native proposals and
   scalar drafts.
6. Native connection proposals require discard until exported; the outcome keeps
   the original connection tuple after selecting another connection.
7. A scalar export delivered after another archive opens cannot download or show
   stale success.
8. The same rule holds for native rewiring exports.

The suite uses actual production HTTP responses. Delays hold original responses
without changing their semantics or retrying requests. Downloaded CAFs are parsed
independently to check scalar values and native wire tuples. Every scenario also
requires no browser field-operation POST and a closed field interface.

The first updated run exposed two assumptions from the older layout. Saving now
enters Changes, so the concurrent-draft test explicitly returns to Objects while
the actual export reply remains held. The deliberately minimal graph fixture has
no root Device BACoid; the independent instance editor reports that limitation.
Late-export assertions require exactly that known error, with no additional or
changed alert, instead of misclassifying it as an export error.

All eight scenarios pass in both Chromium and WebKit. Existing workspace entry
and offline CAF-preservation checks remain separate regressions. Original failed
logs, page snapshots and traces were retained privately; no product guard,
timeout or retry count changed. These are local authored-CAF checks, not native
controller compilation, deployment, code-compliance or Bluetooth acceptance.
