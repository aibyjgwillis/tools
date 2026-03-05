#!/usr/bin/env python3
"""Rapid Download - Bulk image collection from Google Images.

Run: python3 rapid-download.py
Opens a browser-based picker UI on localhost:9849.

NOTE: This is a local-only tool. All HTML rendering uses data from the
local filesystem only. No external/untrusted input is processed.
All rendered text is escaped via textContent-based JS before insertion.
"""

import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time as _time
import urllib.parse
import webbrowser
from io import BytesIO
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

VERSION = "1.0"
PORT = 9849

DOWNLOADS = str(Path.home() / "Downloads")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_DIR = os.path.join(SCRIPT_DIR, "session")
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp'}

# Heartbeat: track last ping from browser, auto-shutdown when tab closes
_last_heartbeat = _time.time() + 30  # 30s grace period for browser to open
_heartbeat_timeout = 10

# Server state
_output_dir = [None]
_watch_baseline = [0.0]
_thumb_map = {}
_full_urls = []
_next_url = [None]
_skip_flag = [False]
_current_idx = [0]
_items_list = []


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
    check("requests library", lambda: requests is not None)

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
    check("Downloads dir", lambda: os.path.isdir(DOWNLOADS))

    print(f"\nRapid Download v{VERSION}")
    all_ok = True
    for name, ok in checks:
        dots = "." * (24 - len(name))
        status = "ok" if ok else "FAIL"
        print(f"  {name} {dots} {status}")
        if not ok:
            all_ok = False

    if not all_ok:
        print("\nSome checks failed. The server will start, but some features may not work.\n")
    else:
        print()

    return all_ok


def get_output_dir():
    if _output_dir[0]:
        return _output_dir[0]
    return os.path.join(DOWNLOADS, "rapid-download")


def latest_image_in_downloads():
    best = None
    best_mtime = 0
    baseline = _watch_baseline[0]
    for f in os.listdir(DOWNLOADS):
        if f.startswith('.'):
            continue
        ext = os.path.splitext(f)[1].lower()
        if ext not in IMAGE_EXTS:
            continue
        full = os.path.join(DOWNLOADS, f)
        if not os.path.isfile(full):
            continue
        mt = os.path.getmtime(full)
        if mt <= baseline:
            continue
        if mt > best_mtime:
            best_mtime = mt
            best = full
    return best


def safe_filename(name):
    s = re.sub(r'[^\w\s-]', '', name.lower())
    s = re.sub(r'[\s]+', '_', s.strip())
    return s or 'item'


# ── HTML Template ─────────────────────────────────────────────────────────────

def get_picker_html():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Rapid Download</title>
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

body {
  display: flex; flex-direction: column; align-items: center;
}

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

.topbar-progress {
  font-family: var(--font-mono); font-size: 12px;
  color: var(--champagne); font-weight: 500;
}

.path-bar {
  width: 100%; padding: 12px 20px;
  display: flex; align-items: center; gap: 8px;
  border-bottom: 1px solid rgba(28,28,30,0.06);
}
.path-bar label {
  color: rgba(28,28,30,0.5); font-family: var(--font-mono);
  font-size: 10px; text-transform: uppercase; letter-spacing: 0.12em; white-space: nowrap;
}
.path-bar input {
  flex: 1; background: rgba(28,28,30,0.04);
  border: 1px solid rgba(28,28,30,0.1);
  color: var(--slate); padding: 7px 12px; border-radius: 8px;
  font-family: var(--font-mono); font-size: 12px;
  outline: none; min-width: 0; transition: border-color 0.25s;
}
.path-bar input:focus { border-color: var(--champagne); }
.path-bar button {
  background: var(--slate); border: none; color: var(--ivory);
  padding: 7px 16px; border-radius: 8px;
  font-family: var(--font-heading); font-size: 12px; font-weight: 500;
  cursor: pointer; transition: all 0.3s cubic-bezier(0.25,0.46,0.45,0.94);
}
.path-bar button:hover { transform: scale(1.03); opacity: 0.85; }
.path-status { font-family: var(--font-mono); font-size: 11px; min-width: 50px; }

.screen {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; padding: 48px 36px 60px;
  width: 100%; max-width: 640px;
}
.screen.hidden { display: none; }

/* ==THEME:BUTTONS== */
.btn {
  font-family: var(--font-heading); font-size: 13px; font-weight: 500;
  padding: 10px 20px; border-radius: 8px; border: 1px solid transparent;
  cursor: pointer; transition: all 0.2s;
}
.btn-primary { background: var(--slate); color: var(--ivory); }
.btn-primary:hover { background: var(--obsidian); }
.btn-secondary { background: white; border-color: rgba(28,28,30,0.15); color: var(--champagne); }
.btn-secondary:hover { border-color: rgba(28,28,30,0.45); color: var(--slate); }
/* ==/THEME:BUTTONS== */

.btn { padding: 13px 32px; border-radius: 2rem; font-size: 13px; font-weight: 600; letter-spacing: 0.02em; }
.btn:hover { transform: scale(1.03); }
.btn-small { padding: 6px 14px; font-size: 11px; border-radius: 6px; }

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

.review-title {
  font-family: var(--font-drama); font-size: 42px;
  font-style: italic; font-weight: 400;
  margin-bottom: 6px; text-align: center;
}
.review-subtitle {
  font-family: var(--font-mono); font-size: 12px;
  color: var(--champagne); text-align: center; margin-bottom: 32px;
}

.edit-list {
  width: 100%; border: 1px solid rgba(28,28,30,0.08);
  border-radius: 1.5rem; overflow: hidden; background: white;
  margin-bottom: 20px;
}
.edit-row {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 16px; border-bottom: 1px solid rgba(28,28,30,0.05);
  transition: background 0.15s;
}
.edit-row:last-child { border-bottom: none; }
.edit-row:hover { background: rgba(28,28,30,0.02); }
.edit-row .row-num {
  font-family: var(--font-mono); font-size: 10px;
  color: rgba(28,28,30,0.3); min-width: 20px; text-align: right;
}
.edit-row .row-fields { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.edit-row .row-name {
  font-size: 14px; font-weight: 500; color: var(--slate);
  background: none; border: none; outline: none; width: 100%;
  font-family: var(--font-heading); padding: 2px 0;
}
.edit-row .row-query {
  font-family: var(--font-mono); font-size: 11px;
  color: var(--champagne); background: none; border: none;
  outline: none; width: 100%; padding: 2px 0;
}
.edit-row .row-name:focus, .edit-row .row-query:focus {
  background: rgba(28,28,30,0.03); border-radius: 4px;
}
.edit-row .row-remove {
  background: none; border: none; cursor: pointer;
  color: rgba(28,28,30,0.2); font-size: 16px; padding: 4px 8px;
  transition: color 0.15s; line-height: 1;
}
.edit-row .row-remove:hover { color: var(--red); }

.add-area {
  width: 100%; display: flex; gap: 8px; margin-bottom: 12px;
}
.add-area input {
  flex: 1; background: rgba(28,28,30,0.04);
  border: 1px solid rgba(28,28,30,0.1);
  color: var(--slate); padding: 9px 14px; border-radius: 8px;
  font-family: var(--font-heading); font-size: 13px; outline: none;
  transition: border-color 0.25s;
}
.add-area input:focus { border-color: var(--champagne); }
.add-area input::placeholder { color: rgba(28,28,30,0.3); }

.upload-area { width: 100%; margin-bottom: 24px; text-align: center; }
.upload-zone {
  border: 2px dashed rgba(28,28,30,0.12);
  border-radius: 1rem; padding: 20px; cursor: pointer;
  transition: all 0.2s; color: rgba(28,28,30,0.4);
  font-family: var(--font-mono); font-size: 12px;
}
.upload-zone:hover { border-color: var(--champagne); color: var(--champagne); }
.upload-zone.dragover { border-color: var(--champagne); background: rgba(90,125,150,0.05); }

.review-actions { display: flex; gap: 14px; margin-top: 8px; }

.active-status { text-align: center; padding: 24px 0; }
.active-status .current-item {
  font-family: var(--font-drama); font-size: 28px;
  font-style: italic; margin-bottom: 8px;
}
.active-status .status-text {
  font-family: var(--font-mono); font-size: 12px;
  color: var(--champagne); margin-bottom: 4px;
}
.active-status .status-text::before {
  content: ''; display: inline-block; width: 6px; height: 6px;
  background: var(--champagne); border-radius: 50%;
  margin-right: 8px; animation: pulse-dot 2s ease-in-out infinite;
}
@keyframes pulse-dot {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.4); }
}
.active-status .saved-text {
  font-family: var(--font-mono); font-size: 12px; color: var(--green);
}
.active-status.hidden { display: none; }

.progress-list {
  width: 100%; border: 1px solid rgba(28,28,30,0.08);
  border-radius: 1.5rem; overflow: hidden; background: white;
  margin-top: 20px; max-height: 300px; overflow-y: auto;
}
.progress-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 24px 10px 16px; font-size: 13px;
  border-bottom: 1px solid rgba(28,28,30,0.05);
}
.progress-row .status { flex-shrink: 0; margin-left: 12px; }
.progress-row:last-child { border-bottom: none; }
.progress-row .name { font-weight: 500; }
.progress-row .status {
  font-family: var(--font-mono); font-size: 10px;
  text-transform: uppercase; letter-spacing: 0.08em;
}
.progress-row .status.saved { color: var(--green); }
.progress-row .status.skipped { color: rgba(28,28,30,0.4); }
.progress-row .status.pending { color: rgba(28,28,30,0.2); }
.progress-row .status.current { color: var(--champagne); font-weight: 500; }
.progress-row.current-row { background: rgba(90,125,150,0.05); }

.end-title {
  font-family: var(--font-drama); font-size: 42px;
  font-style: italic; margin-bottom: 6px; text-align: center;
}
.end-subtitle {
  font-family: var(--font-mono); font-size: 12px;
  color: var(--champagne); text-align: center; margin-bottom: 32px;
}
.end-path {
  font-family: var(--font-mono); font-size: 11px;
  color: rgba(28,28,30,0.45); text-align: center; margin-top: 20px;
  cursor: pointer;
}
.end-path:hover { color: var(--obsidian); text-decoration: underline; }
.end-actions {
  display: flex; justify-content: center; gap: 12px; margin-top: 24px;
}

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

/* ==THEME:FADEIN== */
@keyframes fadeUp { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
/* ==/THEME:FADEIN== */

.fade-in > * { animation: fadeUp 0.45s ease-out both; }
.fade-in > *:nth-child(1) { animation-delay: 0.05s; }
.fade-in > *:nth-child(2) { animation-delay: 0.12s; }
.fade-in > *:nth-child(3) { animation-delay: 0.19s; }
.fade-in > *:nth-child(4) { animation-delay: 0.26s; }
.fade-in > *:nth-child(5) { animation-delay: 0.33s; }
.fade-in > *:nth-child(6) { animation-delay: 0.40s; }
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
  <div class="topbar-brand">Rapid Download</div>
  <div class="topbar-progress" id="progress"></div>
</div>

<div class="path-bar">
  <label>Save to</label>
  <input id="output-input" type="text" spellcheck="false">
  <button onclick="browseFolder()">Browse...</button>
  <span class="path-status" id="path-status"></span>
</div>

<!-- REVIEW SCREEN -->
<div class="screen fade-in" id="review-screen">
  <div class="review-title">Review Items</div>
  <div class="review-subtitle" id="review-count"></div>
  <div class="edit-list" id="edit-list"></div>
  <div class="add-area">
    <input type="text" id="add-input" placeholder="Add items (comma-separated)..." spellcheck="false">
    <button class="btn btn-secondary btn-small" onclick="addItem()">Add</button>
  </div>
  <div class="upload-area">
    <div class="upload-zone" id="upload-zone">Drop a CSV or text file here, or click to upload</div>
    <input type="file" id="file-input" accept=".csv,.txt,.tsv" style="display:none">
  </div>
  <div class="review-actions">
    <button class="btn btn-secondary" onclick="clearList()">Clear List</button>
    <button class="btn btn-primary" onclick="startDownloading()">Start Downloading</button>
  </div>
</div>

<!-- DOWNLOADING SCREEN -->
<div class="screen fade-in hidden" id="downloading-screen">
  <div class="active-status" id="active-status">
    <div class="current-item" id="current-item-name"></div>
    <div class="status-text" id="status-text">Waiting for image...</div>
  </div>
  <div class="progress-list" id="progress-list"></div>
</div>

<!-- END SCREEN -->
<div class="screen fade-in hidden" id="end-screen">
  <div class="end-title">Complete</div>
  <div class="end-subtitle" id="summary-stats"></div>
  <div class="progress-list" id="result-list"></div>
  <div class="end-path" id="output-path" onclick="openOutputFolder()"></div>
  <div class="end-actions">
    <button class="btn btn-primary" onclick="openOutputFolder()">Open Folder</button>
    <button class="btn btn-secondary" onclick="clearAndRestart()">Start Over</button>
  </div>
</div>

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
let items = [];
let currentIdx = 0;
let picks = [];
let searchWindow = null;
let watchInterval = null;

const _bc = new BroadcastChannel('rapid-download');
_bc.onmessage = () => { checkStatus(); };
let outputDir = 'Downloads/rapid-download';

/* ==THEME:HEARTBEAT== */
setInterval(() => { fetch('/api/heartbeat').catch(() => {}); }, 4000);
/* ==/THEME:HEARTBEAT== */

// ===== REVIEW =====

function renderEditList() {
  const list = document.getElementById('edit-list');
  list.textContent = '';
  document.getElementById('review-count').textContent = items.length + ' items';
  items.forEach((item, i) => {
    const row = document.createElement('div');
    row.className = 'edit-row';

    const num = document.createElement('span');
    num.className = 'row-num';
    num.textContent = (i + 1).toString();

    const fields = document.createElement('div');
    fields.className = 'row-fields';

    const nameInput = document.createElement('input');
    nameInput.className = 'row-name';
    nameInput.value = item.name;
    nameInput.addEventListener('change', () => {
      items[i].name = nameInput.value;
      if (!item._queryEdited) {
        items[i].query = nameInput.value;
        queryInput.value = nameInput.value;
      }
      items[i].safeName = makeSafeName(nameInput.value);
    });

    const queryInput = document.createElement('input');
    queryInput.className = 'row-query';
    queryInput.value = item.query || item.name;
    queryInput.placeholder = 'Search query';
    queryInput.addEventListener('change', () => {
      items[i].query = queryInput.value;
      items[i]._queryEdited = true;
    });

    fields.appendChild(nameInput);
    fields.appendChild(queryInput);

    const removeBtn = document.createElement('button');
    removeBtn.className = 'row-remove';
    removeBtn.textContent = '\\u00D7';
    removeBtn.addEventListener('click', () => { items.splice(i, 1); renderEditList(); });

    row.appendChild(num);
    row.appendChild(fields);
    row.appendChild(removeBtn);
    list.appendChild(row);
  });
}

function addItem() {
  const input = document.getElementById('add-input');
  const val = input.value.trim();
  if (!val) return;
  const names = val.split(/[,\\n]/).map(s => s.trim()).filter(Boolean);
  for (const name of names) {
    items.push({ name, query: name, safeName: makeSafeName(name) });
  }
  input.value = '';
  renderEditList();
}

function parseFileContent(text, filename) {
  const ext = filename.split('.').pop().toLowerCase();
  const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
  const newItems = [];
  for (const line of lines) {
    let parts;
    if (ext === 'csv' || ext === 'tsv') {
      parts = ext === 'tsv' ? line.split('\\t') : line.split(',');
    } else {
      parts = [line];
    }
    const name = (parts[0] || '').trim().replace(/^["']|["']$/g, '');
    if (!name) continue;
    if (newItems.length === 0 && /^(name|item|company|brand)/i.test(name)) continue;
    const query = (parts[1] || '').trim().replace(/^["']|["']$/g, '') || name;
    newItems.push({ name, query, safeName: makeSafeName(name) });
  }
  return newItems;
}

const uploadZone = document.getElementById('upload-zone');
const fileInput = document.getElementById('file-input');
uploadZone.addEventListener('click', () => fileInput.click());
uploadZone.addEventListener('dragover', (e) => { e.preventDefault(); uploadZone.classList.add('dragover'); });
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('dragover'));
uploadZone.addEventListener('drop', (e) => {
  e.preventDefault(); uploadZone.classList.remove('dragover');
  if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => { if (fileInput.files[0]) handleFile(fileInput.files[0]); });

function handleFile(file) {
  const reader = new FileReader();
  reader.onload = () => {
    const newItems = parseFileContent(reader.result, file.name);
    if (newItems.length) {
      items = items.concat(newItems);
      renderEditList();
      uploadZone.textContent = 'Added ' + newItems.length + ' items from ' + file.name;
      setTimeout(() => { uploadZone.textContent = 'Drop a CSV or text file here, or click to upload'; }, 3000);
    }
  };
  reader.readAsText(file);
}

document.getElementById('add-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); addItem(); }
  e.stopPropagation();
});

// ===== DOWNLOADING =====

function startDownloading() {
  if (!items.length) return;
  fetch('/api/save-items', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(items)
  }).catch(() => {});

  document.getElementById('review-screen').classList.add('hidden');
  document.getElementById('downloading-screen').classList.remove('hidden');

  renderProgressList();
  openGoogleForCurrent();
  startStatusPoller();
}

function renderProgressList() {
  const list = document.getElementById('progress-list');
  list.textContent = '';
  items.forEach((item, i) => {
    const row = document.createElement('div');
    row.className = 'progress-row' + (i === currentIdx ? ' current-row' : '');
    row.id = 'prog-' + i;

    const nameSpan = document.createElement('span');
    nameSpan.className = 'name';
    nameSpan.textContent = item.name;

    const statusSpan = document.createElement('span');
    statusSpan.className = 'status';
    const pick = picks.find(p => p.safeName === (item.safeName || makeSafeName(item.name)));
    if (pick) {
      statusSpan.textContent = pick.status === 'saved' ? 'Saved' : 'Skipped';
      statusSpan.classList.add(pick.status);
    } else if (i === currentIdx) {
      statusSpan.textContent = 'Current';
      statusSpan.classList.add('current');
    } else {
      statusSpan.textContent = 'Pending';
      statusSpan.classList.add('pending');
    }

    row.appendChild(nameSpan);
    row.appendChild(statusSpan);
    list.appendChild(row);
  });
}

function openGoogleForCurrent() {
  if (currentIdx >= items.length) { showEndScreen(); return; }

  const item = items[currentIdx];
  const query = item.query || item.name;
  const safeName = item.safeName || makeSafeName(item.name);

  document.getElementById('progress').textContent = (currentIdx + 1) + ' of ' + items.length;
  document.getElementById('current-item-name').textContent = item.name;
  document.getElementById('status-text').textContent = 'Waiting for image...';
  document.getElementById('status-text').className = 'status-text';

  const url = '/api/google-images?q=' + encodeURIComponent(query)
    + '&name=' + encodeURIComponent(safeName)
    + '&item=' + encodeURIComponent(item.name);

  console.log('[PICKER] openGoogleForCurrent idx=' + currentIdx + ' url=' + url);
  fetch('/api/set-next-url', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: url })
  });

  if (!searchWindow || searchWindow.closed) {
    searchWindow = window.open(url, 'rapid_search', 'width=1200,height=800');
  }
  resetBaseline().then(() => startWatching());
}

window.skipFromGoogle = function() { skipCurrent(); };

window.advanceFromGoogle = function() {
  stopWatching();
  const item = items[currentIdx];
  if (!item) return;
  const safeName = item.safeName || makeSafeName(item.name);

  (async () => {
    await new Promise(r => setTimeout(r, 500));
    const resp = await fetch('/api/latest-download');
    const data = await resp.json();
    if (data.file && data.is_image) {
      await fetch('/api/latest-download?consumed=' + encodeURIComponent(data.file));
      const saveResp = await fetch('/api/save-image', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: data.file, safeName: safeName })
      });
      const saveData = await saveResp.json();
      picks.push({ name: item.name, safeName: safeName, status: 'saved', file: saveData.saved });
    } else {
      picks.push({ name: item.name, safeName: safeName, status: 'saved' });
    }
    document.getElementById('status-text').textContent = 'Saved ' + safeName;
    document.getElementById('status-text').className = 'saved-text';
    currentIdx++;
    renderProgressList();
    openGoogleForCurrent();
  })();
};

function skipCurrent() {
  stopWatching();
  const item = items[currentIdx];
  picks.push({ name: item.name, safeName: item.safeName || makeSafeName(item.name), status: 'skipped' });
  currentIdx++;
  renderProgressList();
  openGoogleForCurrent();
}

async function resetBaseline() {
  try { await fetch('/api/latest-download?reset=1'); } catch(e) {}
}

function stopWatching() {
  if (watchInterval) { clearInterval(watchInterval); watchInterval = null; }
}

function startWatching() {
  stopWatching();
  watchInterval = setInterval(async () => {
    if (currentIdx >= items.length) { stopWatching(); return; }
    try {
      const sigResp = await fetch('/api/check-skip');
      const sigData = await sigResp.json();
      if (sigData.skip) { skipCurrent(); return; }

      const resp = await fetch('/api/latest-download');
      const data = await resp.json();
      if (data.file && data.is_image) {
        await fetch('/api/latest-download?consumed=' + encodeURIComponent(data.file));
        stopWatching();

        const item = items[currentIdx];
        const safeName = item.safeName || makeSafeName(item.name);

        const saveResp = await fetch('/api/save-image', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source: data.file, safeName: safeName })
        });
        const saveData = await saveResp.json();

        document.getElementById('status-text').textContent = 'Saved ' + safeName;
        document.getElementById('status-text').className = 'saved-text';

        picks.push({ name: item.name, safeName: safeName, status: 'saved', file: saveData.saved });
        currentIdx++;
        console.log('[PICKER] watcher saved, advancing to idx=' + currentIdx);
        renderProgressList();
        openGoogleForCurrent();
      }
    } catch(e) {}
  }, 800);
}

function makeSafeName(name) {
  return name.toLowerCase().replace(/[^\\w\\s-]/g, '').replace(/[\\s]+/g, '_').trim() || 'item';
}

// ===== END =====

function showEndScreen() {
  stopWatching();
  if (searchWindow && !searchWindow.closed) { searchWindow.close(); searchWindow = null; }

  document.getElementById('downloading-screen').classList.add('hidden');
  document.getElementById('end-screen').classList.remove('hidden');

  const saved = picks.filter(p => p.status === 'saved').length;
  const skipped = picks.filter(p => p.status === 'skipped').length;
  document.getElementById('summary-stats').textContent = saved + ' saved, ' + skipped + ' skipped';

  const listEl = document.getElementById('result-list');
  for (const p of picks) {
    const row = document.createElement('div');
    row.className = 'progress-row';
    const nameSpan = document.createElement('span');
    nameSpan.className = 'name';
    nameSpan.textContent = p.name;
    const statusSpan = document.createElement('span');
    statusSpan.className = 'status ' + p.status;
    statusSpan.textContent = p.status === 'saved' ? 'Saved' : 'Skipped';
    row.appendChild(nameSpan);
    row.appendChild(statusSpan);
    listEl.appendChild(row);
  }

  document.getElementById('output-path').textContent = outputDir;

  fetch('/api/save-picks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(picks)
  }).catch(() => {});
}

function openOutputFolder() {
  fetch('/api/open-folder').catch(() => {});
}

function clearAndRestart() {
  items = [];
  picks = [];
  currentIdx = 0;
  document.getElementById('end-screen').classList.add('hidden');
  document.getElementById('result-list').replaceChildren();
  document.getElementById('review-screen').classList.remove('hidden');
  renderEditList();
  document.getElementById('review-count').textContent = 'No items yet. Add some below.';
}

function clearList() {
  items = [];
  renderEditList();
  document.getElementById('review-count').textContent = 'No items yet. Add some below.';
}

async function checkStatus() {
  try {
    const resp = await fetch('/api/status');
    const data = await resp.json();
    while (picks.length < data.currentIdx && picks.length < items.length) {
      const item = items[picks.length];
      picks.push({ name: item.name, safeName: item.safeName || makeSafeName(item.name), status: 'saved' });
    }
    currentIdx = data.currentIdx;
    renderProgressList();
    if (data.done) {
      showEndScreen();
      return true;
    }
  } catch(e) {}
  return false;
}

function startStatusPoller() {
  const poller = setInterval(async () => {
    const done = await checkStatus();
    if (done) clearInterval(poller);
  }, 1000);

  const onFocus = async () => {
    const done = await checkStatus();
    if (done) {
      document.removeEventListener('visibilitychange', onVisChange);
      window.removeEventListener('focus', onFocus);
    }
  };
  const onVisChange = () => { if (!document.hidden) onFocus(); };
  window.addEventListener('focus', onFocus);
  document.addEventListener('visibilitychange', onVisChange);

  const closeCheck = setInterval(() => {
    if (searchWindow && searchWindow.closed) {
      clearInterval(closeCheck);
      checkStatus();
    }
  }, 500);
}

// ===== PATH =====

document.getElementById('output-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); updateOutputDir(); }
  e.stopPropagation();
});

async function browseFolder() {
  const ps = document.getElementById('path-status');
  ps.textContent = 'Opening...'; ps.style.color = 'var(--champagne)';
  try {
    const resp = await fetch('/api/browse-folder');
    const data = await resp.json();
    if (data.path) {
      document.getElementById('output-input').value = data.path;
      outputDir = data.path;
      ps.textContent = 'Updated'; ps.style.color = 'var(--green)';
    } else { ps.textContent = 'Cancelled'; ps.style.color = 'rgba(28,28,30,0.3)'; }
  } catch(e) { ps.textContent = 'Error'; ps.style.color = 'var(--red)'; }
  setTimeout(() => { ps.textContent = ''; }, 2000);
}

async function updateOutputDir() {
  const newDir = document.getElementById('output-input').value.trim();
  if (!newDir) return;
  const ps = document.getElementById('path-status');
  try {
    const resp = await fetch('/api/set-output-dir', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ outputDir: newDir })
    });
    const data = await resp.json();
    outputDir = data.outputDir;
    document.getElementById('output-input').value = outputDir;
    ps.textContent = 'Updated'; ps.style.color = 'var(--green)';
  } catch(e) { ps.textContent = 'Error'; ps.style.color = 'var(--red)'; }
  setTimeout(() => { ps.textContent = ''; }, 2000);
}

// ===== INIT =====

async function init() {
  try {
    const resp = await fetch('/api/items');
    const data = await resp.json();
    items = data.items || [];
    outputDir = data.outputDir || outputDir;
    document.getElementById('output-input').value = outputDir;
  } catch(e) {}

  renderEditList();
  if (!items.length) {
    document.getElementById('review-count').textContent = 'No items yet. Add some below.';
  }
}

init();
</script>
</body>
</html>"""


# ── Injected Google Images JS ─────────────────────────────────────────────────

def get_google_inject_js(save_name, item_name):
    """Return the JavaScript to inject into the proxied Google Images page."""
    safe_save = save_name.replace("'", "\\'")
    safe_item = item_name.replace("'", "\\'").replace("\\", "\\\\")
    return """<script>
window._savePrefix='""" + safe_save + """';
document.addEventListener('click',function(e){
if(e.target.closest('#rd-bar'))return;
e.preventDefault();e.stopPropagation();
var img=e.target;
if(img.tagName!=='IMG'){img=img.closest('img')||img.querySelector('img')}
if(!img||!img.src)return;
console.log('[RD] clicked: '+img.src.substring(0,60));
var hintEl=document.getElementById('rd-hint');
if(hintEl){hintEl.textContent='Saving...';hintEl.style.color='#F5F5F3';hintEl.style.fontWeight='600'}
var c=document.createElement('canvas');
c.width=img.naturalWidth||img.width;
c.height=img.naturalHeight||img.height;
var ctx=c.getContext('2d');
ctx.drawImage(img,0,0);
c.toBlob(function(blob){
if(!blob){if(hintEl)hintEl.textContent='Failed. Click another image.';return}
var fd=new FormData();
fd.append('image',blob,window._savePrefix+'.png');
fd.append('name',window._savePrefix);
fetch('/api/save-image-data',{method:'POST',body:fd}).then(function(r){return r.json()}).then(function(d){
console.log('[RD] saved: '+JSON.stringify(d));
var bar=document.getElementById('rd-bar');
if(bar){bar.style.background='#3a7d5c';bar.style.transition='background 0.3s ease'}
if(hintEl){hintEl.textContent='Saved! Loading next...';hintEl.style.color='#F5F5F3';hintEl.style.fontWeight='600';hintEl.style.fontSize='14px'}
fetch('/api/advance',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'save'})}).then(function(r){return r.json()}).then(function(nd){
try{new BroadcastChannel('rapid-download').postMessage('update')}catch(e){}
if(nd.done){if(hintEl)hintEl.textContent='All done! Closing...';setTimeout(function(){window.close()},1200);return}
setTimeout(function(){window.location.href=nd.url},1000);
});
}).catch(function(e){
console.log('[RD] save error: '+e);
if(hintEl){hintEl.textContent='Error. Click another image.';hintEl.style.color='#c44'}
});
},'image/png');
},true);
var b=document.createElement('div');b.id='rd-bar';
b.style.cssText='position:fixed;top:0;left:0;right:0;background:#1C1C1E;color:#F5F5F3;padding:0;font:14px -apple-system,sans-serif;z-index:99999;display:flex;align-items:center;justify-content:space-between;box-shadow:0 2px 12px rgba(0,0,0,0.3)';
var left=document.createElement('div');
left.style.cssText='display:flex;align-items:center;gap:12px;padding:12px 20px';
var label=document.createElement('span');label.textContent='""" + safe_item + """';
label.style.cssText='font-weight:600;font-size:15px';
left.appendChild(label);
var hint=document.createElement('span');hint.id='rd-hint';hint.textContent='Click any image to save';
hint.style.cssText='color:rgba(245,245,243,0.5);font-size:12px;transition:color 0.3s ease';
left.appendChild(hint);
b.appendChild(left);
var right=document.createElement('div');
right.style.cssText='display:flex;align-items:center;gap:8px;padding:12px 20px';
var skipBtn=document.createElement('button');
skipBtn.textContent='Skip';
skipBtn.style.cssText='background:transparent;border:1px solid rgba(245,245,243,0.25);color:rgba(245,245,243,0.7);padding:6px 18px;border-radius:20px;font:13px -apple-system,sans-serif;cursor:pointer;font-weight:500';
skipBtn.onmouseover=function(){this.style.borderColor='rgba(245,245,243,0.5)';this.style.color='#F5F5F3'};
skipBtn.onmouseout=function(){this.style.borderColor='rgba(245,245,243,0.25)';this.style.color='rgba(245,245,243,0.7)'};
skipBtn.onclick=function(ev){ev.preventDefault();ev.stopPropagation();
skipBtn.textContent='Skipping...';
fetch('/api/advance',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'skip'})}).then(function(r){return r.json()}).then(function(nd){
try{new BroadcastChannel('rapid-download').postMessage('update')}catch(e){}
if(nd.done){if(document.getElementById('rd-hint'))document.getElementById('rd-hint').textContent='All done!';return}
window.location.href=nd.url;
});
};
right.appendChild(skipBtn);
b.appendChild(right);
document.body.style.marginTop='48px';
document.body.appendChild(b);
</script>"""


# ── HTTP Handler ──────────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        global _last_heartbeat
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == '/' or parsed.path == '/index.html':
            html = get_picker_html()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
            return

        if parsed.path == '/api/heartbeat':
            _last_heartbeat = _time.time()
            self._json_response({'ok': True})
            return

        if parsed.path == '/api/items':
            items_path = os.path.join(SESSION_DIR, 'items.json')
            if os.path.isfile(items_path):
                with open(items_path) as f:
                    data = json.load(f)
            else:
                data = []
            if isinstance(data, dict):
                if data.get('outputDir'):
                    _output_dir[0] = os.path.expanduser(data['outputDir'])
                items_list = data.get('items', [])
            else:
                items_list = data
            _items_list.clear()
            _items_list.extend(items_list)
            _current_idx[0] = 0
            self._json_response({'items': items_list, 'outputDir': get_output_dir()})
            return

        if parsed.path == '/api/latest-download':
            qs = urllib.parse.parse_qs(parsed.query)
            if 'reset' in qs:
                _watch_baseline[0] = _time.time()
            if 'consumed' in qs:
                consumed_path = qs['consumed'][0]
                if os.path.isfile(consumed_path):
                    _watch_baseline[0] = os.path.getmtime(consumed_path)
            latest = latest_image_in_downloads()
            self._json_response({
                'file': latest,
                'filename': os.path.basename(latest) if latest else None,
                'is_image': latest is not None,
            })
            return

        if parsed.path == '/api/download-file':
            qs = urllib.parse.parse_qs(parsed.query)
            path = qs.get('path', [''])[0]
            if path and os.path.isfile(path) and path.startswith(DOWNLOADS):
                ext = os.path.splitext(path)[1].lower()
                ct = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                      '.gif': 'image/gif', '.webp': 'image/webp'}.get(ext, 'application/octet-stream')
                self.send_response(200)
                self.send_header('Content-Type', ct)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                with open(path, 'rb') as f:
                    self.wfile.write(f.read())
                return
            self.send_error(404)
            return

        if parsed.path == '/api/browse-folder':
            script = (
                'set chosenFolder to choose folder with prompt "Select output folder"\n'
                'return POSIX path of chosenFolder'
            )
            try:
                result = subprocess.run(
                    ['osascript', '-e', script],
                    capture_output=True, text=True, timeout=60
                )
                path = result.stdout.strip().rstrip('/')
                if path:
                    _output_dir[0] = path
                    os.makedirs(path, exist_ok=True)
                    self._json_response({'path': path})
                else:
                    self._json_response({'path': None})
            except Exception:
                self._json_response({'path': None})
            return

        if parsed.path == '/api/fetch-image':
            qs = urllib.parse.parse_qs(parsed.query)
            url = qs.get('url', [''])[0]
            name = qs.get('name', ['image'])[0]
            if url:
                try:
                    if url.startswith('data:'):
                        import base64
                        header, b64data = url.split(',', 1)
                        ct = header.split(':')[1].split(';')[0]
                        ext = '.png'
                        if 'jpeg' in ct or 'jpg' in ct:
                            ext = '.jpg'
                        elif 'webp' in ct:
                            ext = '.webp'
                        elif 'gif' in ct:
                            ext = '.gif'
                        img_bytes = base64.b64decode(b64data)
                        self.send_response(200)
                        self.send_header('Content-Type', ct)
                        self.send_header('Content-Disposition', 'attachment; filename="' + name + ext + '"')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(img_bytes)
                        return
                    elif requests:
                        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
                        r = requests.get(url, headers=headers, timeout=15)
                        if r.status_code == 200:
                            ct = r.headers.get('Content-Type', 'image/png')
                            ext = '.png'
                            if 'jpeg' in ct or 'jpg' in ct:
                                ext = '.jpg'
                            elif 'webp' in ct:
                                ext = '.webp'
                            self.send_response(200)
                            self.send_header('Content-Type', ct)
                            self.send_header('Content-Disposition', 'attachment; filename="' + name + ext + '"')
                            self.send_header('Access-Control-Allow-Origin', '*')
                            self.end_headers()
                            self.wfile.write(r.content)
                            return
                except Exception as e:
                    print(f"  [FETCH ERROR] {e}")
            self.send_error(404)
            return

        if parsed.path == '/api/next-url':
            url = _next_url[0]
            if url:
                _next_url[0] = None
            self._json_response({'url': url})
            return

        if parsed.path == '/api/status':
            self._json_response({
                'currentIdx': _current_idx[0],
                'total': len(_items_list),
                'done': _current_idx[0] >= len(_items_list),
                'outputDir': get_output_dir()
            })
            return

        if parsed.path == '/api/open-folder':
            out = get_output_dir()
            if os.path.isdir(out):
                subprocess.Popen(['open', out])
            self._json_response({'opened': out})
            return

        if parsed.path == '/api/signal-skip':
            _skip_flag[0] = True
            self._json_response({'ok': True})
            return

        if parsed.path == '/api/check-skip':
            val = _skip_flag[0]
            _skip_flag[0] = False
            self._json_response({'skip': val})
            return

        if parsed.path == '/api/google-images':
            qs = urllib.parse.parse_qs(parsed.query)
            query = qs.get('q', [''])[0]
            save_name = qs.get('name', ['image'])[0]
            if query and requests:
                try:
                    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                    resp = requests.get(
                        'https://www.google.com/search',
                        params={'q': query, 'tbm': 'isch'},
                        headers=headers, timeout=10
                    )
                    item_name = qs.get('item', [save_name])[0]
                    inject = get_google_inject_js(save_name, item_name)
                    html = resp.text.replace('</body>', inject + '</body>')
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(html.encode('utf-8', errors='replace'))
                    return
                except Exception as e:
                    print(f"  [PROXY ERROR] {e}")
            self.send_error(500)
            return

        self.send_error(404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)

        if parsed.path == '/api/save-items':
            data = json.loads(body)
            _items_list.clear()
            _items_list.extend(data)
            _current_idx[0] = 0
            os.makedirs(SESSION_DIR, exist_ok=True)
            items_path = os.path.join(SESSION_DIR, 'items.json')
            existing = {}
            if os.path.isfile(items_path):
                with open(items_path) as f:
                    existing = json.load(f)
            if isinstance(existing, dict):
                existing['items'] = data
            else:
                existing = {'items': data}
            with open(items_path, 'w') as f:
                json.dump(existing, f, indent=2)
            self._json_response({'saved': len(data)})
            return

        if parsed.path == '/api/set-next-url':
            data = json.loads(body)
            _next_url[0] = data.get('url')
            self._json_response({'ok': True})
            return

        if parsed.path == '/api/advance':
            data = json.loads(body)
            action = data.get('action', 'save')

            if action == 'save' and _items_list and _current_idx[0] < len(_items_list):
                item = _items_list[_current_idx[0]]
                safe = item.get('safeName', 'item')
                src = os.path.join(DOWNLOADS, safe + '.png')
                if os.path.isfile(src):
                    out = get_output_dir()
                    os.makedirs(out, exist_ok=True)
                    ext = os.path.splitext(src)[1].lower() or '.png'
                    dest = os.path.join(out, safe + ext)
                    shutil.move(src, dest)
                    print(f"  [ADVANCE] Saved {dest}")

            _current_idx[0] += 1
            idx = _current_idx[0]

            if idx < len(_items_list):
                item = _items_list[idx]
                query = item.get('query', item.get('name', ''))
                safe = item.get('safeName', 'item')
                name = item.get('name', '')
                url = '/api/google-images?q=' + urllib.parse.quote(query) \
                    + '&name=' + urllib.parse.quote(safe) \
                    + '&item=' + urllib.parse.quote(name)
                self._json_response({'done': False, 'url': url, 'idx': idx, 'total': len(_items_list)})
            else:
                self._json_response({'done': True, 'idx': idx, 'total': len(_items_list)})
            return

        if parsed.path == '/api/save-image-data':
            import cgi
            ct_header = self.headers.get('Content-Type', '')
            form = cgi.FieldStorage(
                fp=BytesIO(body),
                headers=self.headers,
                environ={'REQUEST_METHOD': 'POST', 'CONTENT_TYPE': ct_header}
            )
            img_field = form['image']
            name_field = form.getvalue('name', 'image')
            img_bytes = img_field.file.read()
            save_path = os.path.join(DOWNLOADS, name_field + '.png')
            with open(save_path, 'wb') as f:
                f.write(img_bytes)
            print(f"  [SAVE-DATA] {save_path} ({len(img_bytes)} bytes)")
            self._json_response({'saved': save_path, 'size': len(img_bytes)})
            return

        if parsed.path == '/api/save-image':
            data = json.loads(body)
            src = data.get('source')
            name = data.get('safeName', 'image')
            if not src or not os.path.isfile(src):
                self.send_error(400, 'Source file not found')
                return
            out = get_output_dir()
            os.makedirs(out, exist_ok=True)
            ext = os.path.splitext(src)[1].lower() or '.png'
            dest = os.path.join(out, name + ext)
            shutil.move(src, dest)
            print(f"  [SAVED] {dest}")
            self._json_response({'saved': dest})
            return

        if parsed.path == '/api/set-output-dir':
            data = json.loads(body)
            new_dir = os.path.expanduser(data.get('outputDir', ''))
            if new_dir:
                _output_dir[0] = new_dir
                os.makedirs(new_dir, exist_ok=True)
            self._json_response({'outputDir': get_output_dir()})
            return

        if parsed.path == '/api/save-picks':
            data = json.loads(body)
            os.makedirs(SESSION_DIR, exist_ok=True)
            picks_path = os.path.join(SESSION_DIR, 'picks.json')
            with open(picks_path, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"  [SAVED] {picks_path}")
            self._json_response({'saved': picks_path})
            return

        self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def _json_response(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, fmt, *args):
        if '/api/latest-download' in str(args) or '/api/heartbeat' in str(args):
            return
        super().log_message(fmt, *args)


# ── Heartbeat Monitor ─────────────────────────────────────────────────────────

def heartbeat_monitor():
    """Shut down the server when the browser tab closes (no heartbeat)."""
    while True:
        _time.sleep(5)
        if _time.time() - _last_heartbeat > _heartbeat_timeout:
            print("\nNo heartbeat. Browser tab closed. Shutting down.")
            os._exit(0)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    run_preflight()

    os.makedirs(SESSION_DIR, exist_ok=True)

    server = http.server.HTTPServer(('', PORT), Handler)
    print(f"Listening on http://localhost:{PORT}")

    # Start heartbeat monitor
    hb = threading.Thread(target=heartbeat_monitor, daemon=True)
    hb.start()

    # Open browser
    threading.Timer(0.5, lambda: webbrowser.open(f'http://localhost:{PORT}')).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()
