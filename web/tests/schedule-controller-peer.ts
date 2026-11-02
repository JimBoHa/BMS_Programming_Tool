import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import path from "node:path";

/** Actual authored UDP identity, Schedule reads and one-day writes. No site data. */
export async function scheduleControllerPeer(routed = false, string = false) {
  const root = path.resolve("..");
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,json,sys
from tests.test_native_schedule_write import WeeklyPeer
from tests.test_schedule_inventory import options,text,unsigned
from tests.test_connections import free_udp
class Peer(WeeklyPeer):
 def value(self,obj,prop,index):
  if prop in ('model-name','firmware-revision','application-software-version','vendor-name','location'):return text('Authored')
  if prop=='protocol-revision':return unsigned(22)
  if prop=='segmentation-supported':return b'\\x91\\x03'
  if prop=='vendor-identifier':return unsigned(5)
  if prop=='system-status':return b'\\x91\\x00'
  return super().value(obj,prop,index)
async def main():
 p=Peer(routed=sys.argv[1]=='routed')
 if sys.argv[2]=='string':
  atom=bytes.fromhex('74006f6c64');p.exception_count=0
  p.days=[bytes.fromhex('0eb408000000')+atom+bytes.fromhex('0f')]*7
  p.overrides['schedule,1','present-value',None]=atom
  p.overrides['schedule,1','schedule-default',None]=atom
 await asyncio.get_running_loop().create_datagram_endpoint(lambda:p,local_addr=('127.0.0.1',0))
 print(json.dumps({'target':{k:v for k,v in options(p).items() if k in ('address','device','router','dnet')},'local':f'127.0.0.1:{free_udp()}'}),flush=True)
 try:
  while True:
   line=await asyncio.to_thread(sys.stdin.readline)
   if not line:break
   command=json.loads(line)
   print(json.dumps({'reads':len(p.requests),'writes':len(p.writes),'errors':[str(e) for e in p.errors]}),flush=True)
   if command=='stop':break
 finally:
  tasks=list(p.tasks);p.close();await asyncio.gather(*tasks,return_exceptions=True)
asyncio.run(main())
`,
      routed ? "routed" : "direct",
      string ? "string" : "real",
    ],
    {
      cwd: root,
      env: {
        ...process.env,
        PYTHONPATH: [path.join(root, "backend"), root].join(path.delimiter),
      },
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  let errors = "";
  const queue: any[] = [],
    waiters: ((value: any) => void)[] = [];
  child.stderr.on("data", (data) => {
    errors = (errors + String(data)).slice(-8192);
  });
  createInterface({ input: child.stdout }).on("line", (line) => {
    const value = JSON.parse(line),
      resolve = waiters.shift();
    if (resolve) resolve(value);
    else queue.push(value);
  });
  const next = () =>
    queue.length
      ? Promise.resolve(queue.shift())
      : new Promise<any>((resolve, reject) => {
          const timer = setTimeout(
            () =>
              reject(
                new Error("Authored Schedule peer did not reply: " + errors),
              ),
            10000,
          );
          waiters.push((value) => {
            clearTimeout(timer);
            resolve(value);
          });
        });
  const ready = await next();
  let closed = false;
  async function command(value: string) {
    child.stdin.write(JSON.stringify(value) + "\n");
    return next();
  }
  return {
    ...ready,
    stats: () => command("stats"),
    async close() {
      if (closed) return;
      closed = true;
      const exited = new Promise<number | null>((resolve) =>
        child.once("exit", resolve),
      );
      try {
        await command("stop");
        child.stdin.end();
        const timer = setTimeout(() => child.kill("SIGKILL"), 3000);
        const code = await exited;
        clearTimeout(timer);
        if (code !== 0)
          throw new Error("Authored Schedule peer exited: " + errors);
      } finally {
        if (child.exitCode === null) child.kill("SIGKILL");
      }
    },
  };
}
