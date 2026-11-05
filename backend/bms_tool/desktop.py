"""Desktop owner for one loopback server and a small, native launcher window."""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import platform
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse

from . import __version__
from .file_access import open_regular, try_lock, unlock
from .resources import state_directory, web_directory

PROFILE = "bms-studio-desktop/1"


def local_json(url):
    # A proxy environment variable must not send local session data elsewhere.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=2) as response:
        return json.loads(response.read(16384))


class Desktop:
    def __init__(self, directory, port=8765):
        self.directory = Path(directory).resolve()
        self.port = port
        self.descriptor = None
        self.server = self.thread = self.socket = None
        self.identity = secrets.token_hex(24)
        self.control_token = secrets.token_hex(32)
        self.url = None
        self.reused = False

    def start(self, timeout=45):
        """Keep the ownership inode; validate a live owner before reusing its URL."""
        self.directory.mkdir(parents=True, exist_ok=True)
        self.descriptor = open_regular(self.directory / "desktop.lock", writable=True, create=True)
        try:
            try_lock(self.descriptor)
        except BlockingIOError:
            os.close(self.descriptor)
            self.descriptor = None
            try:
                record_descriptor = open_regular(self.directory / "desktop-session.json")
                try:
                    raw = os.read(record_descriptor, 4096)
                finally:
                    os.close(record_descriptor)
                record = json.loads(raw)
                port = record["port"]
                if type(port) is not int or not 1 <= port <= 65535:
                    raise ValueError
                url = f"http://127.0.0.1:{port}"
                identity = local_json(url + "/api/desktop/identity")
                public_record = {k: v for k, v in record.items() if k != "control_token"}
                if identity != public_record or record["profile"] != PROFILE:
                    raise ValueError
            except (OSError, ValueError, KeyError) as exc:
                raise RuntimeError(
                    "BMS Studio is already starting or its owner cannot be verified. "
                    "Wait a few seconds and try again; see logs/desktop.log."
                ) from exc
            self.url, self.reused = url, True
            return self.url
        try:
            if web_directory() is None:
                raise RuntimeError("The bundled browser UI is missing. Reinstall BMS Studio.")
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if os.name == "nt":
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                self.socket.bind(("127.0.0.1", self.port))
            except OSError:
                if not self.port:
                    raise
                self.socket.bind(("127.0.0.1", 0))
            self.socket.listen(128)
            self.port = self.socket.getsockname()[1]
            self.url = f"http://127.0.0.1:{self.port}"
            record = {
                "profile": PROFILE,
                "instance": self.identity,
                "port": self.port,
                "version": __version__,
                "platform": sys.platform,
                "architecture": platform.machine(),
            }
            import uvicorn

            from .app import create_app

            app = create_app(str(self.directory))

            def desktop_identity():
                return record

            async def stop_desktop(request: Request):
                if not secrets.compare_digest(
                    request.headers.get("x-desktop-control", ""), self.control_token
                ):
                    return JSONResponse(
                        {"detail": "Private desktop ownership proof is required."}, 403
                    )
                if self.quit_blocked():
                    return JSONResponse(
                        {
                            "detail": "Finish operations, release owned commands and disconnect before quitting."
                        },
                        409,
                    )
                self.server.should_exit = True
                return {"stopping": True}

            # create_app mounts the browser fallback last; insert this API route
            # ahead of that mount rather than making it an unreachable suffix.
            from fastapi.routing import APIRoute

            app.router.routes.insert(
                0, APIRoute("/api/desktop/identity", desktop_identity, methods=["GET"])
            )
            app.router.routes.insert(
                0, APIRoute("/api/desktop/stop", stop_desktop, methods=["POST"])
            )

            config = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=self.port,
                access_log=False,
                log_config=None,
                loop="asyncio",
                http="h11",
                ws="none",
                timeout_graceful_shutdown=30,
            )
            self.server = uvicorn.Server(config)
            self.thread = threading.Thread(
                target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True
            )
            self.thread.start()
            deadline = time.monotonic() + timeout
            while not self.server.started:
                if not self.thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("The local editor did not start. See logs/desktop.log.")
                time.sleep(0.05)
            # Publish only after readiness; stale records do not prove ownership.
            # Windows byte-range ownership prevents other processes reading the
            # locked byte. Keep the persistent lock inode separate from the
            # atomically replaced, independently verified readiness record.
            with tempfile.NamedTemporaryFile(
                dir=self.directory, prefix=".desktop-session-", delete=False
            ) as ready:
                temporary_record = Path(ready.name)
                ready.write(json.dumps({**record, "control_token": self.control_token}).encode())
                ready.flush()
                os.fsync(ready.fileno())
            try:
                os.replace(temporary_record, self.directory / "desktop-session.json")
            finally:
                temporary_record.unlink(missing_ok=True)
            return self.url
        except BaseException:
            self.close()
            raise

    def quit_blocked(self):
        if self.server is None:
            return False
        state = self.server.config.app.state
        return bool(
            state.bacnet.status()["connected"]
            or state.bacnet.status()["commands"]
            or state.native_applications.active
            or state.device_instances.status()["active_operation"]
        )

    def close(self):
        if self.server is not None:
            self.server.should_exit = True
        if self.thread is not None:
            self.thread.join(timeout=35)
            if self.thread.is_alive():
                raise RuntimeError(
                    "The local editor is still finishing shutdown; ownership retained."
                )
        if self.socket is not None:
            self.socket.close()
            self.socket = None
        if self.descriptor is not None:
            unlock(self.descriptor)
            os.close(self.descriptor)
            self.descriptor = None


def open_folder(directory):
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(directory)])
    elif sys.platform == "win32":
        os.startfile(str(directory))
    else:
        subprocess.Popen(["xdg-open", str(directory)])


def window(desktop, sharing=None):
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title("BMS Studio")
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=24)
    frame.grid()
    ttk.Label(frame, text="BMS Studio", font=("Helvetica", 22, "bold")).grid(sticky="w")
    ttk.Label(frame, text=f"Beta {__version__} · Local editor ready").grid(sticky="w", pady=(8, 4))
    ttk.Label(frame, text=desktop.url).grid(sticky="w", pady=(0, 16))
    if sharing is not None:
        ttk.Label(frame, text="Authenticated LAN access: " + sharing.config.url).grid(
            sticky="w", pady=(0, 8)
        )
    ttk.Button(frame, text="Open editor", command=lambda: webbrowser.open(desktop.url)).grid(
        sticky="ew"
    )
    ttk.Button(
        frame, text="Open logs", command=lambda: open_folder(desktop.directory / "logs")
    ).grid(sticky="ew", pady=8)
    ttk.Label(frame, text="Closing a browser tab leaves the local editor running.").grid(
        sticky="w", pady=8
    )

    def quit_app():
        if desktop.quit_blocked():
            messagebox.showinfo(
                "Disconnect before quitting",
                "Finish any active operation, release owned commands and disconnect "
                "the field interface in the editor before quitting.",
                parent=root,
            )
            return
        root.destroy()

    ttk.Button(frame, text="Quit BMS Studio", command=quit_app).grid(sticky="ew", pady=(8, 0))
    root.protocol("WM_DELETE_WINDOW", quit_app)
    if sys.platform == "darwin":
        root.createcommand("tk::mac::Quit", quit_app)
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--share-config", type=Path, help="Private authenticated LAN configuration")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--headless", action="store_true", help="Run without the launcher window")
    parser.add_argument(
        "--check-not-running", action="store_true", help="Installer ownership check"
    )
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("Port must be between 0 and 65535.")
    directory = (args.data or state_directory()).resolve()
    if args.check_not_running:
        directory.mkdir(parents=True, exist_ok=True)
        descriptor = open_regular(directory / "desktop.lock", writable=True, create=True)
        try:
            try_lock(descriptor)
            unlock(descriptor)
        except BlockingIOError:
            raise SystemExit(1) from None
        finally:
            os.close(descriptor)
        return
    logs = directory / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        logs / "desktop.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    desktop = Desktop(directory, args.port)
    sharing = None
    try:
        desktop.start()
        if args.share_config:
            if desktop.reused:
                raise RuntimeError("Quit the existing editor before starting it with LAN sharing.")
            from .lan import LANConfig, LANServer

            sharing = LANServer(LANConfig.load(args.share_config), desktop.url)
            sharing.start()
        logging.info("BMS Studio %s ready at %s", __version__, desktop.url)
        if not args.no_browser:
            webbrowser.open(desktop.url)
        if desktop.reused:
            return
        if args.headless:
            stop = threading.Event()
            for signum in (signal.SIGINT, signal.SIGTERM):
                signal.signal(signum, lambda *_: stop.set())
            while desktop.thread.is_alive() and not stop.wait(0.2):
                pass
        else:
            window(desktop, sharing)
    except Exception as exc:
        logging.exception("Desktop startup or shutdown failed")
        if args.headless:
            raise
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("BMS Studio could not start", f"{exc}\n\nLogs: {logs}", parent=root)
        root.destroy()
        raise SystemExit(1) from exc
    finally:
        if sharing is not None:
            sharing.close()
        desktop.close()


if __name__ == "__main__":
    main()
