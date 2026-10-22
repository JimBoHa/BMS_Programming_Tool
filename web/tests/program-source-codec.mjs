import { test } from "node:test";
import assert from "node:assert/strict";
import {
  SourceNumber,
  parseSourceJSON,
  sourceStringify,
  parseSourceDocument,
  cloneSource,
  prepareSourceRequest,
  decodeSourceResponse,
  isExactProgram,
  executionNumber,
} from "../src/programSource.ts";
const raw =
  '{"schema_version":1,"id":"source","name":"Source","description":"","revision":0,"scan_seconds":1.0,"target":{"family":"universal-runtime","model":"","firmware":"","release_mode":"","max_nodes":2000,"physical_inputs":null,"physical_outputs":null},"nodes":[{"id":"a","kind":"Constant","label":"","x":0.0,"y":-0.0,"params":{"value":1.0,"values":[-0.0,9007199254740993,1e-7]},"unit":"","value_type":"number"}],"edges":[],"metadata":{"x":[9007199254740993,-0.0,1.0],"quoted":"9007199254740993"}}';
function atoms(p) {
  return sourceStringify({ params: p.nodes[0].params, metadata: p.metadata });
}
test("exact numeric atoms reject accidental serialization, clone and coercion", () => {
  const p = parseSourceDocument(raw);
  assert(isExactProgram(p));
  assert.equal(p.nodes[0].params.value.token, "1.0");
  assert.throws(() => JSON.stringify(p), /source serializer/);
  assert.throws(() => Number(p.nodes[0].params.value), /implicitly converted/);
  assert.throws(() => structuredClone(p), /clone|cloned/i);
  assert.equal(atoms(cloneSource(p)), atoms(p));
  assert(isExactProgram({ ...p, name: "Changed" }));
});
test("node reorder, copy, array reorder and explicit equal-Number edits retain source intent", () => {
  const p = parseSourceDocument(raw),
    copy = cloneSource(p.nodes[0]);
  copy.id = "b";
  copy.params.values.reverse();
  p.nodes.unshift(copy);
  assert.equal(
    sourceStringify(p.nodes[0].params.values),
    "[1e-7,9007199254740993,-0.0]",
  );
  p.nodes[1].params.value = new SourceNumber("1");
  p.nodes[1].params.values[0] = new SourceNumber("0");
  assert.equal(
    sourceStringify(p.nodes[1].params),
    ' {"value":1,"values":[0,9007199254740993,1e-7]}'.trim(),
  );
  assert.equal(p.nodes[0].params.value.token, "1.0");
});
test("envelope source hashes bind exact Program identity and revision", async () => {
  const p = parseSourceDocument(raw),
    envelope = await prepareSourceRequest({ program: p });
  assert.equal(envelope.program.program_id, "source");
  assert.match(envelope.program.source_json, /9007199254740993/);
  const response = {
    format: "bms.program-source-response/1",
    kind: "programs",
    source_json: envelope.program.source_json,
    source_sha256: envelope.program.source_sha256,
    programs: [
      {
        path: [],
        program_id: "source",
        revision_text: "0",
        canonical_sha256: "a".repeat(64),
        canonical_format: "canonical-json/1",
      },
    ],
  };
  assert.equal(atoms(await decodeSourceResponse(response)), atoms(p));
  await assert.rejects(
    () => decodeSourceResponse({ ...response, programs: [] }),
    /coverage/,
  );
  await assert.rejects(
    () =>
      decodeSourceResponse({
        ...response,
        programs: [...response.programs, ...response.programs],
      }),
    /identity\/path/,
  );
  const cyclic = {};
  cyclic.self = cyclic;
  await assert.rejects(() => prepareSourceRequest(cyclic), /Cyclic/);
  await assert.rejects(
    () => decodeSourceResponse({ ...response, source_sha256: "0".repeat(64) }),
    /Invalid exact/,
  );
  await assert.rejects(
    () =>
      prepareSourceRequest({
        ...p,
        [Object.getOwnPropertySymbols(p)[0]]: false,
      }),
    /Unmarked/,
  );
});
test("opaque metadata graph lookalikes retain raw nested atoms", () => {
  const p = parseSourceDocument(raw);
  p.metadata.program = parseSourceJSON(raw);
  const restored = parseSourceDocument(sourceStringify(p));
  assert.equal(restored.metadata.program.scan_seconds.token, "1.0");
  assert.equal(restored.metadata.program.nodes[0].x.token, "0.0");
});
test("strict parser refuses duplicate, nonfinite, malformed, oversize and deep values", () => {
  for (const text of [
    '{"x":1,"x":2}',
    "1e999",
    "[01]",
    "[1,]",
    '"unterminated',
    "[".repeat(66) + "0" + "]".repeat(66),
    '"' + "a".repeat(8 * 1024 * 1024) + '"',
  ])
    assert.throws(() => parseSourceJSON(text));
  assert.equal(
    sourceStringify(parseSourceJSON('{"__proto__":1.0,"x":"not a token 1.0"}')),
    '{"__proto__":1.0,"x":"not a token 1.0"}',
  );
});
test("execution projection refuses nonrepresentable integer literals without archival refusal", () => {
  assert.equal(executionNumber("9007199254740992"), 9007199254740992);
  assert.equal(executionNumber("1152921504606846976"), 2 ** 60);
  assert.throws(() => executionNumber("9007199254740993"), /not exactly/);
  assert.equal(
    sourceStringify(parseSourceJSON("9007199254740993")),
    "9007199254740993",
  );
  assert(Object.is(executionNumber("-0.0"), -0));
});
test("very large bounded archival integers remain exact without execution projection", () => {
  const token = "1" + "0".repeat(500);
  assert.equal(sourceStringify(parseSourceJSON(token)), token);
  assert.throws(() => executionNumber(token), /finite/);
});
test("unicode scalar values and numeric token bounds are explicit", () => {
  for (const text of [
    '"\\ud800"',
    '{"\\udfff":0}',
    "1".repeat(4097),
    "1." + "0".repeat(4096),
  ])
    assert.throws(() => parseSourceJSON(text));
  assert.equal(sourceStringify(parseSourceJSON('"\\ud83d\\ude00"')), '"😀"');
});

test("ordinary projected integral Numbers serialize their exact represented integer", () => {
  const value=executionNumber("1152921504606846976");
  assert.equal(sourceStringify({value}),'{"value":1152921504606846976}');
  assert.equal(sourceStringify(2**53),"9007199254740992");
  assert.equal(sourceStringify(2**100),"1267650600228229401496703205376");
  assert.equal(sourceStringify(-0),"-0.0");
});
