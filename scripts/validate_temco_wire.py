#!/usr/bin/env python3
"""Generate wire fixtures by compiling unchanged pinned manufacturer C encoders.

Only this small original harness and emitted data enter this repository. The
upstream C remains in Reference_Sources under its GPL/linking-exception license.
"""

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = "ae9b9d082de93b35ff2ca59eb1d0c06ae04cec9b"
HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "ptransfer.h"
#include "bacstr.h"
#include "bacdcode.h"
int main(void) {
 uint8_t body[407], params[430], out[480];
 BACNET_OCTET_STRING os;
 BACNET_PRIVATE_TRANSFER_DATA p;
 for(int n=0;n<3;n++) {
  int size=n==2?407:7;
  memset(body,0,sizeof(body));
  body[0]=size&255;body[1]=size>>8;
  body[2]=n==0?7:n==1?16:116;body[3]=3;body[4]=3;
  body[5]=n==0?37:144;body[6]=n==0?0:9;
  for(int j=7;j<size;j++)body[j]=(j-7)&255;
  octetstring_init(&os,body,size);
  p.vendorID=260;p.serviceNumber=1;
  p.serviceParameters=params;p.serviceParametersLen=encode_application_octet_string(params,&os);
  int len=ptransfer_encode_apdu(out,42,&p);
  printf("request%d ",n);for(int j=0;j<len;j++)printf("%02x",out[j]);printf("\n");
  if(n==1){
   body[0]=144;body[1]=1;
   for(int j=7;j<407;j++)body[j]=(j-7)&255;
   octetstring_init(&os,body,407);
   p.serviceParametersLen=encode_application_octet_string(params,&os);
   len=uptransfer_encode_apdu(out,&p);
   printf("unconfirmed_read ");for(int j=0;j<len;j++)printf("%02x",out[j]);printf("\n");
   len=ptransfer_ack_encode_apdu(out,42,&p);
   printf("ack_read ");for(int j=0;j<len;j++)printf("%02x",out[j]);printf("\n");
  }
 }
 params[0]=0;p.serviceParametersLen=1;
 int len=uptransfer_encode_apdu(out,&p);
 printf("unconfirmed_write_null ");for(int j=0;j<len;j++)printf("%02x",out[j]);printf("\n");
}
"""
HEADER_HARNESS = r"""
#include <cstdint>
#include <cstdio>
#include <cstddef>
typedef unsigned char byte;
typedef uint16_t WORD;
class CString {}; // Unused UI-only member type, outside either wire structure.
#include "ud_str.h"
int main() {
 Str_user_data_header h={7,READPROGRAMCODE_T3000,3,3,static_cast<uint16_t>(400|(4<<9))};
 printf("%zu %zu %zu %zu ",sizeof(h),sizeof(Str_program_point),
        offsetof(Str_program_point,bytes),offsetof(Str_program_point,on_off));
 for(size_t n=0;n<sizeof(h);n++)printf("%02x",reinterpret_cast<unsigned char*>(&h)[n]);
 puts("");
}
"""


def generate(sdk):
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=sdk, text=True).strip()
    if revision != PIN:
        raise ValueError("Manufacturer C checkout must be pinned to " + PIN)
    subtree = sdk / "BacNetDllforVc"
    sources = [
        subtree / "Src" / (name + ".c")
        for name in ("ptransfer", "bacdcode", "bacint", "bacstr", "bacreal")
    ]
    # Include all directly referenced public headers in provenance as well.
    header = sdk / "T3000/CM5/ud_str.h"
    paths = sources + sorted((subtree / "include").glob("*.h")) + [header]
    with tempfile.TemporaryDirectory(prefix="temco-wire-") as temporary:
        temporary = Path(temporary)
        harness, binary = temporary / "main.c", temporary / "wire"
        harness.write_text(HARNESS)
        command = [
            "clang",
            "-w",
            "-fdeclspec",
            "-include",
            str(subtree / "include/bacenum.h"),
            "-DBACDL_MSTP=1",
            "-I" + str(subtree / "include"),
            str(harness),
            *map(str, sources),
            "-o",
            str(binary),
        ]
        subprocess.run(command, check=True, capture_output=True)
        output = subprocess.check_output([str(binary)], text=True)
        cpp = temporary / "header.cpp"
        cpp.write_text(HEADER_HARNESS)
        subprocess.run(
            ["clang++", "-w", "-I" + str(header.parent), str(cpp), "-o", str(binary)],
            check=True,
            capture_output=True,
        )
        layout = subprocess.check_output([str(binary)], text=True).strip().split()
    return {
        "profile": "temco-private-transfer-c-fixtures/1",
        "source_url": "https://github.com/temcocontrols/T3000_Building_Automation_System",
        "source_commit": PIN,
        "license": "Upstream C GPL-2.0-or-later with linking exception; emitted protocol data only",
        "generator": "scripts/validate_temco_wire.py (unchanged manufacturer C sources)",
        "source_sha256": {
            str(path.relative_to(sdk)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths
        },
        "frames": dict(line.split(" ", 1) for line in output.splitlines()),
        "cpp_layout": {
            "header_bytes": int(layout[0]),
            "descriptor_bytes": int(layout[1]),
            "descriptor_code_length_offset": int(layout[2]),
            "descriptor_run_state_offset": int(layout[3]),
            "read_code_header_hex": layout[4],
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sdk", type=Path, default=ROOT.parent / "Reference_Sources/temcocontrols--T3000"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "tests/fixtures/temco_private_transfer.json"
    )
    args = parser.parse_args()
    result = generate(args.sdk.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("Generated six real manufacturer C APDU fixtures: " + str(args.output))


if __name__ == "__main__":
    main()
