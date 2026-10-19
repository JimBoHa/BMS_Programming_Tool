#!/usr/bin/env python3
"""Build a bounded macOS/Linux host of Temco's MIT Control Basic compiler/VM.

The upstream checkout remains unchanged. Only build copies are adapted: Windows
string helpers, 32-bit Windows long ABI, and a restricted IN/OUT/VAR resolver.
Network, serial, alarm delivery and unsupported remote-point hooks abort. The
host is a local numeric reference, not controller firmware or a device loader.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import re
import subprocess
from pathlib import Path

PIN = "ae9b9d082de93b35ff2ca59eb1d0c06ae04cec9b"
URL = "https://github.com/temcocontrols/T3000_Building_Automation_System.git"
ROOT = Path(__file__).resolve().parents[1]

PORTABLE = r"""
#include <cstring>
#include <strings.h>
#include <vector>
#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <cctype>
using namespace std;
typedef uint32_t DWORD;
#define BAC_INPUT_ITEM_COUNT 64
#define BAC_OUTPUT_ITEM_COUNT 64
#define BAC_VARIABLE_ITEM_COUNT 256
#define BAC_PROGRAM_ITEM_COUNT 32
#define MAX_FUNCTION_COUNT 40
#define PROGRAM_SIZE 2000
#define strcpy_s(a,b,c) strcpy(a,c)
#define strcat_s(a,b,c) strcat(a,c)
#define Sleep(x) ((void)0)
#define _stricmp strcasecmp
inline char* itoa(int n,char*p,int b){if(b!=10)abort();sprintf(p,"%d",n);return p;}
inline char* ltoa(long n,char*p,int b){if(b!=10)abort();sprintf(p,"%ld",n);return p;}
inline char* strupr(char*p){for(char*q=p;*q;q++)*q=toupper((unsigned char)*q);return p;}
"""

POINT_RESOLVER = r"""
// Host accepts only bare local IN1..64, OUT1..64 and VAR1..256 references.
// Numeric tags/types and indexing match T3000's original local point encoder.
char *isbacnet_point(char *, Point_Bacnet *) { return 0; }
char *ispoint_ex(char *text,int *number,byte *var_type,byte *point_type,
                int *panel,int *network,int,unsigned char &sub,byte,int *present)
{
  const char *digits=nullptr; int kind=-1,limit=0;
  if(!strncmp(text,"IN",2)){kind=BAC_IN;digits=text+2;limit=64;}
  else if(!strncmp(text,"OUT",3)){kind=BAC_OUT;digits=text+3;limit=64;}
  else if(!strncmp(text,"VAR",3)){kind=BAC_VAR;digits=text+3;limit=256;}
  if(!digits || !*digits)return nullptr;
  for(const char*p=digits;*p;p++)if(!isdigit((unsigned char)*p))return nullptr;
  int n=atoi(digits); if(n<1 || n>limit)return nullptr;
  *number=n;*var_type=POINT_VAR;*point_type=kind;*panel=1;*network=0;sub=0;
  *present=0;static char label[1]={0};return label;
}
char *ispoint(char *text,int*n,byte*v,byte*t,int*p,int*net,int nw,byte pn,int*pr)
{unsigned char sub=0;return ispoint_ex(text,n,v,t,p,net,nw,sub,pn,pr);}
"""

COMPILER_MAIN = r"""
#include "compiler.cpp"
char editbuf[25000];
int main(){
  size_t count=fread(editbuf,1,sizeof(editbuf)-1,stdin);
  if(count>=sizeof(editbuf)-1){fputs("Source exceeds host limit",stderr);return 2;}
  editbuf[count]=0;Station_NUM=1;
  int result=Encode_Program();
  if(result || error!=-1){fprintf(stderr,"%s",mesbuf);return 1;}
  if(my_lengthcode<9 || my_lengthcode>=2000)return 3;
  fwrite(mycode,1,my_lengthcode,stdout);return 0;
}
"""

VM_MAIN = r"""
// No field transport is present in this process. Points are in-memory arrays.
S32_T vm_value_global=0,vm_v_global=0;
S32_T points[3][256]={};
extern "C" S16_T get_point_value(VM_Point*p,S32_T*v){
  if(p->point_type<1 || p->point_type>3)abort();
  *v=points[p->point_type-1][p->number];return 0;
}
extern "C" S16_T put_point_value(VM_Point*p,S32_T*v,S16_T,S16_T){
  if(p->point_type<1 || p->point_type>3)abort();
  points[p->point_type-1][p->number]=*v;return 0;
}
extern "C" S16_T get_net_point_value(VM_Point_Net*,S32_T*,U8_T,U8_T){abort();}
extern "C" S16_T put_net_point_value(VM_Point_Net*,S32_T*,S16_T,S16_T,U8_T){abort();}
extern "C" S16_T generatealarm(S8_T*,S16_T,S16_T,S16_T,S8_T,S8_T,S8_T*,S8_T){abort();}
extern "C" void generate_program_alarm(U8_T,U8_T){abort();}
extern "C" U8_T Get_Mini_Type(){return 0;}
extern "C" void Set_icon_config(U8_T){abort();}
S32_T* find_point(const char*p,char**end){
  int kind=-1;
  if(!strncmp(p,"IN",2)){kind=1;p+=2;}
  else if(!strncmp(p,"OUT",3)){kind=0;p+=3;}
  else if(!strncmp(p,"VAR",3)){kind=2;p+=3;}
  if(kind<0)return nullptr;long n=strtol(p,end,10);
  if(n<1 || n>(kind==2?256:64))return nullptr;
  return &points[kind][n-1];
}
int assign_point(char*text){
  char*end=nullptr;S32_T*point=find_point(text,&end);
  if(!point || *end!='=')return 2;
  double value=strtod(end+1,&end);
  if(*end || !isfinite(value) || fabs(value)>2000000)return 2;
  *point=(S32_T)(value*1000);return 0;
}
int main(int argc,char**argv){
  if(argc<3)return 2;
  U8_T code[2200]={};FILE*f=fopen(argv[1],"rb");if(!f)return 2;
  size_t count=fread(code,1,2001,f);fclose(f);if(count<9 || count>=2000)return 2;
  int scans=atoi(argv[2]);if(scans<1 || scans>1000)return 2;
  FILE*frames=nullptr;const char*watch_names[256]={};S32_T*watch_values[256]={};int watches=0;
  for(int i=3;i<argc;i++){
    if(!strncmp(argv[i],"--frames=",9)){
      if(frames)return 2;frames=fopen(argv[i]+9,"r");if(!frames)return 2;
    }else if(!strncmp(argv[i],"--watch=",8)){
      if(watches>=256)return 2;char*end=nullptr;
      watch_names[watches]=argv[i]+8;watch_values[watches]=find_point(argv[i]+8,&end);
      if(!watch_values[watches] || *end)return 2;watches++;
    }else if(assign_point(argv[i]))return 2;
  }
  char frame[32768];
  for(int i=0;i<scans;i++){
    if(frames){
      if(!fgets(frame,sizeof(frame),frames) || !strchr(frame,'\n'))return 2;
      for(char*token=strtok(frame," \t\r\n");token;token=strtok(nullptr," \t\r\n"))
        if(assign_point(token))return 2;
    }
    just_load=(i==0);exec_program(0,code);
    if(!watches)printf("@%d\t-\t0\n",i+1);
    for(int w=0;w<watches;w++)printf("@%d\t%s\t%.6f\n",i+1,watch_names[w],*watch_values[w]/1000.0);
  }
  if(frames)fclose(frames);
  for(int i=0;i<64;i++)printf("OUT%d\t%.6f\n",i+1,points[0][i]/1000.0);
  for(int i=0;i<256;i++)printf("VAR%d\t%.6f\n",i+1,points[2][i]/1000.0);
  U16_T base=0,len=0;memcpy(&base,code,2);
  if(base+7>count)return 3;memcpy(&len,code+base+5,2);
  if(base+7+len>count)return 3;U8_T*local=code+base+7;
  for(int i=0;i<len;){
    if(local[i]!=0x83 || i+5>=len)return 3;S32_T value=0;
    memcpy(&value,local+i+1,4);size_t n=strnlen((char*)local+i+5,len-i-5);
    if(n==len-i-5)return 3;
    printf("%s\t%.6f\n",local+i+5,value/1000.0);i+=6+n;
  }
  return 0;
}
"""


def run(args, cwd=None):
    subprocess.run(list(map(str, args)), cwd=cwd, check=True)


def build(sdk: Path):
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=sdk, text=True).strip()
    if actual != PIN:
        raise SystemExit(f"Expected pinned Temco revision {PIN}, found {actual}.")
    changes = subprocess.check_output(["git", "diff", "HEAD", "--name-only"], cwd=sdk)
    if changes.strip():
        raise SystemExit("Temco upstream tracked files have changes; use a clean checkout.")
    stage = sdk / "build/bms-host"
    stage.mkdir(parents=True, exist_ok=True)
    source = sdk / "T3000"
    compiler = (source / "CM5/BacNetProgram_transplant.cpp").read_text(encoding="latin1")
    compiler = compiler[: compiler.index("char * buf;")]
    start = compiler.index("extern  Panel ptr_panel;")
    end = compiler.index("int checklocalvar(char *tok)", start)
    compiler = compiler[:start] + POINT_RESOLVER + compiler[end:]
    compiler = compiler.replace('#include "stdafx.h"', '#include "portable.h"')
    compiler = compiler.replace('#include "..\\global_define.h"', "")
    compiler = compiler.replace('#include "parser.h"', '#include "PARSER.H"')
    # Windows permits assignment of a zero character constant to a pointer;
    # clang requires nullptr. Leave actual character writes unchanged.
    compiler = re.sub(r"(?<!\*)\btemp = '\\0'", "temp = nullptr", compiler)
    compiler = re.sub(r"\bwait\[", "cb_wait[", compiler)
    compiler = re.sub(r"\bdelete (local_table|renum);", r"delete[] \1;", compiler)
    full = (source / "CM5/BacNetProgram_transplant.cpp").read_text(encoding="latin1")
    start = full.index("static int try_readnet_enum_token(const char* text, long* value)\n{")
    end = full.index("static const char* readnet_enum_name_from_value", start)
    compiler += full[start:end]
    (stage / "compiler.cpp").write_text(compiler, encoding="latin1")
    for name in ("T3000DEF.H", "ROUTER.H", "PARSER.H"):
        (stage / name).write_bytes((source / "CM5" / name).read_bytes())
    constants = (source / "global_define.h").read_text(encoding="latin1")
    constants = constants[constants.index("#define BAC_OUT ") :]
    constants = constants[: constants.index("#define MAX_FUNCTION_COUNT")]
    (stage / "portable.h").write_text(PORTABLE + constants)
    (stage / "compiler_main.cpp").write_text(COMPILER_MAIN)

    shim = (source / "vm_shim.h").read_text()
    shim = shim.replace("#include <windows.h>", "")
    shim = shim.replace("typedef long     S32_T;", "typedef int32_t  S32_T;")
    shim = shim.replace("unsigned long", "uint32_t").replace(
        "long* arrays_address", "int32_t* arrays_address"
    )
    (stage / "vm_shim.h").write_text(shim)
    decode = (source / "decode.c").read_text(encoding="latin1")
    decode = re.sub(r'^#include "[^\n]+"', "", decode, flags=re.M)
    decode = re.sub(r"\blong\b", "int32_t", decode.replace("unsigned long", "uint32_t"))
    # GOSUB is excluded from the supported source profile and host input parser.
    # Retain the unused upstream branch while making its explicit truncation legal.
    decode = decode.replace("(S32_T)return_pointer", "(S32_T)(uintptr_t)return_pointer")
    (stage / "decode.cpp").write_text(decode, encoding="latin1")
    engine = (source / "VirtualProgramEngine.cpp").read_text()
    aliases = engine[engine.index("#define stack vm_stack") : engine.index("\n#undef v\n") + 10]
    aliases = aliases.replace('#include "decode.c"', '#include "decode.cpp"')
    variables = engine[
        engine.index("U8_T* prog = NULL;") : engine.index(
            "//=============================================================================\n// get_point_value"
        )
    ].replace("long* arrays_address", "int32_t* arrays_address")
    (stage / "vm_main.cpp").write_text(
        '#include "vm_shim.h"\n#include <cstdio>\n#include <cstdlib>\n'
        + aliases
        + "\n"
        + variables
        + VM_MAIN
    )
    flags = ["clang++", "-std=c++11", "-O1", "-w"]
    # Upstream has legacy warnings (including mismatched delete and unused code).
    # Host processes are short lived; tested paths use generated bounded input.
    for name in ("compiler", "vm"):
        run(flags + [stage / f"{name}_main.cpp", "-o", stage / f"temco-{name}"])
    sources = {}
    for name in (
        "CM5/BacNetProgram_transplant.cpp",
        "CM5/PARSER.H",
        "decode.c",
        "vm_shim.h",
        "VirtualProgramEngine.cpp",
    ):
        sources[name] = hashlib.sha256((source / name).read_bytes()).hexdigest()
    manifest = {
        "format": "bms-temco-host/1",
        "source_url": URL,
        "source_commit": PIN,
        "license": "MIT",
        "source_sha256": sources,
        "scope": "Local compiler/VM reference with simulated IN/OUT/VAR points only",
        "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "binary_sha256": {
            name: hashlib.sha256((stage / f"temco-{name}").read_bytes()).hexdigest()
            for name in ("compiler", "vm")
        },
    }
    (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (stage / "LICENSE.txt").write_bytes((sdk / "LICENSE.txt").read_bytes())
    print(f"Built Temco compiler and local reference VM in {stage}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sdk",
        type=Path,
        default=ROOT.parent / "Reference_Sources/temcocontrols--T3000",
    )
    args = parser.parse_args()
    sdk = args.sdk.resolve()
    if not sdk.exists():
        sdk.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--filter=blob:none", "--no-checkout", URL, sdk])
        run(["git", "sparse-checkout", "init", "--cone"], cwd=sdk)
        run(["git", "sparse-checkout", "set", "T3000/CM5"], cwd=sdk)
        run(["git", "checkout", "--detach", PIN], cwd=sdk)
    with (sdk / ".bms-toolchain.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            build(sdk)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


if __name__ == "__main__":
    main()
