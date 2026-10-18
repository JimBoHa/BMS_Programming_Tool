"""CLI for the local studio and reproducible offline batch work."""

import argparse
import json
from pathlib import Path

from .caf import CafArchive
from .engine import run_scenario, validate
from .formats import export_program
from .models import Program


def main():
    parser = argparse.ArgumentParser(
        description="BMS Studio local editor, simulator, and interoperability tools"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--data")
    serve.add_argument("--open-browser", action="store_true")
    for name in ("validate", "simulate", "export", "caf"):
        p = sub.add_parser(name)
        p.add_argument("file", type=Path)
        if name == "simulate":
            p.add_argument("--scenario", type=Path, required=True)
        if name == "export":
            p.add_argument("--format", choices=["json", "st", "plcopen", "graphml"], required=True)
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
    elif args.command == "caf":
        print(json.dumps(CafArchive(args.file.read_bytes()).summary(), indent=2))
    else:
        program = Program.model_validate_json(args.file.read_bytes())
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
