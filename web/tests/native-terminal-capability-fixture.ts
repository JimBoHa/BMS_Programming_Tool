import { python } from "./native-connection-fixture";
import { enter, analyze } from "./native-connection-capability-fixture";
import { expect, type Page } from "@playwright/test";

export function seed(directory: string) {
  return JSON.parse(
    python(
      `
from pathlib import Path
import json,sys
from tests.test_native_terminal_capabilities import source,analysis
from tests.test_moi_terminal_copies import authored
from tests.test_moi_terminal_output_namespace import with_output
rows={}
for kind in ['analog','binary','unknown','unverified','output','serial']:
 files=authored(compressed=True,binary=kind=='binary');metadata={}
 if kind=='unknown':files[11],files[12]=b'Unknown saved directory',b'Opaque values'
 if kind=='unverified':metadata['source_identity_matches']=False
 if kind=='output':files=with_output(files)
 if kind=='serial':metadata['connector_config']={'transport':'mstp','serial_port':'owned-unopened'}
 storage,records,_,request=source(Path(sys.argv[1]),files=files,**metadata)
 report=analysis(records,request)
 rows[kind]={'id':request['capture_id'],'report':report,'archive':{k:report[k] for k in ['capture_id','snapshot_sha256','sha256','target','files']}}
print(json.dumps(rows))`,
      directory,
    ),
  );
}
export async function openTerminal(page: Page, id: string) {
  const { compiler, support } = await enter(page, id);
  await analyze(support);
  const terminal = support.getByLabel("Native terminal operation support", {
    exact: true,
  });
  await terminal.locator(":scope > summary").click();
  return { compiler, support, terminal };
}
export async function terminalTable(terminal: ReturnType<Page["getByLabel"]>) {
  const table = terminal.getByRole("table", {
    name: "Native terminal operations",
    exact: true,
  });
  await expect(table.getByRole("row")).toHaveCount(4);
  return table;
}
