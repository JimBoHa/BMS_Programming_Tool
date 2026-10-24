import { spawn } from "node:child_process";
import { createSocket } from "node:dgram";
import path from "node:path";

const root = path.resolve("..");
export async function freePort(): Promise<number> {
  const socket = createSocket("udp4");
  return new Promise((resolve, reject) => {
    socket.once("error", reject);
    socket.bind(0, "127.0.0.1", () => {
      const port = (socket.address() as { port: number }).port;
      socket.close(() => resolve(port));
    });
  });
}
export async function peer(
  network = 3001,
  cached = false,
  stations = 2,
  named = false,
) {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,sys
from tests.guided_router_peer import GuidedRouter
from tests.test_routed_discovery import RawRouter
async def main():
 if sys.argv[2]=='cached':
  peer=RawRouter()
  peer.advertise_networks=False
  peer.devices=[(132007,b'\\x07',2105)]
 else:
  network=int(sys.argv[1])
  names={(network,7):'TB-3-201',(network,8):'HP-3A'} if sys.argv[4]=='named' else {}
  peer=GuidedRouter(network,stations=tuple(range(7,7+int(sys.argv[3]))),names=names)
 transport,_=await asyncio.get_running_loop().create_datagram_endpoint(lambda:peer,local_addr=('127.0.0.1',0))
 print(peer.endpoint,flush=True)
 try:await asyncio.Event().wait()
 finally:transport.close()
asyncio.run(main())
`,
      String(network),
      cached ? "cached" : "advertised",
      String(stations),
      named ? "named" : "default",
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  const writes: string[] = [],
    errors: string[] = [];
  const endpoint = await new Promise<string>((resolve, reject) => {
    let buffer = "",
      ready = false,
      stderr = "";
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Router startup: " + stderr));
    }, 10000);
    child.stderr!.on("data", (value) => (stderr += value.toString()));
    child.stdout!.on("data", (value) => {
      buffer += value.toString();
      while (buffer.includes("\n")) {
        const end = buffer.indexOf("\n"),
          line = buffer.slice(0, end).trim();
        buffer = buffer.slice(end + 1);
        if (!ready) {
          ready = true;
          clearTimeout(timer);
          resolve(line);
        } else if (line.startsWith("WRITE ")) writes.push(line.slice(6));
        else if (line.startsWith("PEER ERROR ")) errors.push(line);
      }
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      clearTimeout(timer);
      if (!ready) reject(new Error(`Router ${code}: ${stderr}`));
    });
  });
  return {
    endpoint,
    network,
    writes,
    errors,
    close: () => child.kill("SIGTERM"),
  };
}
