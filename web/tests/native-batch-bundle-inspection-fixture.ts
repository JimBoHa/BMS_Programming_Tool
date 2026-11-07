import { python } from "./caf-native-fixture";
import { seedBatchEvidence } from "./native-default-batch-evidence-fixture";

export function seedBundleInspection(directory: string, kind = "valid") {
  const source = seedBatchEvidence(directory, kind);
  const inspection = JSON.parse(
    python(
      `
import base64,json,sys
from bms_tool.native_batch_bundle_inspection import inspect_bundle
print(json.dumps(inspect_bundle(base64.b64decode(sys.argv[1]))))
`,
      source.bundle,
    ),
  );
  return { ...source, inspection };
}
