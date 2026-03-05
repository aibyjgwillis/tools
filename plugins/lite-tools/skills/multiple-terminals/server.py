#!/usr/bin/env python3
"""Multiple Terminals - Web configurator for launching tiled Terminal.app windows.

Run: python3 server.py
Opens a browser-based UI on localhost:9848.
"""

import http.server
import json
import os
import subprocess
import sys
import threading
import webbrowser
import time as _time

VERSION = "1.1"
PORT = 9848
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.expanduser("~/.config/lite-tools")
CONFIG_PATH = os.path.join(CONFIG_DIR, "multiple-terminals.json")

_last_heartbeat = _time.time()
_heartbeat_timeout = 600


def get_all_active_windows():
    """Get all visible windows on the active desktop (current Space only).

    Uses CoreGraphics kCGWindowListOptionOnScreenOnly which only returns
    windows on the current Space. Terminal windows are counted from CG,
    other apps are listed individually.
    """
    windows = []
    skip_apps = {"Finder", "Dock", "Notification Center", "Control Center",
                 "WindowManager", "Spotlight", "SystemUIServer"}

    try:
        import Quartz
        options = (Quartz.kCGWindowListOptionOnScreenOnly
                   | Quartz.kCGWindowListExcludeDesktopElements)
        cg_windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)

        app_counts = {}
        for w in cg_windows:
            owner = w.get("kCGWindowOwnerName", "")
            layer = w.get("kCGWindowLayer", 0)
            bounds = w.get("kCGWindowBounds", {})
            bw = bounds.get("Width", 0)
            bh = bounds.get("Height", 0)

            if layer != 0 or bw < 100 or bh < 100 or owner in skip_apps:
                continue

            app_counts[owner] = app_counts.get(owner, 0) + 1
            is_terminal = (owner == "Terminal")
            windows.append({
                "app": owner,
                "index": app_counts[owner],
                "name": w.get("kCGWindowName", ""),
                "type": "terminal" if is_terminal else "other",
            })
    except ImportError:
        pass

    return windows


def load_config():
    """Load saved config from disk."""
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_config(data):
    """Save config to disk."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)


class QuietServer(http.server.HTTPServer):
    def handle_error(self, request, client_address):
        pass

    def shutdown_request(self, request):
        try:
            request.shutdown(2)
        except Exception:
            pass
        self.close_request(request)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/":
            html_path = os.path.join(SCRIPT_DIR, "interface.html")
            try:
                with open(html_path, "r") as f:
                    body = f.read().encode()
            except FileNotFoundError:
                body = b"<h1>interface.html not found</h1>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/api/heartbeat":
            global _last_heartbeat
            _last_heartbeat = _time.time()
            self.send_json({"ok": True})

        elif self.path == "/api/active-windows":
            windows = get_all_active_windows()
            terminal_count = sum(1 for w in windows if w["type"] == "terminal")
            other_count = sum(1 for w in windows if w["type"] == "other")
            self.send_json({
                "windows": windows,
                "terminalCount": terminal_count,
                "otherCount": other_count,
                "totalCount": len(windows),
            })

        elif self.path == "/api/config":
            self.send_json(load_config())

        else:
            self.send_response(404)
            self.end_headers()

    def _build_cmd(self, body):
        cmd = [sys.executable, os.path.join(SCRIPT_DIR, "multiple-terminals.py")]
        cmd += ["--count", str(body.get("count", 3))]
        cmd += ["--layout", body.get("layout", "side-by-side")]

        theme = body.get("theme")
        colors = body.get("colors")
        mode = body.get("mode")
        if theme:
            cmd += ["--theme", theme]
        elif colors:
            cmd += ["--colors", colors]
        elif mode:
            cmd += ["--mode", mode]

        if body.get("includeAll"):
            cmd.append("--include-all")
        if body.get("noClaude"):
            cmd.append("--no-claude")
        if body.get("commands"):
            cmd += ["--commands", body["commands"]]
        if body.get("notify"):
            cmd.append("--notify")
        if body.get("sound"):
            cmd.append("--sound")
        if body.get("soundName"):
            cmd += ["--sound-name", body["soundName"]]
        if body.get("soundVolume") is not None:
            cmd += ["--sound-volume", str(body["soundVolume"])]
        if body.get("skipPerms"):
            cmd.append("--skip-perms")
        if body.get("highlightColor"):
            cmd += ["--highlight-color", body["highlightColor"]]
        return cmd

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"

        if self.path in ("/api/apply", "/api/launch", "/api/restyle"):
            body = json.loads(raw)
            cmd = self._build_cmd(body)
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                self.send_json({
                    "ok": result.returncode == 0,
                    "output": result.stdout.strip(),
                    "error": result.stderr.strip() if result.returncode != 0 else ""
                })
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 500)

        elif self.path == "/api/config":
            body = json.loads(raw)
            save_config(body)
            self.send_json({"ok": True})

        elif self.path == "/api/test-sound":
            body = json.loads(raw)
            name = body.get("soundName", "Submarine")
            volume = body.get("soundVolume", 0.2)
            path = f"/System/Library/Sounds/{name}.aiff"
            try:
                subprocess.Popen(
                    ["afplay", "-v", str(volume), path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                self.send_json({"ok": True})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 500)

        else:
            self.send_response(404)
            self.end_headers()


def main():
    print(f"\nMultiple Terminals v{VERSION}")
    print(f"  Server ........ http://localhost:{PORT}")
    print(f"  Config ........ {CONFIG_PATH}")
    print(f"  Auto-shutdown . {_heartbeat_timeout}s after tab close\n")

    server = QuietServer(("127.0.0.1", PORT), Handler)
    webbrowser.open(f"http://localhost:{PORT}")

    def heartbeat_watchdog():
        while True:
            _time.sleep(3)
            if _time.time() - _last_heartbeat > _heartbeat_timeout:
                print("Tab closed, shutting down.")
                server.shutdown()
                break

    watchdog = threading.Thread(target=heartbeat_watchdog, daemon=True)
    watchdog.start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
