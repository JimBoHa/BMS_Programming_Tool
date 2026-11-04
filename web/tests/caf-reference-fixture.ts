import { python } from "./caf-constant-fixture";
export { python };
export function contract() {
  return JSON.parse(
    python(
      "import json;from tests.test_caf_math_copy import example,REF;from bms_tool.caf import CafArchive;from bms_tool.caf_graph import CafGraph;from bms_tool.caf_reference_labels import CafReferenceLabels;a=CafArchive(example());print(json.dumps({'archive':a.hash,'diagram':CafGraph(a).diagram(REF),'labels':CafReferenceLabels(a).diagram(REF)}))",
    ).toString(),
  );
}
