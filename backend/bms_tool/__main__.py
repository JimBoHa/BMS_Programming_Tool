"""CLI for the local studio and reproducible offline batch work."""

import argparse
import json
from pathlib import Path

from .caf import CafArchive
from .engine import run_scenario, validate
from .formats import export_program, import_program


def main():
    parser = argparse.ArgumentParser(
        description="BMS Studio local editor, simulator, and interoperability tools"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--data")
    serve.add_argument("--open-browser", action="store_true")
    gate = sub.add_parser(
        "inline-heat-gate", help="Review a native inline heating permissive in a local backup"
    )
    gate.add_argument("application", type=Path)
    gate.add_argument("static", type=Path)
    gate.add_argument("dynamic", type=Path)
    for option in ("diagram", "pressure", "flow", "enable", "passthrough", "valve"):
        gate.add_argument("--" + option, required=True)
    gate.add_argument("--threshold-cfm", type=float, required=True)
    gate.add_argument("--first-instance", type=int, default=3_000_000)
    gate.add_argument("--output", type=Path)
    gate.add_argument("--review-sha256")
    inline = sub.add_parser(
        "inline-reheat-draft", help="Review and save an offline inline reheat program"
    )
    for name in ("application", "static", "dynamic", "prototype"):
        inline.add_argument("--" + name, type=Path, required=True)
    inline.add_argument("--first-instance", type=int, required=True)
    inline.add_argument("--purpose", choices=("observe", "control"), default="observe")
    inline.add_argument("--layout", choices=("flat", "activities"), default="activities")
    inline.add_argument("--sampling", choices=("paired", "clock-edge"), default="paired")
    inline.add_argument("--output", type=Path)
    inline.add_argument("--review-sha256")
    for name in ("validate", "simulate", "export", "caf"):
        p = sub.add_parser(name)
        p.add_argument("file", type=Path)
        if name == "simulate":
            p.add_argument("--scenario", type=Path, required=True)
        if name == "export":
            p.add_argument(
                "--format",
                choices=[
                    "json",
                    "st",
                    "plcopen",
                    "graphml",
                    "sedona",
                    "sedona-sax",
                    "sedona-sab",
                    "bog",
                    "temco-bas",
                ],
                required=True,
            )
            p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn

        from .app import create_app

        if args.open_browser:
            import threading
            import webbrowser

            threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
        uvicorn.run(create_app(args.data), host="127.0.0.1", port=args.port, access_log=False)
    elif args.command == "inline-heat-gate":
        from .native_inline_heat import local_copy

        print(json.dumps(local_copy(args), indent=2))
    elif args.command == "inline-reheat-draft":
        from .native_inline_draft import local_draft

        print(json.dumps(local_draft(args), indent=2))
    elif args.command == "caf":
        print(json.dumps(CafArchive(args.file.read_bytes()).summary(), indent=2))
    else:
        program = import_program(args.file.read_bytes(), args.file.name)
        if args.command == "validate":
            issues = validate(program)
            print(json.dumps([i.model_dump() for i in issues], indent=2))
            if any(i.level == "error" for i in issues):
                raise SystemExit(1)
        elif args.command == "export":
            args.output.write_bytes(export_program(program, args.format)[0])
        elif args.command == "simulate":
            scenario = json.loads(args.scenario.read_text())
            print(json.dumps(run_scenario(program, **scenario), indent=2))


if __name__ == "__main__":
    main()
