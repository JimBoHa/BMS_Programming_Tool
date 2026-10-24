import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  executionNumber,
  executionScalarMap,
  executionSourceValue,
  parseExecutionJSON,
  parseExecutionSourceJSON,
  parseExecutionHistoryTail,
  parseSourceJSON,
  sourceStringify,
  decodeSourceResponse,
  numericToken,
  projectSourceDocument,
} from "../src/programSource";
import { projectGroupExecutionDocument } from "../src/executionValues";

const python = "../.venv/bin/python";
function assertPython(raw: string) {
  execFileSync(
    python,
    [
      "-c",
      `import json,math,sys
v=json.load(sys.stdin)
assert type(v['exponent']) is float and v['exponent']==1e30
assert type(v['decimal']) is float and v['decimal']==1.0
assert type(v['negative_zero']) is float and math.copysign(1,v['negative_zero'])<0
assert type(v['integer_zero']) is int and v['integer_zero']==0
assert type(v['power']) is int and v['power']==2**60
assert type(v['flag']) is bool and v['flag'] is True
`,
    ],
    { input: raw },
  );
}
const values =
  '{"exponent":1e30,"decimal":1.0,"negative_zero":-0.0,"integer_zero":-0,"power":1152921504606846976,"flag":true}';
test("validated live atoms preserve original Python numeric type, integer and signed zero", () => {
  const parsed = parseExecutionSourceJSON(values);
  expect(sourceStringify(parsed)).toBe(values);
  assertPython(sourceStringify(parsed));
  expect(executionNumber("1e30")).toBe(1e30);
  expect(typeof parseExecutionJSON("1.0")).toBe("number");
  expect(numericToken(executionSourceValue(" -0.0 "))).toBe("-0.0");
});
test("live validation still refuses unsafe integer tokens and nonfinite/malformed forms", () => {
  for (const token of [
    "9007199254740993",
    "-9007199254740993",
    "1e400",
    "NaN",
    "+1",
    "01",
    "",
    "1.2.3",
  ])
    expect(() => executionSourceValue(token), token).toThrow();
  expect(() => parseExecutionSourceJSON('{"x":9007199254740993}')).toThrow();
  expect(() => parseExecutionSourceJSON('{"x":1,"x":2}')).toThrow();
  expect(
    sourceStringify(
      parseExecutionSourceJSON(
        '[1.0,{"value":1e30,"quality":"good"},false,null]',
      ),
    ),
  ).toBe('[1.0,{"value":1e30,"quality":"good"},false,null]');
});
function rawGroup(extra = "") {
  return parseSourceJSON(
    '{"session":"owned-session","time":1.0,"link_delay_cycles":1,"definition":{"name":"group","links":[{"initial":1.0}],"programs":[]},"external_inputs":{"a":{"x":{"value":1152921504606846976,"quality":"good"},"f":1e30}},"programs":{"a":{"time":1.0,"values":{"x":1152921504606846976},"outputs":{"out":1152921504606846976},"forces":{},"state":{}}},"history":[{"time":1.0,"inputs":{"a":{"x":1152921504606846976}},"programs":{"a":{"outputs":{"out":1152921504606846976}}}}],"failures":[]' +
      extra +
      "}",
  );
}
test("group only reuses exact known signal paths while structural unknown integers remain guarded", () => {
  const raw = rawGroup(),
    projected = projectGroupExecutionDocument(raw);
  expect(sourceStringify(projected.external_inputs)).toBe(
    '{"a":{"x":{"value":1152921504606846976,"quality":"good"},"f":1e30}}',
  );
  expect(sourceStringify(projected.definition.links[0].initial)).toBe("1.0");
  expect(projected.time).toBe(1);
  expect(projected.programs.a.outputs.out).toBe(2 ** 60);
  expect(() => projectSourceDocument(raw)).toThrow();
  expect(() =>
    projectGroupExecutionDocument(
      rawGroup(',"unexpected_count":9007199254740993'),
    ),
  ).toThrow(/Unsupported browser numeric projection/);
  for (const key of ["time", "link_delay_cycles"])
    expect(() =>
      projectGroupExecutionDocument({
        ...raw,
        [key]: parseSourceJSON("9007199254740993"),
      }),
    ).toThrow();
});
test("group Program hydration keeps revision/id and source parameter safeguards", () => {
  const program = parseSourceJSON(
    '{"schema_version":1,"id":"source","name":"Source","description":"","revision":0,"scan_seconds":1.0,"target":{"family":"universal-runtime","model":"","firmware":"","release_mode":"","max_nodes":2000,"physical_inputs":null,"physical_outputs":null},"nodes":[{"id":"x","kind":"Input","label":"","x":0,"y":0,"params":{"default":1e30,"archived":9007199254740993},"unit":"","value_type":"number"}],"edges":[],"metadata":{}}',
  );
  const raw = rawGroup();
  raw.definition.programs = [{ alias: "a", program }];
  const projected = projectGroupExecutionDocument(raw);
  expect(projected.definition.programs[0].program.id).toBe("source");
  expect(projected.definition.programs[0].program.revision).toBe(0);
  expect(
    numericToken(
      projected.definition.programs[0].program.nodes[0].params.archived,
    ),
  ).toBe("9007199254740993");
  program.revision = parseSourceJSON("9007199254740993");
  expect(() => projectGroupExecutionDocument(raw)).toThrow();
});
test("custom live projection runs only after exact response hash and descriptor validation", async () => {
  const source_json = sourceStringify(rawGroup());
  const envelope = {
    format: "bms.program-source-response/1",
    kind: "programs",
    source_json,
    source_sha256: createHash("sha256").update(source_json).digest("hex"),
    programs: [],
  };
  const value = await decodeSourceResponse(
    envelope,
    projectGroupExecutionDocument,
  );
  expect(numericToken(value.external_inputs.a.f)).toBe("1e30");
  await expect(
    decodeSourceResponse(
      { ...envelope, source_sha256: "0".repeat(64) },
      projectGroupExecutionDocument,
    ),
  ).rejects.toThrow(/hash/);
  await expect(
    decodeSourceResponse(
      { ...envelope, programs: [{ path: [], program_id: "wrong" }] },
      projectGroupExecutionDocument,
    ),
  ).rejects.toThrow();
});

test("receipt-only tail reader exceeds archival size/count safely and discards earlier rows", () => {
  const earlier =
    '{"time":0,"values":{},"outputs":{},"padding":' +
    JSON.stringify("x".repeat(9 * 1024 * 1024)) +
    ',"unneeded":[' +
    "0,".repeat(210_000) +
    "0]}";
  const receipt =
    '{"history":[' +
    earlier +
    ',{"time":1,"values":{"a":1e30,"b":1.0,"z":-0.0},"forces":{"a":1152921504606846976}}]}';
  expect(() => parseSourceJSON(receipt)).toThrow(/8 MiB/);
  const tail = parseExecutionHistoryTail(receipt);
  expect(Object.keys(tail).sort()).toEqual(["forces", "values"]);
  expect(sourceStringify(tail)).toBe(
    '{"values":{"a":1e30,"b":1.0,"z":-0.0},"forces":{"a":1152921504606846976}}',
  );
  const countBound =
    '{"history":[{"ignored":[' + "0,".repeat(210_000) + "0]}]}";
  expect(() => parseSourceJSON(countBound)).toThrow(/value bound/);
  expect(parseExecutionHistoryTail(countBound)).toEqual({});
});
test("receipt tail remains strict for deep earlier data, duplicate keys and malformed syntax", () => {
  expect(() =>
    parseExecutionHistoryTail(
      '{"history":[{"ignored":' + "[".repeat(70) + "0" + "]".repeat(70) + "}]}",
    ),
  ).toThrow(/depth/);
  expect(() =>
    parseExecutionHistoryTail('{"history":[],"history":[]}'),
  ).toThrow(/Duplicate/);
  expect(() =>
    parseExecutionHistoryTail('{"history":[{"values":{"a":1.0}}]} trailing'),
  ).toThrow(/trailing/);
});

test("accepted execution maps reject wrappers, strings, null and unsupported integer atoms", () => {
  for (const raw of [
    null,
    [],
    parseSourceJSON('{"x":"1.0"}'),
    parseSourceJSON('{"x":{"value":1.0}}'),
    parseSourceJSON('{"x":9007199254740993}'),
  ])
    expect(() => executionScalarMap(raw)).toThrow();
  expect(
    sourceStringify(
      executionScalarMap(parseSourceJSON('{"x":1.0,"z":-0.0,"b":false}')),
    ),
  ).toBe('{"x":1.0,"z":-0.0,"b":false}');
});

test("real bounded Engine API receipt beyond archival item budget retains exact final maps", () => {
  const raw = execFileSync(
    python,
    [
      "-c",
      `from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
from bms_tool.app import create_app
from bms_tool.models import Program,Node,Edge
p=Program(id='actual-wide-receipt',nodes=[Node(id=f'i{i}',kind='Input',params={'default':1.0}) for i in range(1000)]+[Node(id=f'o{i}',kind='Output') for i in range(1000)],edges=[Edge(id=f'e{i}',source=f'i{i}',target=f'o{i}') for i in range(1000)])
with TemporaryDirectory() as d,TestClient(create_app(Path(d))) as c:
 h={'X-Studio-Token':c.get('/api/session').json()['token']}
 r=c.post('/api/simulation/step',headers=h,json={'program':p.model_dump(),'forces':{n.id:1.0 for n in p.nodes},'steps':50,'operation_id':'e'*32})
 assert r.status_code==200,r.text
 v=r.json(); assert v['completed_steps']==50 and len(v['history'])==50
 owned={'session':v['session'],'retirement_token':v['retirement_token'],'creation_operation_id':v['session_creation_operation_id']}
 assert c.post('/api/simulation/retire',headers=h,json=owned).json()['retired'] is True
 print(r.text)
`,
    ],
    { maxBuffer: 16 * 1024 * 1024, encoding: "utf8" },
  );
  expect(raw.length).toBeGreaterThan(3_000_000);
  expect(() => parseSourceJSON(raw)).toThrow(/value bound/);
  const tail = parseExecutionHistoryTail(raw);
  expect(Object.keys(tail.values)).toHaveLength(2000);
  expect(Object.keys(tail.forces)).toHaveLength(2000);
  expect(numericToken(tail.values.i0)).toBe("1.0");
  expect(numericToken(tail.forces.o999)).toBe("1.0");
});
