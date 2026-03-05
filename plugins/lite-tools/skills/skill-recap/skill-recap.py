#!/usr/bin/env python3
"""Skill Recap - Visual summary of what a skill just did.

Run: python3 skill-recap.py
Opens a browser-based UI on localhost:9848.

NOTE: This is a local-only tool. All HTML rendering uses data POSTed
from the local Claude Code process. No external/untrusted input is processed.
All rendered text is escaped via textContent-based escHtml() before insertion.
"""

import http.server
import json
import os
import subprocess
import sys
import threading
import webbrowser
import time as _time

VERSION = "1.2"
PORT = 9848

# Heartbeat: track last ping from browser, auto-shutdown when tab closes
_last_heartbeat = _time.time()
_heartbeat_timeout = 10  # seconds without a ping before shutdown

# Store the most recent recap data
_recap_data = None

# Common skill directories to search
_HOME = os.path.expanduser("~")
_SKILL_SEARCH_DIRS = [
    os.path.join(_HOME, "tools", "plugins"),
    os.path.join(_HOME, ".claude", "plugins"),
    os.path.join(_HOME, ".claude", "skills"),
]

def _find_skill_path(skill_name):
    """Search common directories for a SKILL.md matching the skill name."""
    for base in _SKILL_SEARCH_DIRS:
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            if "SKILL.md" in files:
                # Check if directory name matches skill name
                dirname = os.path.basename(root)
                if dirname == skill_name:
                    return os.path.join(root, "SKILL.md")
            # Don't recurse too deep
            if root.count(os.sep) - base.count(os.sep) > 4:
                dirs.clear()
    return None


def run_preflight():
    """Run startup checks and print pass/fail for each."""
    checks = []

    def check(name, fn):
        try:
            ok = fn()
            checks.append((name, ok))
        except Exception:
            checks.append((name, False))

    check("Python 3.6+", lambda: sys.version_info >= (3, 6))

    import socket
    def check_port():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", PORT))
            s.close()
            return True
        except OSError:
            s.close()
            return False

    check(f"Port {PORT} available", check_port)

    print(f"\nSkill Recap v{VERSION}")
    all_ok = True
    for name, ok in checks:
        dots = "." * (24 - len(name))
        status = "ok" if ok else "FAIL"
        print(f"  {name} {dots} {status}")
        if not ok:
            all_ok = False

    if not all_ok:
        print("\nSome checks failed. The server may not start correctly.\n")
    else:
        print()

    return all_ok


class ThreadedHTTPServer(http.server.HTTPServer):
    """Handle each request in a separate thread."""
    def process_request(self, request, client_address):
        t = threading.Thread(target=self.process_request_thread, args=(request, client_address))
        t.daemon = True
        t.start()

    def process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _html(self, content):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        global _last_heartbeat
        if self.path == "/":
            self._html(HTML)
        elif self.path == "/api/recap":
            if _recap_data:
                self._json(_recap_data)
            else:
                self._json({"empty": True})
        elif self.path == "/api/heartbeat":
            _last_heartbeat = _time.time()
            self._json({"ok": True})
        else:
            self.send_error(404)

    def do_POST(self):
        global _recap_data
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if self.path == "/api/recap":
            # Auto-find skill_path if not provided
            if not body.get("skill_path") and body.get("skill_name"):
                found = _find_skill_path(body["skill_name"])
                if found:
                    body["skill_path"] = found
            _recap_data = body
            self._json({"ok": True})
        elif self.path == "/api/read-file":
            raw = body.get("path", "")
            expanded = os.path.expanduser(raw)
            if os.path.isfile(expanded):
                try:
                    with open(expanded, "r") as f:
                        content = f.read()
                    self._json({"ok": True, "content": content, "path": expanded})
                except Exception as e:
                    self._json({"error": str(e)}, 500)
            else:
                self._json({"error": "File not found", "path": expanded}, 404)
        elif self.path == "/api/open":
            raw = body.get("path", "")
            expanded = os.path.expanduser(raw)
            if os.path.exists(expanded):
                subprocess.Popen(["open", expanded])
                self._json({"ok": True})
            else:
                self._json({"error": "Path not found", "path": expanded}, 404)
        else:
            self.send_error(404)


# -- HTML UI -----------------------------------------------------------------
# NOTE: All dynamic content is escaped via escHtml() which uses
# document.createElement('div').textContent, preventing XSS.
# Data originates solely from the local Claude Code process.

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Skill Recap</title>
<!-- ==THEME:FONTS== -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Playfair+Display:ital,wght@0,400;0,700;1,400&family=JetBrains+Mono:wght@300;400;500&display=swap" rel="stylesheet">
<!-- ==/THEME:FONTS== -->
<style>
/* ==THEME:VARS== */
:root {
  --obsidian: #0F1114; --champagne: #5A7D96; --ivory: #F5F5F3;
  --slate: #1C1C1E;
  --font-heading: 'Inter', sans-serif;
  --font-drama: 'Playfair Display', serif;
  --font-mono: 'JetBrains Mono', monospace;
  --green: #2D8659; --green-bg: rgba(45,134,89,0.08);
  --amber: #B8860B; --amber-bg: rgba(184,134,11,0.08);
  --red: #C0392B; --red-bg: rgba(192,57,43,0.08);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: var(--font-heading); background: var(--ivory);
  color: var(--slate); min-height: 100vh;
  -webkit-font-smoothing: antialiased;
}
/* ==/THEME:VARS== */
/* ==THEME:NOISE_CSS== */
.noise-overlay { position: fixed; inset: 0; z-index: 9999; pointer-events: none; opacity: 0.04; }
/* ==/THEME:NOISE_CSS== */

/* ==THEME:TOPBAR== */
.topbar {
  width: 100%; min-height: 56px; padding: 0 36px; display: flex; align-items: center;
  justify-content: space-between; border-bottom: 1px solid rgba(28,28,30,0.08);
}
.topbar-brand { font-weight: 700; font-size: 13px; letter-spacing: 0.12em; text-transform: uppercase; }
.topbar-pill {
  font-family: var(--font-mono); font-size: 11px; font-weight: 500;
  background: rgba(28,28,30,0.06); border-radius: 2rem; padding: 5px 14px;
  color: var(--champagne);
}
.topbar-tabs { display: flex; background: rgba(28,28,30,0.05); border-radius: 2rem; padding: 3px; }
.topbar-tab {
  padding: 7px 20px; border-radius: 2rem; border: none; font-family: var(--font-heading);
  font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.3s;
  color: rgba(28,28,30,0.45); background: none; letter-spacing: 0.02em;
}
.topbar-tab:hover { color: var(--slate); }
.topbar-tab.active { background: var(--slate); color: var(--ivory); }
/* ==/THEME:TOPBAR== */
.topbar-right { display: flex; align-items: center; gap: 8px; }
.topbar-btn {
  font-family: var(--font-mono); font-size: 10px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.06em;
  background: none; border: 1px solid rgba(28,28,30,0.12);
  border-radius: 6px; padding: 5px 12px; cursor: pointer;
  color: var(--champagne); transition: all 0.2s;
}
.topbar-btn:hover { background: rgba(28,28,30,0.05); color: var(--slate); }
.topbar-btn.copied { background: var(--green-bg); color: var(--green); border-color: rgba(45,134,89,0.2); }

.main {
  max-width: 700px; margin: 0 auto; padding: 48px 24px 80px;
}
.main > * { animation: fadeUp 0.45s ease-out both; }
.main > *:nth-child(1) { animation-delay: 0.05s; }
.main > *:nth-child(2) { animation-delay: 0.12s; }
.main > *:nth-child(3) { animation-delay: 0.19s; }
.main > *:nth-child(4) { animation-delay: 0.26s; }
.main > *:nth-child(5) { animation-delay: 0.33s; }
.main > *:nth-child(6) { animation-delay: 0.40s; }
.main > *:nth-child(7) { animation-delay: 0.47s; }
.main > *:nth-child(8) { animation-delay: 0.54s; }
/* ==THEME:FADEIN== */
@keyframes fadeUp { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
/* ==/THEME:FADEIN== */

/* ==THEME:PAGE_TITLE== */
.page-title {
  font-family: var(--font-drama); font-size: 32px; font-weight: 400;
  font-style: italic; text-align: center; margin-bottom: 8px;
}
.page-subtitle {
  font-family: var(--font-mono); font-size: 12px; color: var(--champagne);
  text-align: center; margin-bottom: 40px;
}
/* ==/THEME:PAGE_TITLE== */

/* ==THEME:SECTION_LABEL== */
.section-label {
  font-family: var(--font-mono); font-size: 10px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.14em; color: var(--champagne);
  margin-bottom: 12px;
}
/* ==/THEME:SECTION_LABEL== */

/* ==THEME:CARDS== */
.card {
  background: white; border: 1px solid rgba(28,28,30,0.08);
  border-radius: 12px; padding: 20px 24px; margin-bottom: 20px;
}
.card-champagne { background: rgba(90,125,150,0.04); border-color: rgba(90,125,150,0.12); }
.card-amber { background: var(--amber-bg); border-color: rgba(184,134,11,0.15); }
/* ==/THEME:CARDS== */

/* Status badge */
.status-badge {
  display: inline-block; font-family: var(--font-mono); font-size: 11px;
  font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em;
  padding: 4px 14px; border-radius: 2rem; margin-bottom: 24px;
}
.status-badge.success { background: var(--green-bg); color: var(--green); }
.status-badge.partial { background: var(--amber-bg); color: var(--amber); }
.status-badge.failed { background: var(--red-bg); color: var(--red); }

/* Summary */
.summary-text { font-size: 15px; line-height: 1.6; color: var(--slate); }

/* Actions list */
.action-item {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 10px 0; border-bottom: 1px solid rgba(28,28,30,0.05);
}
.action-item:last-child { border-bottom: none; }
.action-tag {
  font-family: var(--font-mono); font-size: 10px; font-weight: 600;
  padding: 2px 8px; border-radius: 4px; white-space: nowrap; margin-top: 2px;
}
.action-tag.created { background: var(--green-bg); color: var(--green); }
.action-tag.modified { background: rgba(90,125,150,0.1); color: var(--champagne); }
.action-tag.deleted { background: var(--red-bg); color: var(--red); }
.action-tag.command { background: rgba(28,28,30,0.06); color: var(--slate); }
.action-path {
  font-family: var(--font-mono); font-size: 12px; font-weight: 500;
  color: var(--slate); word-break: break-all;
}
.action-detail { font-size: 12px; color: var(--champagne); margin-top: 2px; }

/* Diffs */
.diff-block { margin-bottom: 16px; }
.diff-block:last-child { margin-bottom: 0; }
.diff-file {
  font-family: var(--font-mono); font-size: 11px; font-weight: 600;
  color: var(--champagne); margin-bottom: 8px;
}
.diff-panels { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.diff-panel {
  background: rgba(28,28,30,0.03); border: 1px solid rgba(28,28,30,0.08);
  border-radius: 8px; padding: 12px; overflow-x: auto;
}
.diff-panel-label {
  font-family: var(--font-mono); font-size: 9px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.1em; color: var(--champagne);
  margin-bottom: 8px;
}
.diff-panel pre {
  font-family: var(--font-mono); font-size: 12px; line-height: 1.7;
  margin: 0; white-space: pre-wrap; word-break: break-all;
}
.diff-line-removed { color: var(--red); background: var(--red-bg); padding: 1px 4px; border-radius: 3px; display: inline; }
.diff-line-added { color: var(--green); background: var(--green-bg); padding: 1px 4px; border-radius: 3px; display: inline; }

/* Warnings */
.warning-item {
  display: flex; align-items: flex-start; gap: 8px;
  font-size: 13px; color: var(--amber); padding: 10px 0;
  border-bottom: 1px solid rgba(184,134,11,0.1);
}
.warning-item:last-child { border-bottom: none; }
.warning-icon { font-family: var(--font-mono); font-weight: 700; flex-shrink: 0; margin-top: 1px; }
.warning-text { flex: 1; line-height: 1.5; }
.warning-copy {
  flex-shrink: 0; font-family: var(--font-mono); font-size: 9px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.06em;
  background: rgba(184,134,11,0.1); border: 1px solid rgba(184,134,11,0.2);
  border-radius: 4px; padding: 3px 8px; cursor: pointer;
  color: var(--amber); transition: all 0.2s; white-space: nowrap; margin-top: 1px;
}
.warning-copy:hover { background: rgba(184,134,11,0.2); }
.warning-copy.copied { background: var(--green-bg); color: var(--green); border-color: rgba(45,134,89,0.2); }
.warning-copy[title] { position: relative; }
.warning-copy:hover::after {
  content: attr(title); position: absolute; bottom: calc(100% + 6px); right: 0;
  font-family: var(--font-mono); font-size: 9px; white-space: nowrap;
  background: var(--slate); color: var(--ivory); padding: 4px 8px;
  border-radius: 4px; pointer-events: none;
}

/* Next steps */
.step-item {
  display: flex; align-items: baseline; gap: 0; padding: 8px 0;
}
.step-num {
  font-family: var(--font-mono); font-size: 12px; font-weight: 700;
  color: var(--champagne); width: 28px; flex-shrink: 0; text-align: right;
  padding-right: 10px;
}
.step-text { font-size: 13px; line-height: 1.5; color: var(--slate); }

/* Open in Finder link */
.open-link {
  font-family: var(--font-mono); font-size: 10px; font-weight: 500;
  color: var(--champagne); text-decoration: none; cursor: pointer;
  border: 1px solid rgba(90,125,150,0.2); border-radius: 4px;
  padding: 2px 7px; margin-left: 8px; transition: all 0.2s;
  white-space: nowrap;
}
.open-link:hover { background: rgba(90,125,150,0.08); color: var(--slate); }

/* Empty state */
.empty-state {
  text-align: center; padding: 80px 24px;
}
.empty-title {
  font-family: var(--font-drama); font-size: 24px; font-style: italic;
  margin-bottom: 12px; color: var(--slate);
}
.empty-text {
  font-family: var(--font-mono); font-size: 12px; color: var(--champagne);
  line-height: 1.8;
}

/* Timestamp + duration row */
.meta-row {
  text-align: center; margin-bottom: 20px;
  font-family: var(--font-mono); font-size: 11px; color: var(--champagne);
}
.meta-separator { margin: 0 8px; opacity: 0.4; }

/* Stats row */
.stats-row {
  display: flex; justify-content: center; gap: 8px; flex-wrap: wrap;
  margin-bottom: 28px;
}
.stat-pill {
  font-family: var(--font-mono); font-size: 10px; font-weight: 600;
  padding: 4px 12px; border-radius: 2rem;
  background: rgba(28,28,30,0.05); color: var(--slate);
}
.stat-pill.has-warnings { background: var(--amber-bg); color: var(--amber); }

/* Action group headers */
.action-group-header {
  font-family: var(--font-mono); font-size: 10px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.1em; color: var(--champagne);
  padding: 8px 0 4px; margin-top: 8px;
  border-top: 1px solid rgba(28,28,30,0.06);
}
.action-group-header:first-child { border-top: none; margin-top: 0; }

/* Copy JSON button */
.copy-btn {
  font-family: var(--font-mono); font-size: 10px; font-weight: 500;
  background: rgba(28,28,30,0.05); border: 1px solid rgba(28,28,30,0.1);
  border-radius: 6px; padding: 5px 12px; cursor: pointer;
  color: var(--champagne); transition: all 0.2s;
}
.copy-btn:hover { background: rgba(28,28,30,0.1); color: var(--slate); }
.copy-btn.copied { background: var(--green-bg); color: var(--green); border-color: rgba(45,134,89,0.2); }

/* ==THEME:FOOTER_CSS== */
.footer {
  position: fixed; bottom: 0; left: 0; right: 0;
  display: flex; align-items: center; justify-content: center;
  padding: 14px 24px;
  font-family: var(--font-mono); font-size: 10px; color: rgba(28,28,30,0.3);
  background: linear-gradient(transparent, var(--ivory) 40%);
  gap: 14px;
}
.footer a { color: var(--champagne); text-decoration: none; }
.footer a:hover { color: var(--slate); }
.footer-sep { opacity: 0.3; }
.footer-socials { display: flex; align-items: center; gap: 10px; }
.footer-socials a { display: flex; align-items: center; }
.footer-socials svg { width: 13px; height: 13px; fill: var(--champagne); opacity: 0.6; transition: opacity 0.2s; }
.footer-socials a:hover svg { opacity: 1; }
.footer-waitlist { position: relative; }
.footer-waitlist-btn {
  font-family: var(--font-mono); font-size: 10px; font-weight: 500;
  background: var(--slate); color: var(--ivory); border: none; border-radius: 2rem;
  padding: 5px 12px; cursor: pointer; transition: all 0.2s; letter-spacing: 0.02em;
}
.footer-waitlist-btn:hover { background: var(--obsidian); }
.footer-waitlist-form {
  position: absolute; bottom: 32px; right: 0; background: white;
  border: 1px solid rgba(28,28,30,0.1); border-radius: 10px; padding: 14px;
  display: none; flex-direction: column; gap: 8px; min-width: 240px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.08);
}
.footer-waitlist-form.open { display: flex; }
.footer-waitlist-form label {
  font-family: var(--font-mono); font-size: 10px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.1em; color: var(--champagne);
}
.footer-waitlist-form input {
  font-family: var(--font-heading); font-size: 13px; padding: 8px 12px;
  border: 1px solid rgba(28,28,30,0.12); border-radius: 6px; outline: none;
  transition: border-color 0.2s; color: var(--slate); background: var(--ivory);
}
.footer-waitlist-form input:focus { border-color: var(--champagne); }
.footer-waitlist-form .footer-waitlist-submit {
  font-family: var(--font-heading); font-size: 12px; font-weight: 600;
  background: var(--slate); color: var(--ivory); border: none; border-radius: 6px;
  padding: 8px; cursor: pointer; transition: all 0.2s;
}
.footer-waitlist-form .footer-waitlist-submit:hover { background: var(--obsidian); }
.footer-waitlist-msg {
  font-family: var(--font-mono); font-size: 10px; color: var(--green);
}
/* ==/THEME:FOOTER_CSS== */

/* Skill file viewer panel */
.viewer-overlay {
  position: fixed; inset: 0; background: rgba(15,17,20,0.4);
  z-index: 10000; opacity: 0; pointer-events: none; transition: opacity 0.25s;
}
.viewer-overlay.open { opacity: 1; pointer-events: auto; }
.viewer-panel {
  position: fixed; top: 0; right: 0; bottom: 0; width: min(560px, 90vw);
  background: white; z-index: 10001; box-shadow: -4px 0 24px rgba(0,0,0,0.12);
  transform: translateX(100%); transition: transform 0.3s ease;
  display: flex; flex-direction: column;
}
.viewer-panel.open { transform: translateX(0); }
.viewer-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 20px; border-bottom: 1px solid rgba(28,28,30,0.08);
}
.viewer-title { font-family: var(--font-mono); font-size: 12px; font-weight: 600; color: var(--slate); }
.viewer-close {
  background: none; border: none; font-size: 18px; cursor: pointer;
  color: var(--champagne); padding: 4px 8px; border-radius: 4px;
}
.viewer-close:hover { background: rgba(28,28,30,0.05); color: var(--slate); }
.viewer-body {
  flex: 1; overflow-y: auto; padding: 20px;
}
.viewer-body pre {
  font-family: var(--font-mono); font-size: 12px; line-height: 1.7;
  color: var(--slate); white-space: pre-wrap; word-break: break-word;
}

/* Responsive diffs */
@media (max-width: 600px) {
  .diff-panels { grid-template-columns: 1fr; }
  .main { padding: 32px 16px 80px; }
  .topbar { padding: 14px 20px; }
  .stats-row { gap: 6px; }
}
</style>
</head>
<body>
<!-- ==THEME:NOISE_HTML== -->
<svg class="noise-overlay" width="100%" height="100%">
  <filter id="noise"><feTurbulence type="fractalNoise" baseFrequency="0.65" numOctaves="3" stitchTiles="stitch"/></filter>
  <rect width="100%" height="100%" filter="url(#noise)"/>
</svg>
<!-- ==/THEME:NOISE_HTML== -->

<div class="topbar">
  <div class="topbar-brand">Skill Recap</div>
  <div class="topbar-right">
    <button class="topbar-btn" id="viewSkillBtn" style="display:none;">View Skill</button>
    <button class="topbar-btn" id="editSkillBtn" style="display:none;">Edit Skill</button>
    <div class="topbar-pill" id="skillPill">...</div>
  </div>
</div>

<div class="viewer-overlay" id="viewerOverlay"></div>
<div class="viewer-panel" id="viewerPanel">
  <div class="viewer-header">
    <span class="viewer-title" id="viewerTitle">SKILL.md</span>
    <button class="viewer-close" id="viewerClose">X</button>
  </div>
  <div class="viewer-body"><pre id="viewerContent"></pre></div>
</div>

<div class="main" id="content"></div>
<button class="copy-btn" id="copyBtn" style="display:none; position:fixed; bottom:14px; left:24px;">Copy JSON</button>
<!-- ==THEME:FOOTER_HTML== -->
<div class="footer">
  <span>Built by <a href="https://jgwillis.com" target="_blank">Joseph Willis</a></span>
  <span class="footer-sep">|</span>
  <a href="mailto:info@jgwillis.com">info@jgwillis.com</a>
  <span class="footer-sep">|</span>
  <div class="footer-socials">
    <a href="https://instagram.com/aibyjgwillis" target="_blank">
      <svg viewBox="0 0 24 24"><path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z"/></svg>
    </a>
    <a href="https://tiktok.com/@aibyjgwillis" target="_blank">
      <svg viewBox="0 0 24 24"><path d="M19.59 6.69a4.83 4.83 0 01-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 01-2.88 2.5 2.89 2.89 0 01-2.89-2.89 2.89 2.89 0 012.89-2.89c.28 0 .54.04.79.1v-3.5a6.37 6.37 0 00-.79-.05A6.34 6.34 0 003.15 15.2a6.34 6.34 0 0010.86 4.48V13a8.28 8.28 0 005.58 2.15V11.7a4.83 4.83 0 01-3.77-1.24V6.69h3.77z"/></svg>
    </a>
    <a href="https://youtube.com/@aibyjgwillis" target="_blank">
      <svg viewBox="0 0 24 24"><path d="M23.498 6.186a3.016 3.016 0 00-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 00.502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 002.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 002.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>
    </a>
  </div>
  <span class="footer-sep">|</span>
  <div class="footer-waitlist">
    <button class="footer-waitlist-btn" onclick="this.nextElementSibling.classList.toggle('open')">Join Pro Tools Waitlist</button>
    <div class="footer-waitlist-form">
      <label>Get notified at launch</label>
      <input type="email" placeholder="you@email.com" class="footer-waitlist-email">
      <button class="footer-waitlist-submit" onclick="submitWaitlist(this)">Submit</button>
      <span class="footer-waitlist-msg"></span>
    </div>
  </div>
</div>
<!-- ==/THEME:FOOTER_HTML== -->

<script>
const TAG_MAP = {
  downloaded: { label: 'DL', cls: 'created' },
  saved:      { label: 'SAVED', cls: 'created' },
  colored:    { label: 'COLOR', cls: 'created' },
  committed:  { label: 'COMMIT', cls: 'created' },
  deployed:   { label: 'DEPLOY', cls: 'created' },
  built:      { label: 'BUILT', cls: 'created' },
  added:      { label: 'ADDED', cls: 'created' },
  created:    { label: 'NEW', cls: 'created' },
  fixed:      { label: 'FIXED', cls: 'modified' },
  configured: { label: 'CONFIG', cls: 'modified' },
  modified:   { label: 'MOD', cls: 'modified' },
  tested:     { label: 'TEST', cls: 'command' },
  command:    { label: 'CMD', cls: 'command' },
  skipped:    { label: 'SKIP', cls: 'deleted' },
  removed:    { label: 'REMOVED', cls: 'deleted' },
  deleted:    { label: 'DEL', cls: 'deleted' }
};

function escHtml(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

let _emptyRendered = false;
let _loadingRendered = false;

function renderLoading() {
  if (_loadingRendered) return;
  _loadingRendered = true;
  document.getElementById('skillPill').textContent = 'loading';
  const c = document.getElementById('content');
  c.textContent = '';
  const wrap = el('div', 'empty-state');
  wrap.appendChild(el('div', 'empty-title', 'Loading recap...'));
  const sub = el('div', 'empty-text');
  sub.textContent = 'Waiting for skill data.';
  wrap.appendChild(sub);
  c.appendChild(wrap);
}

function renderEmpty() {
  if (_emptyRendered) return;
  _emptyRendered = true;
  _loadingRendered = false;
  document.getElementById('skillPill').textContent = 'waiting';
  const c = document.getElementById('content');
  c.textContent = '';
  const wrap = el('div', 'empty-state');
  wrap.appendChild(el('div', 'empty-title', 'No recap data yet'));
  const sub = el('div', 'empty-text');
  sub.textContent = 'Run a skill, then use /skill-recap to see a visual summary of what happened.';
  wrap.appendChild(sub);
  c.appendChild(wrap);
}

// Show loading immediately
renderLoading();

let _recapData = null;

function formatTimestamp(ts) {
  if (!ts) return null;
  try {
    const d = new Date(ts);
    if (isNaN(d)) return null;
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
      + ' at ' + d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  } catch (e) { return null; }
}

function formatDuration(secs) {
  if (!secs && secs !== 0) return null;
  if (secs < 60) return secs + 's';
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return s > 0 ? m + 'm ' + s + 's' : m + 'm';
}

function groupActions(actions) {
  const order = ['downloaded', 'saved', 'colored', 'committed', 'deployed', 'built', 'added', 'created', 'fixed', 'configured', 'modified', 'tested', 'command', 'skipped', 'removed', 'deleted'];
  const groups = {};
  for (const a of actions) {
    const t = a.type || 'other';
    if (!groups[t]) groups[t] = [];
    groups[t].push(a);
  }
  const sorted = [];
  for (const t of order) { if (groups[t]) sorted.push([t, groups[t]]); }
  for (const t of Object.keys(groups)) { if (!order.includes(t)) sorted.push([t, groups[t]]); }
  return sorted;
}

const GROUP_LABELS = {
  downloaded: 'Downloaded', saved: 'Saved', colored: 'Colored',
  committed: 'Committed', deployed: 'Deployed', built: 'Built',
  added: 'Added', created: 'Created', fixed: 'Fixed',
  configured: 'Configured', modified: 'Modified', tested: 'Tested',
  command: 'Commands', skipped: 'Skipped', removed: 'Removed', deleted: 'Deleted'
};

function renderRecap(d) {
  _recapData = d;
  document.getElementById('skillPill').textContent = d.skill_name || 'unknown';
  document.title = (d.skill_name || 'Skill') + ' | Recap';
  document.getElementById('copyBtn').style.display = '';
  if (d.skill_path) {
    document.getElementById('viewSkillBtn').style.display = '';
    document.getElementById('editSkillBtn').style.display = '';
  }

  const statusCls = d.status === 'success' ? 'success' : d.status === 'partial' ? 'partial' : 'failed';
  const c = document.getElementById('content');
  c.textContent = '';

  // Title
  c.appendChild(el('div', 'page-title', d.skill_name));
  c.appendChild(el('p', 'page-subtitle', 'skill execution recap'));

  // Status + timestamp + duration row
  const statusWrap = el('div', '');
  statusWrap.style.textAlign = 'center';
  statusWrap.appendChild(el('span', 'status-badge ' + statusCls, d.status || 'unknown'));
  c.appendChild(statusWrap);

  // Meta row (timestamp + duration)
  const ts = formatTimestamp(d.timestamp);
  const dur = formatDuration(d.duration_seconds);
  if (ts || dur) {
    const meta = el('div', 'meta-row');
    if (ts) meta.appendChild(document.createTextNode(ts));
    if (ts && dur) meta.appendChild(el('span', 'meta-separator', '|'));
    if (dur) meta.appendChild(document.createTextNode('Completed in ' + dur));
    c.appendChild(meta);
  }

  // Stats row
  const actionCount = d.actions ? d.actions.length : 0;
  const diffCount = d.diffs ? d.diffs.length : 0;
  const warnCount = d.warnings ? d.warnings.length : 0;
  const stepCount = d.next_steps ? d.next_steps.length : 0;
  if (actionCount + diffCount + warnCount + stepCount > 0) {
    const row = el('div', 'stats-row');
    if (actionCount) row.appendChild(el('span', 'stat-pill', actionCount + ' action' + (actionCount !== 1 ? 's' : '')));
    if (diffCount) row.appendChild(el('span', 'stat-pill', diffCount + ' diff' + (diffCount !== 1 ? 's' : '')));
    if (warnCount) row.appendChild(el('span', 'stat-pill has-warnings', warnCount + ' warning' + (warnCount !== 1 ? 's' : '')));
    if (stepCount) row.appendChild(el('span', 'stat-pill', stepCount + ' next step' + (stepCount !== 1 ? 's' : '')));
    c.appendChild(row);
  }

  // Summary
  if (d.summary) {
    c.appendChild(el('div', 'section-label', 'Summary'));
    const card = el('div', 'card');
    card.appendChild(el('div', 'summary-text', d.summary));
    c.appendChild(card);
  }

  // Actions (grouped by type)
  if (d.actions && d.actions.length > 0) {
    c.appendChild(el('div', 'section-label', 'Actions'));
    const card = el('div', 'card');
    const groups = groupActions(d.actions);
    const needsHeaders = groups.length > 1;
    for (const [type, items] of groups) {
      if (needsHeaders) {
        const label = (GROUP_LABELS[type] || type.charAt(0).toUpperCase() + type.slice(1)) + ' (' + items.length + ')';
        card.appendChild(el('div', 'action-group-header', label));
      }
      for (const a of items) {
        const tag = TAG_MAP[a.type] || { label: (a.type || '???').toUpperCase().slice(0,3), cls: 'modified' };
        const item = el('div', 'action-item');
        item.appendChild(el('span', 'action-tag ' + tag.cls, tag.label));
        const info = el('div', '');
        const pathText = a.path || a.cmd || '';
        const pathRow = el('div', 'action-path');
        pathRow.textContent = pathText;
        if (pathText.match(/^[~\/]/)) {
          const openBtn = el('a', 'open-link', 'Open');
          openBtn.addEventListener('click', function(e) {
            e.preventDefault();
            fetch('/api/open', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: pathText }) });
          });
          pathRow.appendChild(openBtn);
        }
        info.appendChild(pathRow);
        if (a.detail) info.appendChild(el('div', 'action-detail', a.detail));
        item.appendChild(info);
        card.appendChild(item);
      }
    }
    c.appendChild(card);
  }

  // Diffs
  if (d.diffs && d.diffs.length > 0) {
    c.appendChild(el('div', 'section-label', 'Changes'));
    const card = el('div', 'card');
    for (const diff of d.diffs) {
      const block = el('div', 'diff-block');
      block.appendChild(el('div', 'diff-file', diff.file));
      const panels = el('div', 'diff-panels');

      const bPanel = el('div', 'diff-panel');
      bPanel.appendChild(el('div', 'diff-panel-label', 'Before'));
      const bPre = el('pre', '');
      renderDiffLines(bPre, diff.before, 'removed');
      bPanel.appendChild(bPre);
      panels.appendChild(bPanel);

      const aPanel = el('div', 'diff-panel');
      aPanel.appendChild(el('div', 'diff-panel-label', 'After'));
      const aPre = el('pre', '');
      renderDiffLines(aPre, diff.after, 'added');
      aPanel.appendChild(aPre);
      panels.appendChild(aPanel);

      block.appendChild(panels);
      card.appendChild(block);
    }
    c.appendChild(card);
  }

  // Warnings
  if (d.warnings && d.warnings.length > 0) {
    c.appendChild(el('div', 'section-label', 'Warnings'));
    const card = el('div', 'card card-amber');
    for (const w of d.warnings) {
      const item = el('div', 'warning-item');
      item.appendChild(el('span', 'warning-icon', '!'));
      item.appendChild(el('span', 'warning-text', w));
      const copyBtn = el('button', 'warning-copy', 'Fix');
      copyBtn.setAttribute('title', 'Copy fix prompt for Claude');
      copyBtn.addEventListener('click', function() {
        const prompt = 'Fix this warning from the "' + d.skill_name + '" skill:\n\n'
          + '> ' + w + '\n\n'
          + 'Investigate the root cause and apply a fix.';
        navigator.clipboard.writeText(prompt).then(() => {
          copyBtn.textContent = 'Paste in Claude';
          copyBtn.classList.add('copied');
          copyBtn.removeAttribute('title');
          setTimeout(() => {
            copyBtn.textContent = 'Fix';
            copyBtn.classList.remove('copied');
            copyBtn.setAttribute('title', 'Copy fix prompt for Claude');
          }, 2500);
        });
      });
      item.appendChild(copyBtn);
      card.appendChild(item);
    }
    c.appendChild(card);
  }

  // Next steps
  if (d.next_steps && d.next_steps.length > 0) {
    c.appendChild(el('div', 'section-label', 'Next Steps'));
    const card = el('div', 'card card-champagne');
    d.next_steps.forEach((s, i) => {
      const item = el('div', 'step-item');
      item.appendChild(el('span', 'step-num', (i + 1) + '.'));
      item.appendChild(el('span', 'step-text', s));
      card.appendChild(item);
    });
    c.appendChild(card);
  }
}

// Copy JSON button
document.getElementById('copyBtn').addEventListener('click', function() {
  if (!_recapData) return;
  const btn = this;
  navigator.clipboard.writeText(JSON.stringify(_recapData, null, 2)).then(() => {
    btn.textContent = 'Copied';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = 'Copy JSON'; btn.classList.remove('copied'); }, 1500);
  });
});

function renderDiffLines(pre, text, type) {
  if (!text) return;
  const lines = text.split('\n');
  lines.forEach((line, i) => {
    const span = el('span', 'diff-line-' + type, line);
    pre.appendChild(span);
    if (i < lines.length - 1) pre.appendChild(document.createTextNode('\n'));
  });
}

// Fetch recap data on load
async function loadRecap() {
  try {
    const res = await fetch('/api/recap');
    const data = await res.json();
    if (data.empty) {
      renderEmpty();
      setTimeout(loadRecap, 2000);
    } else {
      renderRecap(data);
    }
  } catch (e) {
    renderEmpty();
    setTimeout(loadRecap, 2000);
  }
}

loadRecap();

// Viewer panel
const viewerOverlay = document.getElementById('viewerOverlay');
const viewerPanel = document.getElementById('viewerPanel');
function openViewer() { viewerOverlay.classList.add('open'); viewerPanel.classList.add('open'); }
function closeViewer() { viewerOverlay.classList.remove('open'); viewerPanel.classList.remove('open'); }
document.getElementById('viewerClose').addEventListener('click', closeViewer);
viewerOverlay.addEventListener('click', closeViewer);

// View Skill button
document.getElementById('viewSkillBtn').addEventListener('click', function() {
  if (!_recapData || !_recapData.skill_path) return;
  fetch('/api/read-file', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: _recapData.skill_path }) })
    .then(r => r.json())
    .then(d => {
      if (d.ok) {
        document.getElementById('viewerTitle').textContent = _recapData.skill_path.split('/').pop();
        document.getElementById('viewerContent').textContent = d.content;
        openViewer();
      }
    });
});

// Edit Skill button
document.getElementById('editSkillBtn').addEventListener('click', function() {
  if (!_recapData) return;
  const name = _recapData.skill_name || 'this skill';
  const path = _recapData.skill_path || '';
  const prompt = 'I want to edit the "' + name + '" skill'
    + (path ? ' at ' + path : '') + '.\n\n'
    + 'Walk me through what it currently does and what changes I can make.';
  const btn = this;
  navigator.clipboard.writeText(prompt).then(() => {
    btn.textContent = 'Paste in Claude';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = 'Edit Skill'; btn.classList.remove('copied'); }, 2500);
  });
});

// Heartbeat
setInterval(() => { fetch('/api/heartbeat').catch(() => {}); }, 4000);
</script>
</body>
</html>"""


# -- Main --------------------------------------------------------------------

if __name__ == "__main__":
    run_preflight()
    server = ThreadedHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Server running at http://localhost:{PORT}")
    print("Server will stop automatically when you close the browser tab.\n")

    def heartbeat_watchdog():
        """Shut down the server when the browser tab is closed."""
        _time.sleep(15)  # grace period for initial page load
        while True:
            _time.sleep(3)
            if _time.time() - _last_heartbeat > _heartbeat_timeout:
                print("\nBrowser tab closed. Shutting down.")
                server.shutdown()
                return

    watchdog = threading.Thread(target=heartbeat_watchdog, daemon=True)
    watchdog.start()
    threading.Timer(0.5, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    server.server_close()
