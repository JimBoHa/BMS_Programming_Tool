import { test, expect } from "@playwright/test";
import { python } from "./caf-constant-fixture";
import { connectionSeal } from "../src/nativeConnectionContract";
import {
  creationCheckpoint,
  creationDraftStatus,
  creationDraftResult,
  creationDraftRemoved,
  creationDraftToken,
  selectionContext,
} from "../src/cafCreationDraftContract";

const fixtures = JSON.parse(
  python(`
import importlib,json,tempfile
from bms_tool.caf import CafArchive
from bms_tool.caf_creation_drafts import CafCreationDrafts,INSPECTORS,selection_context
from bms_tool.storage import Store
from tests.test_caf_creation_drafts import FAMILIES,selection,match,token
out=[]
for kind,name,changes in FAMILIES:
 module=importlib.import_module('tests.test_caf_'+(name if name.endswith('creation') else name+'_copy'))
 caf=CafArchive(module.example(zero=True,**changes))
 with tempfile.TemporaryDirectory() as tmp:
  service=CafCreationDrafts(Store(tmp)); row=selection(caf,kind,module.REF,module.PROTOTYPE,x='1e-',y='  α\\n')
  saved=service.save(caf,{'selection':row,'expected':None})
  out.append({'archive':caf.hash,'context':selection_context(row),'source':INSPECTORS[kind](caf).inspect(module.REF,module.PROTOTYPE),'saved':saved,'status':service.status(caf.hash,selection_context(row)),'restored':service.restore(caf,match(saved['checkpoint']))})
print(json.dumps(out))
`).toString(),
);

for (const [i, f] of fixtures.entries())
  test(`actual backend copy checkpoint ${i + 1} preserves its source profile and raw coordinates`, async () => {
    const saved = f.saved.checkpoint,
      expected = creationDraftToken(saved);
    expect(
      await creationCheckpoint(saved, f.archive, f.context, f.source),
    ).toBe(true);
    expect(await creationDraftStatus(f.status, f.archive, f.context)).toBe(
      true,
    );
    expect(
      await creationDraftResult(
        f.saved,
        "save",
        f.archive,
        f.context,
        f.source,
        null,
        saved.selection,
      ),
    ).toBe(true);
    expect(
      await creationDraftResult(
        f.restored,
        "restore",
        f.archive,
        f.context,
        f.source,
        expected,
        undefined,
        saved,
      ),
    ).toBe(true);
    expect(saved.selection.x).toBe("1e-");
    expect(saved.selection.y).toBe("  α\n");
  });

const first = fixtures[0];
for (const field of [
  "kind",
  "diagram_ref",
  "prototype_ref",
  "selection_sha256",
  "x",
  "y",
  "profile",
  "caf_sha256",
  "id",
  "revision",
  "created_at",
  "source_profile",
  "diagram_sha256",
  "prototype_sha256",
  "extra-authority",
])
  test(`resealed wrong ${field} cannot restore copy source authority`, async () => {
    const v = structuredClone(first.saved.checkpoint);
    if (
      ["kind", "diagram_ref", "prototype_ref", "selection_sha256"].includes(
        field,
      )
    )
      v.selection[field] = "other";
    else if (field === "x") v.selection.x = false;
    else if (field === "y") v.selection.y = "x".repeat(8193);
    else if (
      ["source_profile", "diagram_sha256", "prototype_sha256"].includes(field)
    )
      v.source_evidence[field] = "0".repeat(64);
    else if (field === "extra-authority") v.can_apply = true;
    else v[field] = field === "revision" ? true : "other";
    const { checkpoint_sha256, ...body } = v;
    v.checkpoint_sha256 = await connectionSeal(body);
    expect(
      await creationCheckpoint(v, first.archive, first.context, first.source),
    ).toBe(false);
  });

test("status metadata never supplies fresh source evidence and an unavailable generation cannot supply coordinates", async () => {
  const value = structuredClone(first.status);
  value.source_revalidated = true;
  expect(await creationDraftStatus(value, first.archive, first.context)).toBe(
    false,
  );
  value.source_revalidated = false;
  value.checkpoint = {
    state: "unavailable",
    id: "a".repeat(32),
    revision: 1,
    error: "Unavailable",
  };
  expect(await creationDraftStatus(value, first.archive, first.context)).toBe(
    true,
  );
  expect(creationDraftToken(value.checkpoint)).toEqual({
    id: "a".repeat(32),
    revision: 1,
  });
  expect(
    await creationCheckpoint(
      value.checkpoint,
      first.archive,
      first.context,
      first.source,
    ),
  ).toBe(false);
});

for (const field of [
  "controller_queries",
  "controller_writes",
  "can_apply",
  "coordinates_validated",
  "export_success_restored",
  "scope",
  "profile",
  "context",
])
  test(`wrong ${field} envelope cannot become a copy save receipt`, async () => {
    const value = structuredClone(first.saved);
    value[field] = true;
    expect(
      await creationDraftResult(
        value,
        "save",
        first.archive,
        first.context,
        first.source,
        null,
        first.saved.checkpoint.selection,
      ),
    ).toBe(false);
  });

test("restore binds its exact previously displayed record, while saved coordinates remain unparsed", async () => {
  const value = structuredClone(first.restored),
    old = first.saved.checkpoint;
  value.checkpoint.selection.x = "different";
  const { checkpoint_sha256, ...body } = value.checkpoint;
  value.checkpoint.checkpoint_sha256 = await connectionSeal(body);
  expect(
    await creationCheckpoint(
      value.checkpoint,
      first.archive,
      first.context,
      first.source,
    ),
  ).toBe(true);
  expect(
    await creationDraftResult(
      value,
      "restore",
      first.archive,
      first.context,
      first.source,
      creationDraftToken(old),
      undefined,
      old,
    ),
  ).toBe(false);
  expect(selectionContext(old.selection)).toEqual(first.context);
  expect(
    creationDraftRemoved(
      {
        ...first.saved,
        profile: "caf-creation-draft-remove/1",
        source_revalidated: false,
        checkpoint: undefined,
      },
      first.archive,
      first.context,
      creationDraftToken(old)!,
    ),
  ).toBe(false);
});
