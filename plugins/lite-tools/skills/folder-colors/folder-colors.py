#!/usr/bin/env python3
"""Folder Colors - macOS folder icon colorizer with smart auto-coloring.

Run: python3 ~/.claude/skills/folder-colors/folder-colors.py
Opens a browser-based UI on localhost:9847.

NOTE: This is a local-only tool. All HTML rendering uses data from the
local filesystem only. No external/untrusted input is processed.
"""

import http.server
import json
import os
import subprocess
import sys
import threading
import webbrowser
import colorsys
import hashlib
import base64
from io import BytesIO
from urllib.parse import parse_qs, urlparse

VERSION = "1.0"
PORT = 9847


def run_preflight():
    """Run startup checks and print pass/fail for each. Returns True if all pass."""
    checks = []

    def check(name, fn):
        try:
            ok = fn()
            checks.append((name, ok))
        except Exception:
            checks.append((name, False))

    # 1. Python version
    check("Python 3.6+", lambda: sys.version_info >= (3, 6))

    # 2. osascript available
    check("osascript", lambda: subprocess.run(
        ["which", "osascript"], capture_output=True).returncode == 0)

    # 3. sips available
    check("sips", lambda: subprocess.run(
        ["which", "sips"], capture_output=True).returncode == 0)

    # 4. Finder automation permission
    def check_finder():
        r = subprocess.run(
            ["osascript", "-e", 'tell application "Finder" to get name of startup disk'],
            capture_output=True, text=True, timeout=30)
        return r.returncode == 0

    check("Finder access", check_finder)

    # 5. System Events permission
    def check_system_events():
        r = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to get name'],
            capture_output=True, text=True, timeout=30)
        return r.returncode == 0

    check("System Events", check_system_events)

    # 6. Writable temp dir
    check("Temp directory", lambda: os.access("/tmp", os.W_OK))

    # Print results
    print(f"\nFolder Colors v{VERSION}")
    all_ok = True
    for name, ok in checks:
        dots = "." * (24 - len(name))
        status = "ok" if ok else "FAIL"
        print(f"  {name} {dots} {status}")
        if not ok:
            all_ok = False

    if not all_ok:
        print("\nSome checks failed. The server will start, but some features may not work.")
        print("If permission dialogs appeared, approve them and restart.\n")
    else:
        print()

    return all_ok

# Heartbeat: track last ping from browser, auto-shutdown when tab closes
import time as _time
_last_heartbeat = _time.time()
_heartbeat_timeout = 10  # seconds without a ping before shutdown

# Preview cache: maps "color|opacity" -> PNG bytes
_preview_cache = {}

# Shared state: when set-layers is called externally, store here for UI to pick up
_pending_layers = None  # {"layers": {"0": "#hex", ...}, "description": "...", "version": int}
_layers_version = 0

# ── Smart Color Engine ──────────────────────────────────────────────────────

# Each rule: (keywords, {style: (h, s, l)})
# Styles: intuitive (default), vibrant (boosted saturation), muted (professional)
CATEGORY_STYLES = {
    "finance": {
        "intuitive": (145, 65, 42),   # green (money = green)
        "vibrant":   (145, 85, 45),
        "muted":     (145, 35, 48),
    },
    "trash": {
        "intuitive": (0, 30, 50),     # muted red-gray (cleanup)
        "vibrant":   (0, 55, 48),
        "muted":     (0, 18, 55),
    },
    "code": {
        "intuitive": (180, 70, 42),   # teal/cyan (tech)
        "vibrant":   (180, 85, 45),
        "muted":     (180, 35, 48),
    },
    "photo": {
        "intuitive": (25, 70, 52),    # warm orange
        "vibrant":   (25, 85, 50),
        "muted":     (25, 40, 52),
    },
    "music": {
        "intuitive": (320, 60, 50),   # pink/magenta
        "vibrant":   (320, 80, 50),
        "muted":     (320, 30, 52),
    },
    "video": {
        "intuitive": (0, 70, 40),     # deep red (cinema)
        "vibrant":   (0, 85, 42),
        "muted":     (0, 35, 45),
    },
    "document": {
        "intuitive": (215, 65, 50),   # blue (professional)
        "vibrant":   (215, 82, 50),
        "muted":     (215, 35, 52),
    },
    "design": {
        "intuitive": (275, 60, 52),   # purple (creative)
        "vibrant":   (275, 80, 52),
        "muted":     (275, 30, 52),
    },
    "school": {
        "intuitive": (50, 75, 48),    # yellow
        "vibrant":   (50, 90, 48),
        "muted":     (50, 40, 50),
    },
    "download": {
        "intuitive": (30, 75, 50),    # orange (attention)
        "vibrant":   (30, 90, 48),
        "muted":     (30, 40, 50),
    },
    "work": {
        "intuitive": (220, 55, 38),   # navy (corporate)
        "vibrant":   (220, 75, 40),
        "muted":     (220, 30, 45),
    },
    "config": {
        "intuitive": (200, 15, 48),   # gray (neutral)
        "vibrant":   (200, 30, 48),
        "muted":     (200, 10, 52),
    },
    "personal": {
        "intuitive": (330, 55, 52),   # rose
        "vibrant":   (330, 75, 52),
        "muted":     (330, 30, 52),
    },
}

CATEGORY_RULES = [
    (["finance", "money", "invoice", "tax", "budget", "accounting",
      "receipt", "bank", "payment", "billing"],
     "finance"),
    (["trash", "temp", "tmp", "old", "backup", "archive", "cache",
      "deprecated", "unused", "legacy"],
     "trash"),
    (["code", "dev", "src", "project", "repo", "git", "build", "dist", "bin",
      "lib", "pkg", "node_modules", "venv", ".env", "scripts", "tools"],
     "code"),
    (["photo", "image", "picture", "screenshot", "camera", "gallery",
      "wallpaper", "png", "jpg", "svg"],
     "photo"),
    (["music", "audio", "sound", "podcast", "song", "playlist", "beat",
      "sample", "mix"],
     "music"),
    (["video", "movie", "film", "clip", "recording", "stream", "youtube",
      "media"],
     "video"),
    (["doc", "document", "paper", "report", "notes", "writing", "draft",
      "text", "pdf", "word", "pages"],
     "document"),
    (["design", "sketch", "figma", "ui", "ux", "mockup", "wireframe",
      "asset", "icon", "font", "graphic", "art"],
     "design"),
    (["school", "class", "course", "homework", "study", "lecture",
      "assignment", "exam", "grade", "education"],
     "school"),
    (["download", "downloads"],
     "download"),
    (["work", "office", "meeting", "client", "contract", "hr",
      "employee", "team", "company", "corporate"],
     "work"),
    (["config", "settings", "pref", "system", "etc", "log", "data",
      "database", "db", "sql"],
     "config"),
    (["personal", "private", "journal", "diary", "health", "fitness",
      "recipe", "travel", "vacation"],
     "personal"),
]


def categorize_folder(name, style="intuitive"):
    lower = name.lower().replace("_", " ").replace("-", " ").replace(".", " ")
    for keywords, category in CATEGORY_RULES:
        for kw in keywords:
            if kw in lower:
                styles = CATEGORY_STYLES.get(category, {})
                return styles.get(style, styles.get("intuitive"))
    return None


def hash_color(name):
    h = int(hashlib.md5(name.encode()).hexdigest()[:8], 16)
    return (h % 360, 55, 48)


def depth_adjust(hsl, depth):
    h, s, l = hsl
    h = (h + depth * 15) % 360
    s = max(25, s - depth * 8)
    l = min(70, l + depth * 6)
    return (h, s, l)


def hsl_to_rgb01(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h / 360, l / 100, s / 100)
    return (r, g, b)


def hsl_to_hex(h, s, l):
    r, g, b = hsl_to_rgb01(h, s, l)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def hex_to_rgb01(hex_color):
    hex_color = hex_color.lstrip("#")
    return (int(hex_color[0:2], 16) / 255,
            int(hex_color[2:4], 16) / 255,
            int(hex_color[4:6], 16) / 255)


def scan_folder(path, max_depth=3, _depth=0, style="intuitive"):
    results = []
    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        return results
    for name in entries:
        if name.startswith(".") or name == "Icon\r":
            continue
        full = os.path.join(path, name)
        if not os.path.isdir(full):
            continue
        cat_hsl = categorize_folder(name, style) or hash_color(name)
        adjusted = depth_adjust(cat_hsl, _depth)
        entry = {
            "name": name,
            "path": full,
            "depth": _depth,
            "color": hsl_to_hex(*adjusted),
            "children": scan_folder(full, max_depth, _depth + 1, style) if _depth < max_depth else [],
        }
        results.append(entry)
    return results


# ── Describe Palette Engine ─────────────────────────────────────────────────

PALETTE_KEYWORDS = {
    # hue_center, hue_range, sat_min, sat_max, light_min, light_max
    "ocean":   (200, 40, 50, 80, 35, 60),
    "sea":     (190, 35, 50, 75, 35, 55),
    "sky":     (210, 30, 45, 70, 50, 70),
    "forest":  (140, 40, 40, 70, 28, 50),
    "earth":   (25, 30, 35, 60, 30, 52),
    "sunset":  (15, 40, 60, 85, 40, 60),
    "warm":    (20, 50, 50, 75, 40, 60),
    "cool":    (220, 50, 40, 70, 38, 58),
    "pastel":  (0, 360, 30, 50, 65, 80),
    "dark":    (0, 360, 40, 70, 20, 38),
    "moody":   (260, 80, 30, 55, 22, 42),
    "vibrant": (0, 360, 70, 95, 42, 58),
    "neon":    (0, 360, 85, 100, 48, 60),
    "autumn":  (25, 40, 50, 75, 35, 55),
    "fall":    (25, 40, 50, 75, 35, 55),
    "spring":  (100, 60, 45, 70, 45, 65),
    "winter":  (210, 40, 25, 50, 40, 65),
    "summer":  (40, 60, 55, 80, 45, 62),
    "berry":   (310, 50, 45, 75, 30, 52),
    "rose":    (340, 30, 45, 70, 40, 60),
    "mint":    (160, 30, 40, 65, 45, 65),
    "lavender":(270, 30, 35, 55, 50, 70),
    "gold":    (45, 20, 55, 80, 42, 58),
    "rust":    (15, 20, 50, 70, 30, 48),
    "slate":   (210, 30, 15, 30, 35, 55),
    "coral":   (10, 20, 60, 80, 50, 65),
    "teal":    (175, 25, 45, 70, 35, 52),
    "plum":    (290, 30, 40, 60, 30, 48),
    "sand":    (35, 20, 30, 50, 55, 70),
    "navy":    (225, 20, 50, 75, 22, 38),
    "wine":    (345, 25, 45, 65, 25, 40),
    "ice":     (200, 30, 20, 40, 65, 82),
    "fire":    (10, 30, 70, 90, 38, 55),
    "tropical":(160, 80, 55, 80, 40, 60),
    "retro":   (30, 60, 40, 65, 40, 58),
    "candy":   (320, 80, 55, 80, 55, 72),
    "coffee":  (25, 15, 30, 50, 25, 42),
    "midnight":(240, 30, 40, 65, 15, 32),
    # Basic color names
    "red":     (0, 30, 60, 85, 35, 55),
    "orange":  (25, 25, 60, 85, 42, 58),
    "yellow":  (50, 25, 60, 85, 48, 62),
    "green":   (130, 40, 45, 75, 35, 55),
    "blue":    (220, 40, 50, 80, 35, 58),
    "purple":  (275, 40, 45, 75, 32, 58),
    "violet":  (280, 35, 45, 75, 35, 58),
    "pink":    (330, 30, 50, 80, 50, 68),
    "magenta": (300, 30, 55, 80, 40, 55),
    "cyan":    (185, 30, 50, 80, 40, 58),
    "indigo":  (250, 30, 45, 70, 28, 45),
    "brown":   (20, 25, 35, 55, 28, 45),
    "gray":    (210, 20, 8, 20, 35, 65),
    "grey":    (210, 20, 8, 20, 35, 65),
    "black":   (0, 360, 15, 35, 10, 25),
    "white":   (0, 360, 10, 25, 75, 90),
    "cream":   (40, 15, 20, 40, 70, 85),
    "turquoise":(175, 25, 50, 75, 40, 58),
    "maroon":  (345, 25, 45, 65, 22, 38),
    "olive":   (80, 25, 35, 55, 30, 45),
    "peach":   (20, 20, 45, 70, 60, 75),
    "aqua":    (185, 30, 55, 80, 45, 62),
    "crimson": (348, 25, 60, 85, 30, 48),
    "emerald": (155, 30, 50, 75, 35, 52),
    "sapphire":(225, 25, 55, 80, 30, 48),
    "ruby":    (350, 25, 55, 80, 30, 48),
    "amber":   (38, 20, 60, 85, 42, 58),
}

import random as _random


def describe_palette(description, n_layers=8, n_accents=8):
    """Parse a text description and generate coordinated colors.

    Returns:
        layers: 8 colors in a dark-to-light gradient (layer theme style)
        accents: 8 colors spread across the hue range (regular theme style)
    """
    words = description.lower().split()
    matches = []
    for w in words:
        for kw, params in PALETTE_KEYWORDS.items():
            if kw in w or w in kw:
                matches.append(params)

    if not matches:
        h = int(hashlib.md5(description.encode()).hexdigest()[:4], 16) % 360
        matches = [(h, 60, 45, 70, 35, 55)]

    hue_center = sum(m[0] for m in matches) / len(matches)
    hue_range = max(m[1] for m in matches)
    sat_min = sum(m[2] for m in matches) / len(matches)
    sat_max = sum(m[3] for m in matches) / len(matches)
    light_min = sum(m[4] for m in matches) / len(matches)
    light_max = sum(m[5] for m in matches) / len(matches)

    rng = _random.Random(hashlib.md5(description.encode()).hexdigest())

    # Layer theme: 8 colors from very dark to very light, staying on-hue
    layers = []
    for i in range(n_layers):
        t = i / max(n_layers - 1, 1)
        h = (hue_center + rng.uniform(-hue_range * 0.15, hue_range * 0.15)) % 360
        s = sat_max - t * (sat_max - sat_min) * 0.4  # saturation drops gently
        # Lightness range stays in reproducible zone for folder tinting
        l = 22 + t * 52
        layers.append(hsl_to_hex(h, s, l))

    # Accent theme: 8 colors spread across the hue range at varied lightnesses
    accents = []
    for i in range(n_accents):
        h_off = (i - n_accents // 2) * (hue_range / n_accents)
        h = (hue_center + h_off) % 360
        s = sat_min + rng.random() * (sat_max - sat_min)
        l = light_min + rng.random() * (light_max - light_min)
        accents.append(hsl_to_hex(h, s, l))

    return {"layers": layers, "accents": accents}


# ── JXA Icon Engine ─────────────────────────────────────────────────────────

def apply_color(folder_path, r, g, b, opacity=0.55):
    import math
    # Reset the icon first so we tint from a clean base
    reset_icon(folder_path)
    escaped = folder_path.replace("\\", "\\\\").replace('"', '\\"')

    # Convert target RGB to HSV for hue rotation and brightness matching
    target_h, target_s, target_v = colorsys.rgb_to_hsv(r, g, b)
    target_hue_deg = target_h * 360
    folder_hue_deg = 210  # macOS folder blue
    rotation_rad = (target_hue_deg - folder_hue_deg) / 180.0 * math.pi

    # Saturation: blend between folder's native saturation and target
    # Capped to prevent over-saturation that crushes to black at high intensity
    folder_sat = 0.55
    sat_boost = (target_s / max(folder_sat, 0.01)) * (0.5 + opacity * 0.5)
    sat_boost = min(sat_boost, 2.5)

    # Exposure: darken multiplicatively to preserve detail and hue
    # Softened at high opacity to prevent black folders
    folder_val = 0.85
    ratio = max(target_v / folder_val, 0.15)
    # Gentler strength curve: less aggressive darkening
    strength = 1.0 if ratio < 0.4 else (0.9 if ratio < 0.8 else 0.6)
    exposure_adj = math.log2(ratio) * strength * min(opacity + 0.3, 1.0)

    script = f'''
    ObjC.import("AppKit");
    ObjC.import("CoreImage");
    var ws = $.NSWorkspace.sharedWorkspace;
    var icon = ws.iconForFileType("public.folder");
    icon.setSize({{width: 512, height: 512}});

    var tiff = icon.TIFFRepresentation;
    var rep = $.NSBitmapImageRep.imageRepWithData(tiff);
    var cgImg = rep.CGImage;
    var ciImg = $.CIImage.imageWithCGImage(cgImg);

    // Rotate hue to target color (preserves all shadows and gradients)
    var hue = $.CIFilter.filterWithName("CIHueAdjust");
    hue.setDefaults;
    hue.setValueForKey(ciImg, "inputImage");
    hue.setValueForKey($.NSNumber.numberWithDouble({rotation_rad}), "inputAngle");
    var out1 = hue.valueForKey("outputImage");

    // Adjust saturation
    var sat = $.CIFilter.filterWithName("CIColorControls");
    sat.setDefaults;
    sat.setValueForKey(out1, "inputImage");
    sat.setValueForKey($.NSNumber.numberWithDouble({sat_boost}), "inputSaturation");
    var out2 = sat.valueForKey("outputImage");

    // Adjust exposure (multiplicative darkening preserves detail and hue)
    var exp = $.CIFilter.filterWithName("CIExposureAdjust");
    exp.setDefaults;
    exp.setValueForKey(out2, "inputImage");
    exp.setValueForKey($.NSNumber.numberWithDouble({exposure_adj}), "inputEV");
    out2 = exp.valueForKey("outputImage");

    // Render to CGImage then NSImage
    var ctx = $.CIContext.context;
    var ext = out2.extent;
    var cgOut = ctx.createCGImageFromRect(out2, ext);
    var final_img = $.NSImage.alloc.initWithCGImageSize(cgOut, {{width: 512, height: 512}});

    ws.setIconForFileOptions(final_img, "{escaped}", 0);
    "ok";
    '''
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", script],
        capture_output=True, text=True
    )
    return result.returncode == 0 and "ok" in result.stdout


def reset_icon(folder_path):
    icon_file = os.path.join(folder_path, "Icon\r")
    try:
        if os.path.exists(icon_file):
            os.remove(icon_file)
    except OSError:
        pass
    escaped = folder_path.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(
        ["osascript", "-e",
         f'tell application "Finder" to update item (POSIX file "{escaped}" as alias)'],
        capture_output=True, text=True
    )


# ── Wallpaper Color Extraction ───────────────────────────────────────────────

def get_wallpaper_path():
    result = subprocess.run(
        ["osascript", "-e", 'tell application "System Events" to get picture of desktop 1'],
        capture_output=True, text=True
    )
    path = result.stdout.strip()
    return path if path and os.path.exists(path) else None


def _ensure_readable(image_path):
    """Convert HEIC/HEIF to JPEG via sips if needed. Returns a readable path."""
    if image_path.lower().endswith(('.heic', '.heif')):
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
        tmp.close()
        subprocess.run(
            ["sips", "-s", "format", "jpeg", image_path, "--out", tmp.name],
            capture_output=True, text=True
        )
        return tmp.name
    return image_path


def extract_palette(image_path, n_colors=12):
    try:
        from PIL import Image
        readable = _ensure_readable(image_path)
        img = Image.open(readable).convert("RGB")
        img = img.resize((150, 150))
        quantized = img.quantize(colors=n_colors, method=Image.Quantize.MEDIANCUT)
        palette_data = quantized.getpalette()
        counts = sorted(quantized.getcolors(), reverse=True)

        colors = []
        seen_hues = set()
        for count, idx in counts:
            r = palette_data[idx * 3]
            g = palette_data[idx * 3 + 1]
            b = palette_data[idx * 3 + 2]
            h, s_val, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            if v < 0.15 or v > 0.95 or s_val < 0.08:
                continue
            hue_bucket = round(h * 12)
            if hue_bucket in seen_hues:
                continue
            seen_hues.add(hue_bucket)
            colors.append(f"#{r:02x}{g:02x}{b:02x}")
            if len(colors) >= 8:
                break

        if len(colors) < 4:
            for count, idx in counts:
                r = palette_data[idx * 3]
                g = palette_data[idx * 3 + 1]
                b = palette_data[idx * 3 + 2]
                hx = f"#{r:02x}{g:02x}{b:02x}"
                if hx not in colors:
                    colors.append(hx)
                if len(colors) >= 6:
                    break
        return colors
    except Exception:
        return []


def generate_contrast_palette(wallpaper_colors):
    """Generate 8 folder colors that look great against the wallpaper.

    Strategy:
    - Extract each wallpaper color's hue, boost saturation and shift value
    - Add complementary colors for variety
    - Ensure all colors are vivid enough to read as folder tints
    """
    if not wallpaper_colors:
        return []

    wp_hsv = []
    for hex_c in wallpaper_colors:
        hex_c = hex_c.lstrip("#")
        r, g, b = int(hex_c[0:2], 16) / 255, int(hex_c[2:4], 16) / 255, int(hex_c[4:6], 16) / 255
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        wp_hsv.append((h, s, v))

    avg_light = sum(v for _, _, v in wp_hsv) / len(wp_hsv)

    # Target: vivid, medium-value colors that pop on the wallpaper
    if avg_light > 0.65:
        target_val_range = (0.50, 0.70)  # darker folders on light wallpaper
    elif avg_light > 0.35:
        target_val_range = (0.55, 0.75)
    else:
        target_val_range = (0.65, 0.85)  # brighter folders on dark wallpaper

    result = []
    used_buckets = set()

    # First pass: boost each wallpaper color into a vivid folder color
    for h, s, v in wp_hsv:
        bucket = round(h * 12) % 12
        if bucket in used_buckets:
            continue
        used_buckets.add(bucket)
        new_s = max(0.55, min(0.85, s * 1.3 + 0.15))
        new_v = (target_val_range[0] + target_val_range[1]) / 2
        r, g, b = colorsys.hsv_to_rgb(h, new_s, new_v)
        result.append(f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}")

    # Second pass: add complementary and offset hues for variety
    for h, s, v in wp_hsv:
        for offset in [0.5, 0.33, 0.67]:
            if len(result) >= 8:
                break
            ch = (h + offset) % 1.0
            bucket = round(ch * 12) % 12
            if bucket in used_buckets:
                continue
            used_buckets.add(bucket)
            new_s = max(0.55, min(0.85, 0.70))
            idx = len(result)
            new_v = target_val_range[0] + (target_val_range[1] - target_val_range[0]) * (idx / 8)
            r, g, b = colorsys.hsv_to_rgb(ch, new_s, new_v)
            result.append(f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}")

    return result[:8]


def wallpaper_thumbnail(image_path, max_w=400):
    try:
        from PIL import Image
        readable = _ensure_readable(image_path)
        img = Image.open(readable).convert("RGB")
        ratio = max_w / img.width
        img = img.resize((max_w, int(img.height * ratio)))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=75)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


# ── HTTP Server ─────────────────────────────────────────────────────────────

HOME_DIR = os.path.expanduser("~")


class ThreadedHTTPServer(http.server.HTTPServer):
    """Handle each request in a separate thread so JXA calls don't block the UI."""
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
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _html(self, content):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode())

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._html(HTML)
        elif parsed.path == "/api/scan":
            params = parse_qs(parsed.query)
            path = params.get("path", [os.path.expanduser("~/Desktop")])[0]
            depth = int(params.get("depth", ["2"])[0])
            style = params.get("style", ["intuitive"])[0]
            if style not in ("intuitive", "vibrant", "muted"):
                style = "intuitive"
            if not os.path.isdir(path):
                self._json({"error": "Not a directory"}, 400)
                return
            self._json({"path": path, "tree": scan_folder(path, max_depth=depth, style=style)})
        elif parsed.path == "/api/list":
            params = parse_qs(parsed.query)
            path = params.get("path", [HOME_DIR])[0]
            if path == "~":
                path = HOME_DIR
            if not os.path.isdir(path):
                self._json({"error": "Not a directory"}, 400)
                return
            dirs = []
            try:
                for name in sorted(os.listdir(path)):
                    full = os.path.join(path, name)
                    if os.path.isdir(full) and not name.startswith("."):
                        dirs.append({"name": name, "path": full})
            except PermissionError:
                pass
            self._json({"path": path, "dirs": dirs, "home": HOME_DIR})
        elif parsed.path == "/api/count":
            params = parse_qs(parsed.query)
            path = params.get("path", [HOME_DIR])[0]
            max_depth = int(params.get("depth", [999])[0])
            if path == "~":
                path = HOME_DIR
            if not os.path.isdir(path):
                self._json({"error": "Not a directory", "count": 0}, 400)
                return
            count = 0
            def count_recursive(p, d):
                nonlocal count
                if d > max_depth:
                    return
                try:
                    for name in sorted(os.listdir(p)):
                        full = os.path.join(p, name)
                        if os.path.isdir(full) and not name.startswith(".") and name != "Icon\r":
                            count += 1
                            count_recursive(full, d + 1)
                except PermissionError:
                    pass
            count_recursive(path, 0)
            self._json({"path": path, "count": count})
        elif parsed.path == "/api/home":
            self._json({"home": HOME_DIR})
        elif parsed.path == "/api/folder-icon":
            try:
                icon_script = '''
                ObjC.import("AppKit");
                ObjC.import("Foundation");
                var ws = $.NSWorkspace.sharedWorkspace;
                var folder = ws.iconForFileType("public.folder");
                folder.setSize({width: 256, height: 256});
                var tiff = folder.TIFFRepresentation;
                var rep = $.NSBitmapImageRep.imageRepWithData(tiff);
                var png = rep.representationUsingTypeProperties($.NSBitmapImageFileTypePNG, $.NSDictionary.dictionary);
                png.writeToFileAtomically("/tmp/_fc_icon.png", true);
                "ok";
                '''
                subprocess.run(["osascript", "-l", "JavaScript", "-e", icon_script],
                               capture_output=True, text=True, timeout=10)
                with open("/tmp/_fc_icon.png", "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "max-age=3600")
                self.end_headers()
                self.wfile.write(data)
            except Exception:
                self.send_error(500)
        elif parsed.path == "/api/preview":
            params = parse_qs(parsed.query)
            color = params.get("color", ["#5a7d96"])[0]
            opacity = float(params.get("opacity", ["0.55"])[0])
            cache_key = f"{color}|{opacity}"
            try:
                if cache_key in _preview_cache:
                    data = _preview_cache[cache_key]
                else:
                    hr, hg, hb = hex_to_rgb01(color)
                    target_h, target_s, target_v = colorsys.rgb_to_hsv(hr, hg, hb)
                    import math
                    rotation_rad = (target_h * 360 - 210) / 180.0 * math.pi
                    folder_sat = 0.55
                    sat_boost = (target_s / max(folder_sat, 0.01)) * (0.5 + opacity * 0.5)
                    sat_boost = min(sat_boost, 2.5)
                    folder_val = 0.85
                    ratio = max(target_v / folder_val, 0.15)
                    strength = 1.0 if ratio < 0.4 else (0.9 if ratio < 0.8 else 0.6)
                    exposure_adj = math.log2(ratio) * strength * min(opacity + 0.3, 1.0)
                    preview_script = f'''
                    ObjC.import("AppKit"); ObjC.import("CoreImage");
                    var ws = $.NSWorkspace.sharedWorkspace;
                    var icon = ws.iconForFileType("public.folder");
                    icon.setSize({{width: 256, height: 256}});
                    var tiff = icon.TIFFRepresentation;
                    var rep = $.NSBitmapImageRep.imageRepWithData(tiff);
                    var cgImg = rep.CGImage;
                    var ciImg = $.CIImage.imageWithCGImage(cgImg);
                    var hue = $.CIFilter.filterWithName("CIHueAdjust");
                    hue.setDefaults;
                    hue.setValueForKey(ciImg, "inputImage");
                    hue.setValueForKey($.NSNumber.numberWithDouble({rotation_rad}), "inputAngle");
                    var out1 = hue.valueForKey("outputImage");
                    var sat = $.CIFilter.filterWithName("CIColorControls");
                    sat.setDefaults;
                    sat.setValueForKey(out1, "inputImage");
                    sat.setValueForKey($.NSNumber.numberWithDouble({sat_boost}), "inputSaturation");
                    var out2 = sat.valueForKey("outputImage");
                    var exp = $.CIFilter.filterWithName("CIExposureAdjust");
                    exp.setDefaults;
                    exp.setValueForKey(out2, "inputImage");
                    exp.setValueForKey($.NSNumber.numberWithDouble({exposure_adj}), "inputEV");
                    out2 = exp.valueForKey("outputImage");
                    var ctx = $.CIContext.context;
                    var ext = out2.extent;
                    var cgOut = ctx.createCGImageFromRect(out2, ext);
                    var nsImg = $.NSImage.alloc.initWithCGImageSize(cgOut, {{width: 256, height: 256}});
                    var t2 = nsImg.TIFFRepresentation;
                    var r2 = $.NSBitmapImageRep.imageRepWithData(t2);
                    var png = r2.representationUsingTypeProperties($.NSBitmapImageFileTypePNG, $.NSDictionary.dictionary);
                    png.writeToFileAtomically("/tmp/_fc_preview.png", true);
                    "ok";
                    '''
                    subprocess.run(["osascript", "-l", "JavaScript", "-e", preview_script],
                                   capture_output=True, text=True, timeout=10)
                    with open("/tmp/_fc_preview.png", "rb") as f:
                        data = f.read()
                    if len(_preview_cache) > 200:
                        _preview_cache.clear()
                    _preview_cache[cache_key] = data
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(data)
            except Exception:
                self.send_error(500)
        elif parsed.path == "/api/pick":
            try:
                result = subprocess.run(
                    ["osascript", "-e",
                     'set f to POSIX path of (choose folder with prompt "Choose a folder")\nreturn f'],
                    capture_output=True, text=True, timeout=120
                )
                path = result.stdout.strip().rstrip("/")
                if path:
                    self._json({"path": path})
                else:
                    self._json({"error": "No folder selected"}, 400)
            except subprocess.TimeoutExpired:
                self._json({"error": "Dialog timed out"}, 400)
            except Exception as e:
                self._json({"error": str(e)}, 400)
        elif parsed.path == "/api/get-layers":
            params = parse_qs(parsed.query)
            since = int(params.get("since", ["0"])[0])
            if _pending_layers and _pending_layers["version"] > since:
                self._json(_pending_layers)
            else:
                self._json({"version": _layers_version})
        elif parsed.path == "/api/heartbeat":
            global _last_heartbeat
            _last_heartbeat = _time.time()
            self._json({"ok": True})
        elif parsed.path == "/api/wallpaper":
            wp = get_wallpaper_path()
            if not wp:
                self._json({"error": "Could not detect wallpaper"}, 400)
                return
            colors = extract_palette(wp)
            suggested = generate_contrast_palette(colors)
            thumb = wallpaper_thumbnail(wp)
            self._json({"path": wp, "colors": colors, "suggested": suggested, "thumbnail": thumb})
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if self.path == "/api/apply":
            path = body.get("path", "")
            color = body.get("color", "#3498DB")
            opacity = body.get("opacity", 0.55)
            r, g, b = hex_to_rgb01(color)
            self._json({"ok": apply_color(path, r, g, b, opacity)})
        elif self.path == "/api/reset":
            path = body.get("path", "")
            recursive = body.get("recursive", False)
            count = 0
            if recursive and path and os.path.isdir(path):
                def reset_recursive(folder_path):
                    nonlocal count
                    reset_icon(folder_path)
                    count += 1
                    try:
                        for name in sorted(os.listdir(folder_path)):
                            full = os.path.join(folder_path, name)
                            if os.path.isdir(full) and not name.startswith(".") and name != "Icon\r":
                                reset_recursive(full)
                    except PermissionError:
                        pass
                reset_recursive(path)
            else:
                reset_icon(path)
                count = 1
            self._json({"ok": True, "count": count})
        elif self.path == "/api/describe-palette":
            text = body.get("text", "")
            if not text.strip():
                self._json({"error": "No description provided"}, 400)
                return
            result = describe_palette(text)
            self._json(result)
        elif self.path == "/api/set-layers":
            global _pending_layers, _layers_version
            layers = body.get("layers", {})
            accents = body.get("accents", [])
            path = body.get("path", "")
            opacity = body.get("opacity", 0.55)
            description = body.get("description", "")
            # Store for UI to pick up
            _layers_version += 1
            _pending_layers = {"layers": layers, "accents": accents, "description": description, "version": _layers_version}
            results = []
            if path and os.path.isdir(path):
                # Apply layer colors to actual folders at each depth
                def apply_layers_recursive(folder_path, depth=0):
                    color = layers.get(str(depth))
                    if not color:
                        return
                    r, g, b = hex_to_rgb01(color)
                    apply_color(folder_path, r, g, b, opacity)
                    results.append({"path": folder_path, "depth": depth})
                    if str(depth + 1) in layers:
                        try:
                            for name in sorted(os.listdir(folder_path)):
                                full = os.path.join(folder_path, name)
                                if os.path.isdir(full) and not name.startswith(".") and name != "Icon\r":
                                    apply_layers_recursive(full, depth + 1)
                        except PermissionError:
                            pass
                # Start from children of path at depth 0
                try:
                    for name in sorted(os.listdir(path)):
                        full = os.path.join(path, name)
                        if os.path.isdir(full) and not name.startswith(".") and name != "Icon\r":
                            apply_layers_recursive(full, 0)
                except PermissionError:
                    pass
            self._json({"ok": True, "applied": len(results)})
        elif self.path == "/api/upload-palette":
            image_data = body.get("image", "")
            if not image_data:
                self._json({"error": "No image data"}, 400)
                return
            try:
                # Strip data URL prefix if present
                if "," in image_data:
                    image_data = image_data.split(",", 1)[1]
                raw = base64.b64decode(image_data)
                import tempfile
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                tmp.write(raw)
                tmp.close()
                colors = extract_palette(tmp.name)
                suggested = generate_contrast_palette(colors)
                os.unlink(tmp.name)
                self._json({"colors": colors, "suggested": suggested})
            except Exception as e:
                self._json({"error": str(e)}, 500)
        elif self.path == "/api/apply-batch":
            results = []
            opacity = body.get("opacity", 0.55)
            for item in body.get("items", []):
                r, g, b = hex_to_rgb01(item["color"])
                results.append({"path": item["path"], "ok": apply_color(item["path"], r, g, b, opacity)})
            self._json({"results": results})
        elif self.path == "/api/reset-batch":
            for p in body.get("paths", []):
                reset_icon(p)
            self._json({"ok": True})
        else:
            self.send_error(404)


# ── HTML UI ─────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Folder Colors</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Playfair+Display:ital,wght@0,400;0,700;1,400&family=JetBrains+Mono:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root {
  --obsidian: #0F1114; --champagne: #5A7D96; --ivory: #F5F5F3;
  --slate: #1C1C1E;
  --font-heading: 'Inter', sans-serif;
  --font-drama: 'Playfair Display', serif;
  --font-mono: 'JetBrains Mono', monospace;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: var(--font-heading); background: var(--ivory);
  color: var(--slate); min-height: 100vh;
  -webkit-font-smoothing: antialiased;
}
.noise-overlay { position: fixed; inset: 0; z-index: 9999; pointer-events: none; opacity: 0.04; }

.topbar {
  width: 100%; padding: 18px 36px; display: flex; align-items: center;
  justify-content: space-between; border-bottom: 1px solid rgba(28,28,30,0.08);
}
.topbar-brand { font-weight: 700; font-size: 13px; letter-spacing: 0.12em; text-transform: uppercase; }
.topbar-tabs { display: flex; background: rgba(28,28,30,0.05); border-radius: 2rem; padding: 3px; }
.topbar-tab {
  padding: 7px 20px; border-radius: 2rem; border: none; font-family: var(--font-heading);
  font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.3s;
  color: rgba(28,28,30,0.45); background: none; letter-spacing: 0.02em;
}
.topbar-tab:hover { color: var(--slate); }
.topbar-tab.active { background: var(--slate); color: var(--ivory); }

.main { max-width: 700px; margin: 0 auto; padding: 50px 36px 80px; }
.page-title { font-family: var(--font-drama); font-size: 48px; font-weight: 400; font-style: italic; text-align: center; margin-bottom: 6px; }
.page-subtitle { font-family: var(--font-mono); font-size: 12px; color: var(--champagne); text-align: center; margin-bottom: 40px; }

.panel { display: none; }
.panel.active { display: block; }
.section { margin-bottom: 28px; }
.section-label { font-family: var(--font-mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.12em; color: rgba(28,28,30,0.4); margin-bottom: 10px; }

.path-row { display: flex; gap: 8px; align-items: center; }
.path-input {
  flex: 1; padding: 10px 14px; background: rgba(28,28,30,0.04);
  border: 1px solid rgba(28,28,30,0.1); border-radius: 8px; color: var(--slate);
  font-family: var(--font-mono); font-size: 12px; outline: none; cursor: pointer;
}
.path-input:focus { border-color: var(--champagne); }
.path-input::placeholder { color: rgba(28,28,30,0.3); }

.btn {
  padding: 10px 24px; border: none; border-radius: 2rem; font-family: var(--font-heading);
  font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.3s; letter-spacing: 0.02em;
}
.btn:hover { transform: scale(1.03); }
.btn:disabled { opacity: 0.35; cursor: default; transform: none; }
.btn-primary { background: var(--slate); color: var(--ivory); }
.btn-primary:hover { background: var(--obsidian); }
.btn-secondary { background: transparent; color: rgba(28,28,30,0.55); border: 1px solid rgba(28,28,30,0.18); }
.btn-secondary:hover { border-color: rgba(28,28,30,0.45); color: var(--slate); }
.btn-danger { background: transparent; color: #9a3a3a; border: 1px solid rgba(154,58,58,0.3); }
.btn-success { background: var(--champagne); color: white; }
.btn-sm { padding: 7px 16px; font-size: 12px; }

/* Color presets */
.presets { display: grid; grid-template-columns: repeat(9, 1fr); gap: 8px; }
.preset-wrap { text-align: center; }
.preset { width: 100%; aspect-ratio: 1; border-radius: 12px; border: 3px solid transparent; cursor: pointer; transition: all 0.2s; }
.preset:hover { transform: scale(1.1); }
.preset.selected { border-color: var(--slate); box-shadow: 0 2px 12px rgba(28,28,30,0.15); }
.preset-name { font-size: 10px; color: rgba(28,28,30,0.4); margin-top: 3px; font-weight: 500; }
.preset-custom {
  position: relative; overflow: hidden; border: 2px dashed rgba(28,28,30,0.25);
  display: flex; align-items: center; justify-content: center;
  background: rgba(28,28,30,0.04);
}
.preset-custom::after {
  content: '+'; font-size: 24px; font-weight: 300; color: rgba(28,28,30,0.3);
  pointer-events: none; position: absolute; line-height: 1;
}
.preset-custom.has-custom-color { border-style: solid; border-color: rgba(28,28,30,0.15); }
.preset-custom.has-custom-color::after { display: none; }
.preset-custom input[type="color"] { position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; }
.preset-custom.selected { border-color: var(--slate); border-style: solid; }

/* Theme row */
.themes { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.theme-btn {
  padding: 6px 14px; border-radius: 2rem; border: 1px solid rgba(28,28,30,0.12);
  font-family: var(--font-heading); font-size: 11px; font-weight: 600; cursor: pointer;
  background: white; color: var(--slate); transition: all 0.2s;
}
.theme-btn:hover { border-color: var(--champagne); }
.theme-btn.active { background: var(--slate); color: var(--ivory); border-color: var(--slate); }

/* Picker row */
.picker-row { display: flex; align-items: center; gap: 14px; margin-top: 14px; }
input[type="color"] { width: 44px; height: 44px; border: none; border-radius: 10px; cursor: pointer; background: none; padding: 0; }
input[type="color"]::-webkit-color-swatch-wrapper { padding: 0; }
input[type="color"]::-webkit-color-swatch { border: none; border-radius: 10px; }
.color-hex { font-family: var(--font-mono); font-size: 12px; color: rgba(28,28,30,0.4); }
.folder-preview {
  display: inline-block; position: relative; padding: 8px 0;
}
.preview-spinner {
  display: none; position: absolute; top: 50%; left: 50%;
  width: 28px; height: 28px; margin: -14px 0 0 -14px;
  border: 3px solid rgba(0,0,0,0.1); border-top-color: rgba(0,0,0,0.4);
  border-radius: 50%; animation: spin 0.6s linear infinite;
}
.preview-spinner.visible { display: block; }
@keyframes spin { to { transform: rotate(360deg); } }
.folder-icon-img {
  width: 120px; height: 120px; display: block;
  filter: drop-shadow(0 2px 8px rgba(0,0,0,0.12));
}
.folder-tint-overlay {
  position: absolute; top: 8px; left: 0; width: 120px; height: 120px;
  background: #5a7d96; opacity: 0.55; mix-blend-mode: color;
  pointer-events: none;
  -webkit-mask-image: url(/api/folder-icon);
  mask-image: url(/api/folder-icon);
  -webkit-mask-size: 120px 120px;
  mask-size: 120px 120px;
}
.picker-label { font-family: var(--font-mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; color: rgba(28,28,30,0.35); }

/* Opacity slider */
.opacity-row { display: flex; align-items: center; gap: 12px; margin-top: 12px; }
.opacity-row label { font-family: var(--font-mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; color: rgba(28,28,30,0.4); white-space: nowrap; }
.opacity-row input[type="range"] { flex: 1; accent-color: var(--champagne); }
.opacity-val { font-family: var(--font-mono); font-size: 12px; color: var(--champagne); min-width: 32px; font-weight: 500; }

/* Wallpaper section */
.wallpaper-card {
  background: white; border: 1px solid rgba(28,28,30,0.08); border-radius: 1rem;
  padding: 16px; display: none; margin-top: 12px;
}
.wallpaper-thumb { width: 100%; border-radius: 10px; margin-bottom: 12px; }
.wallpaper-colors { display: flex; gap: 6px; flex-wrap: wrap; }
.wp-swatch {
  width: 36px; height: 36px; border-radius: 8px; cursor: pointer;
  border: 2px solid transparent; transition: all 0.15s;
}
.wp-swatch:hover { transform: scale(1.15); }
.wp-swatch.selected { border-color: var(--slate); }

/* Location pills */
.location-pills { display: flex; gap: 8px; flex-wrap: wrap; }
.loc-pill {
  padding: 8px 16px; border-radius: 2rem; border: 1px solid rgba(28,28,30,0.12);
  font-family: var(--font-heading); font-size: 12px; font-weight: 600; cursor: pointer;
  background: white; color: var(--slate); transition: all 0.2s;
}
.loc-pill:hover { border-color: var(--champagne); color: var(--champagne); }
.loc-pill.active { background: var(--slate); color: var(--ivory); border-color: var(--slate); }

.folder-color-pick {
  width: 24px; height: 24px; border: none; border-radius: 6px; cursor: pointer;
  background: none; padding: 0; flex-shrink: 0;
}
.folder-color-pick::-webkit-color-swatch-wrapper { padding: 0; }
.folder-color-pick::-webkit-color-swatch { border: 1px solid rgba(28,28,30,0.1); border-radius: 6px; }

.folder-expand {
  color: rgba(28,28,30,0.25); font-size: 10px; padding: 4px 8px; border-radius: 4px;
  cursor: pointer; flex-shrink: 0; transition: all 0.15s; user-select: none;
}
.folder-expand:hover { background: rgba(28,28,30,0.06); color: var(--champagne); }

.subfolder-list { display: none; border-left: 2px solid rgba(28,28,30,0.08); margin-left: 28px; }
.sub-item { padding-left: 12px; }
.sub-name { font-size: 12px; color: rgba(28,28,30,0.6); }
.sub-loading { font-size: 12px; padding: 8px 12px; }

.sub-check-row {
  display: flex; align-items: center; gap: 8px; margin-bottom: 12px; cursor: pointer;
  font-family: var(--font-mono); font-size: 11px; color: rgba(28,28,30,0.5);
}
.sub-check-row input { accent-color: var(--champagne); width: 16px; height: 16px; }

/* Welcome banner */
.welcome-banner {
  max-width: 700px; margin: 16px auto 0; padding: 12px 20px;
  background: rgba(90,125,150,0.08); border: 1px solid rgba(90,125,150,0.18);
  border-radius: 10px; display: flex; align-items: center; justify-content: space-between;
  font-size: 13px; color: var(--slate); line-height: 1.4;
}
.welcome-banner-close {
  background: none; border: none; font-size: 18px; color: rgba(28,28,30,0.35);
  cursor: pointer; padding: 4px 8px; margin-left: 12px; flex-shrink: 0;
}
.welcome-banner-close:hover { color: var(--slate); }

.manual-list-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 16px; border-bottom: 1px solid rgba(28,28,30,0.06);
}
.manual-list-title { font-family: var(--font-mono); font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: rgba(28,28,30,0.4); }
.manual-list-actions { display: flex; gap: 6px; }

.action-row { display: flex; gap: 10px; }
.action-row .btn { flex: 1; }
.status { text-align: center; padding: 10px 16px; border-radius: 2rem; font-family: var(--font-mono); font-size: 12px; margin-top: 16px; display: none; }
.status.show { display: block; }
.status.ok { background: rgba(58,125,92,0.08); color: #3a7d5c; }
.status.err { background: rgba(181,59,59,0.08); color: #b53b3b; }
.status.info { background: rgba(90,125,150,0.08); color: var(--champagne); }

/* Progress bar */
.progress-wrap {
  margin-top: 12px; display: none; background: rgba(28,28,30,0.05);
  border-radius: 2rem; overflow: hidden; height: 28px; position: relative;
}
.progress-wrap.show { display: block; }
.progress-bar {
  height: 100%; background: var(--champagne); border-radius: 2rem;
  transition: width 0.2s ease; min-width: 0; width: 0%;
}
.progress-text {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  font-family: var(--font-mono); font-size: 11px; color: var(--slate); font-weight: 500;
  pointer-events: none;
}

/* Smart tree */
.tree-container { max-height: 420px; overflow-y: auto; background: white; border: 1px solid rgba(28,28,30,0.08); border-radius: 1rem; }
.tree-container::-webkit-scrollbar { width: 5px; }
.tree-container::-webkit-scrollbar-thumb { background: rgba(28,28,30,0.12); border-radius: 3px; }
.tree-item { display: flex; align-items: center; padding: 8px 16px; gap: 10px; font-size: 13px; border-bottom: 1px solid rgba(28,28,30,0.04); overflow: hidden; }
.tree-item:last-child { border-bottom: none; }
.tree-swatch { width: 22px; height: 22px; min-width: 22px; min-height: 22px; max-width: 22px; max-height: 22px; border-radius: 6px; border: none; padding: 0; cursor: pointer; flex-shrink: 0; -webkit-appearance: none; appearance: none; }
.tree-swatch::-webkit-color-swatch-wrapper { padding: 0; }
.tree-swatch::-webkit-color-swatch { border: none; border-radius: 6px; }
.tree-swatch:hover { transform: scale(1.2); }
.tree-name { flex: 1; font-weight: 500; }
.tree-path { color: rgba(28,28,30,0.3); font-size: 11px; font-family: var(--font-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 200px; flex-shrink: 1; }
.tree-depth-bar { display: inline-block; width: 2px; height: 14px; border-radius: 1px; margin-right: 2px; background: rgba(28,28,30,0.1); }
.tree-check { width: 16px; height: 16px; accent-color: var(--champagne); cursor: pointer; flex-shrink: 0; }

.depth-row { display: flex; align-items: center; gap: 12px; margin-top: 14px; }
.depth-row label { font-family: var(--font-mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; color: rgba(28,28,30,0.4); white-space: nowrap; }
.depth-row input[type="range"] { flex: 1; accent-color: var(--champagne); }
.depth-val { font-family: var(--font-mono); font-size: 12px; color: var(--champagne); min-width: 16px; font-weight: 500; }

.spinner { display: inline-block; width: 12px; height: 12px; border: 2px solid rgba(90,125,150,0.3); border-top-color: var(--champagne); border-radius: 50%; animation: spin 0.6s linear infinite; margin-right: 6px; vertical-align: middle; }
@keyframes spin { to { transform: rotate(360deg); } }

.main > * { animation: fadeUp 0.45s ease-out both; }
.main > *:nth-child(1) { animation-delay: 0.05s; }
.main > *:nth-child(2) { animation-delay: 0.12s; }
.main > *:nth-child(3) { animation-delay: 0.19s; }
@keyframes fadeUp { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }

.footer { position: fixed; bottom: 16px; right: 24px; font-family: var(--font-mono); font-size: 10px; color: rgba(28,28,30,0.3); }
.footer a { color: var(--champagne); text-decoration: none; }
.empty-msg { padding: 24px; text-align: center; color: rgba(28,28,30,0.35); font-size: 13px; }

/* Layer colors tree */
.layer-tree {
  background: white; border: 1px solid rgba(28,28,30,0.08); border-radius: 12px;
  overflow: hidden;
}
.layer-tree-header {
  display: flex; align-items: center; gap: 8px; padding: 10px 14px;
  border-bottom: 1px solid rgba(28,28,30,0.06); overflow-x: auto;
}
.layer-tree-header .section-label { margin: 0; }
.layer-loc-pills { display: flex; gap: 6px; flex: 1; white-space: nowrap; }
.layer-loc-pill {
  padding: 5px 12px; border-radius: 2rem; border: 1px solid rgba(28,28,30,0.1);
  font-family: var(--font-heading); font-size: 11px; font-weight: 600; cursor: pointer;
  background: none; color: rgba(28,28,30,0.45); transition: all 0.2s; flex-shrink: 0;
}
.layer-loc-pill:hover { border-color: var(--champagne); color: var(--champagne); }
.layer-loc-pill.active { background: var(--slate); color: var(--ivory); border-color: var(--slate); }
.layer-row {
  display: flex; align-items: center; gap: 10px; padding: 8px 14px; position: relative;
  transition: all 0.15s;
}
.layer-row:hover { background: rgba(28,28,30,0.02); }
.layer-row.active-layer { background: rgba(90,125,150,0.12); border-radius: 6px; box-shadow: inset 0 0 0 1.5px rgba(90,125,150,0.2); }
.layer-row.drag-over { background: rgba(90,125,150,0.08); border-left-color: var(--champagne); }
.layer-indent { display: flex; align-items: center; gap: 0; flex-shrink: 0; }
.layer-indent-bar { width: 2px; height: 32px; background: rgba(28,28,30,0.08); margin-left: 9px; margin-right: 9px; }
.layer-folder-img {
  width: 32px; height: 32px; display: block; flex-shrink: 0;
  filter: drop-shadow(0 1px 3px rgba(0,0,0,0.1));
}
.layer-swatch {
  width: 26px; height: 26px; border-radius: 7px; border: 2px solid rgba(28,28,30,0.1);
  cursor: pointer; position: relative; flex-shrink: 0; transition: all 0.15s;
}
.layer-swatch:hover { transform: scale(1.15); border-color: var(--champagne); }
.layer-swatch.has-color { border-color: rgba(28,28,30,0.25); box-shadow: 0 1px 6px rgba(0,0,0,0.1); }
.layer-swatch .inherit-dash {
  position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
  font-size: 14px; line-height: 1; color: rgba(28,28,30,0.25); font-weight: 300;
}
.layer-row input[type="color"] {
  position: absolute; width: 26px; height: 26px; opacity: 0; cursor: pointer; pointer-events: none;
}
.layer-row.has-override input[type="color"] { pointer-events: auto; }
.layer-name { font-size: 13px; font-weight: 500; color: var(--slate); flex: 1; }
.layer-hint { font-family: var(--font-mono); font-size: 10px; color: rgba(28,28,30,0.3); }
.layer-row:not(.has-override) .layer-name { color: rgba(28,28,30,0.4); }
.layer-clear {
  width: 18px; height: 18px; border-radius: 50%; background: none; border: 1px solid rgba(28,28,30,0.12);
  color: rgba(28,28,30,0.3); font-size: 11px; line-height: 16px; text-align: center;
  cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; transition: all 0.15s;
}
.layer-clear:hover { border-color: #b53b3b; color: #b53b3b; background: rgba(181,59,59,0.06); }
.layer-check { width: 16px; height: 16px; accent-color: var(--champagne); cursor: pointer; flex-shrink: 0; margin-left: auto; }
.layer-add-row {
  display: flex; align-items: center; justify-content: center; padding: 4px 14px;
}
.layer-add-btn {
  padding: 3px 12px; border-radius: 2rem; border: 1px dashed rgba(28,28,30,0.15);
  background: none; cursor: pointer; font-family: var(--font-mono); font-size: 10px;
  color: rgba(28,28,30,0.3); transition: all 0.15s; letter-spacing: 0.03em;
}
.layer-add-btn:hover { border-color: var(--champagne); color: var(--champagne); background: rgba(90,125,150,0.04); }
.layer-add-btn:disabled { opacity: 0.3; cursor: default; border-color: rgba(28,28,30,0.1); color: rgba(28,28,30,0.2); background: none; }

/* Preset drag + context menu */
.preset { cursor: grab; }
.preset:active { cursor: grabbing; }
.layer-node-circle.drag-over { transform: scale(1.25); border-color: var(--champagne); box-shadow: 0 0 12px rgba(90,125,150,0.4); }
.preset-ctx {
  position: fixed; background: white; border: 1px solid rgba(28,28,30,0.12); border-radius: 10px;
  padding: 4px 0; box-shadow: 0 4px 20px rgba(0,0,0,0.12); z-index: 10000; min-width: 140px;
  font-family: var(--font-heading); font-size: 12px; display: none;
}
.preset-ctx.show { display: block; }
.preset-ctx-item {
  padding: 7px 14px; cursor: pointer; display: flex; align-items: center; gap: 8px;
  color: var(--slate); transition: background 0.1s;
}
.preset-ctx-item:hover { background: rgba(28,28,30,0.05); }
.preset-ctx-item:first-child { border-radius: 10px 10px 0 0; }
.preset-ctx-item:last-child { border-radius: 0 0 10px 10px; }
.preset-ctx-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.source-toggle.active { background: var(--slate); color: var(--ivory); border-color: var(--slate); }
.source-card { display: none; margin-top: 12px; }
</style>
</head>
<body>
<svg class="noise-overlay" width="100%" height="100%">
  <filter id="noise"><feTurbulence type="fractalNoise" baseFrequency="0.65" numOctaves="3" stitchTiles="stitch"/></filter>
  <rect width="100%" height="100%" filter="url(#noise)"/>
</svg>

<div class="topbar">
  <div class="topbar-brand">Folder Colors</div>
  <div class="topbar-tabs">
    <button class="topbar-tab active" data-tab="manual">Manual</button>
    <button class="topbar-tab" data-tab="smart">Smart Auto-Color</button>
  </div>
</div>

<div class="welcome-banner" id="welcomeBanner" style="display:none;">
  <span>Pick a color and click Apply to color your Desktop folders. Use themes for quick presets.</span>
  <button class="welcome-banner-close" id="welcomeBannerClose" title="Dismiss">X</button>
</div>

<div class="main">
  <div class="page-title">Folder Colors</div>
  <p class="page-subtitle">Tint macOS folder icons with any color, or let smart mode handle it.</p>

  <!-- MANUAL -->
  <div id="panel-manual" class="panel active">

    <!-- 1. Preview -->
    <div class="section" style="text-align:center;">
      <div class="folder-preview" id="folderPreview">
        <img src="/api/folder-icon" class="folder-icon-img" id="folderIconImg" draggable="false">
        <div class="folder-tint-overlay" id="folderTintOverlay"></div>
        <div class="preview-spinner" id="previewSpinner"></div>
      </div>
    </div>

    <!-- 2. Choose Colors -->
    <div class="section">
      <div class="section-label">Themes</div>
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:14px;">
        <div class="themes" id="themes" style="margin-bottom:0;"></div>
        <span style="width:1px;height:20px;background:rgba(28,28,30,0.12);flex-shrink:0;"></span>
        <div class="themes" id="layerThemes" style="margin-bottom:0;"></div>
      </div>

      <div class="presets" id="presets"></div>

      <div class="picker-row" style="margin-top:10px;display:none;">
        <input type="color" id="colorWheel" value="#5a7d96">
        <span class="color-hex" id="colorHex">#5a7d96</span>
      </div>

      <div class="opacity-row">
        <label>Intensity</label>
        <input type="range" id="opacitySlider" min="20" max="95" value="55">
        <span class="opacity-val" id="opacityVal">55%</span>
      </div>

      <!-- Secondary source toggles -->
      <div style="display:flex;gap:8px;margin-top:14px;">
        <button class="btn btn-secondary btn-sm source-toggle" data-source="imageHex" id="imageHexBtn">Image / Hex</button>
        <button class="btn btn-secondary btn-sm source-toggle" data-source="aiPalette" id="aiPaletteBtn">AI Palette</button>
      </div>

      <!-- Image / Hex card (collapsible) -->
      <div class="wallpaper-card source-card" id="imageHexCard" data-source="imageHex">
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
          <label class="btn btn-secondary btn-sm" style="position:relative;overflow:hidden;">
            Upload Image
            <input type="file" id="imageUpload" accept=".png,.jpg,.jpeg,.webp" style="position:absolute;inset:0;opacity:0;cursor:pointer;">
          </label>
          <span style="color:rgba(28,28,30,0.3);font-size:12px;">or pick a color</span>
          <input type="color" id="hexInput" value="#FF5733" style="width:44px;height:36px;border:none;border-radius:8px;cursor:pointer;background:none;padding:0;">
          <button class="btn btn-primary btn-sm" id="hexGenBtn">Generate</button>
        </div>
        <div id="uploadResults" style="display:none;margin-top:10px;">
          <div class="section-label" style="margin-bottom:6px;">From Image</div>
          <div id="uploadSwatches" class="wallpaper-colors"></div>
          <div class="section-label" style="margin:10px 0 6px;">High Contrast</div>
          <div id="uploadContrastSwatches" class="wallpaper-colors"></div>
        </div>
        <div id="hexResults" style="display:none;margin-top:10px;">
          <div class="section-label" style="margin-bottom:6px;">Theme Colors</div>
          <div id="hexSwatches" class="wallpaper-colors" style="margin-bottom:12px;"></div>
          <button class="btn btn-secondary btn-sm" id="hexUseThemeBtn" style="margin-bottom:14px;">Use as Theme</button>
          <div class="section-label" style="margin-bottom:6px;">Layer Gradient</div>
          <div id="hexLayerSwatches" class="wallpaper-colors" style="margin-bottom:12px;"></div>
          <button class="btn btn-secondary btn-sm" id="hexUseLayerBtn">Use as Layer Theme</button>
        </div>
      </div>

      <!-- AI Palette card (collapsible) -->
      <div class="wallpaper-card source-card" id="aiPaletteCard" data-source="aiPalette">
        <div id="aiPaletteHint" style="padding:10px 14px;background:rgba(28,28,30,0.03);border:1px solid rgba(28,28,30,0.08);border-radius:10px;font-size:12px;color:rgba(28,28,30,0.5);line-height:1.6;">
          Describe the colors you want in Claude Code using the skill:<br>
          <code style="background:rgba(28,28,30,0.06);padding:2px 6px;border-radius:4px;font-family:var(--font-mono);font-size:11px;color:var(--slate);">/folder-colors "warm earth tones"</code><br>
          Claude will generate a palette and send it here automatically.
        </div>
        <div id="aiPaletteResults" style="display:none;">
          <div id="aiPaletteDesc" style="font-family:var(--font-mono);font-size:11px;color:var(--champagne);margin-bottom:10px;"></div>
          <div class="section-label" style="margin-bottom:6px;">Theme Colors</div>
          <div id="aiAccentSwatches" class="wallpaper-colors" style="margin-bottom:12px;"></div>
          <button class="btn btn-secondary btn-sm" id="aiUseThemeBtn" style="margin-bottom:14px;">Use as Theme</button>
          <div class="section-label" style="margin-bottom:6px;">Layer Gradient</div>
          <div id="aiLayerSwatches" class="wallpaper-colors" style="margin-bottom:12px;"></div>
          <button class="btn btn-secondary btn-sm" id="aiUseLayerBtn">Use as Layer Theme</button>
        </div>
      </div>
    </div>

    <!-- 2b. Apply To + Color by Depth (merged) -->
    <div class="section">
      <div class="section-label">Apply To</div>
      <div class="layer-tree" id="layerTree"></div>

      <div id="manualFolderList" class="tree-container" style="display:none; margin-top:10px;">
        <div class="manual-list-header">
          <span class="manual-list-title" id="manualListTitle">Folders</span>
        </div>
        <div id="manualFolderItems"></div>
      </div>
    </div>

    <div class="action-row">
      <button class="btn btn-primary" id="applyBtn" disabled>Apply Color</button>
      <button class="btn btn-secondary" id="resetBtn" disabled>Reset to Default</button>
    </div>
    <div class="progress-wrap" id="manualProgress"><div class="progress-bar" id="manualProgressBar"></div><div class="progress-text" id="manualProgressText"></div></div>
    <div class="status" id="manualStatus"></div>
  </div>

  <!-- SMART -->
  <div id="panel-smart" class="panel">
    <div class="section">
      <div class="section-label">Parent Folder</div>
      <div class="path-row">
        <input type="text" class="path-input" id="smartPath" placeholder="~/Desktop" spellcheck="false" style="cursor:text;">
        <button class="btn btn-primary btn-sm" id="scanBtn">Scan</button>
      </div>
      <div class="section-label" style="margin-top:14px;">Color Style</div>
      <div class="themes" id="smartStylePills">
        <button class="theme-btn active" data-style="intuitive">Intuitive</button>
        <button class="theme-btn" data-style="vibrant">Vibrant</button>
        <button class="theme-btn" data-style="muted">Muted</button>
      </div>
      <div class="opacity-row" style="margin-top:12px;">
        <label>Intensity</label>
        <input type="range" id="smartOpacitySlider" min="20" max="95" value="55">
        <span class="opacity-val" id="smartOpacityVal">55%</span>
      </div>
    </div>

    <div class="section" id="smartResultsSection" style="display:none;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
        <div class="section-label" style="margin:0;">Folders Found <span id="folderCount" style="color:var(--champagne);"></span></div>
        <div style="display:flex;gap:8px;">
          <button class="btn btn-sm btn-secondary" id="selectAllBtn">Select All</button>
          <button class="btn btn-sm btn-secondary" id="selectNoneBtn">Select None</button>
        </div>
      </div>
      <div class="tree-container" id="smartTree"></div>
      <div class="action-row" style="margin-top:16px;">
        <button class="btn btn-success" id="applyAllBtn">Apply Selected</button>
        <button class="btn btn-danger" id="resetAllBtn">Reset Selected</button>
      </div>
    </div>
    <div class="progress-wrap" id="smartProgress"><div class="progress-bar" id="smartProgressBar"></div><div class="progress-text" id="smartProgressText"></div></div>
    <div class="status" id="smartStatus"></div>
  </div>
</div>

<div class="footer">Built by <a href="https://jgwillis.com" target="_blank">Joseph Willis</a></div>

<div class="preset-ctx" id="presetCtx"></div>

<script>
const THEMES = {
  'Classic': ['#C0392B','#D35400','#D4A017','#27AE60','#2980B9','#8E44AD','#C2185B','#16A085'],
  'Stealth': ['#2C3E50','#34495E','#1A1A2E','#3D3D3D','#4A4A4A','#2D2D2D','#1B2631','#283747'],
  'Tactical': ['#556B2F','#8B7355','#4A5D23','#6B4226','#3B3B3B','#8B4513','#2F4F4F','#704214'],
  'Carbon': ['#1C1C1C','#333333','#4D4D4D','#666666','#2C2C2C','#3D3D3D','#1A1A1A','#555555'],
  'Dark & Moody': ['#9E2C21','#305853','#B06821','#511B18','#1B2A30','#3B3B3B','#5C4033','#2C3E50'],
  'Earth & Leather': ['#8B5E3C','#A0522D','#6B4226','#556B2F','#8F9779','#D2B48C','#C19A6B','#4A3728'],
  'Midnight': ['#0D1B2A','#1B263B','#415A77','#778DA9','#2A3950','#1F3044','#324A5F','#0B132B'],
  'Mermaidcore': ['#2EC4B6','#6A89CC','#82589F','#3B9B8F','#48DBDB','#7E57C2','#5CA0D3','#38ADA9'],
  'Soft Pastel': ['#FFB5C2','#B5D8FF','#C4B5FF','#B5FFD9','#FFE4B5','#E8B5FF','#B5F0FF','#FFD1B5'],
  'Warm Neutrals': ['#C4A882','#B8A089','#A69279','#D4C4AA','#B5A590','#C9B99A','#A89070','#BCA888'],
  'Sunset': ['#FF6B35','#F7C59F','#EFEFD0','#004E89','#1A659E','#FF9F1C','#E84855','#2B2D42'],
  'Mint Wellness': ['#3EB489','#48C9B0','#76D7C4','#A3E4D7','#1ABC9C','#17A589','#138D75','#0E6655'],
};

const LAYER_THEMES = {
  'Ocean':  ['#15486e', '#1a6898', '#2488b8', '#3aa5d0', '#58bee0', '#80d0ea', '#a8e0f2', '#c8ecf8'],
  'Forest': ['#1a5030', '#286a42', '#388855', '#4ca86c', '#68c088', '#88d4a4', '#a8e4c0', '#c8f0d8'],
  'Sunset': ['#8a2a18', '#a83820', '#c85030', '#d86a40', '#e88858', '#f0a470', '#f4c090', '#f8d8b0'],
  'Berry':  ['#5a1860', '#722878', '#8c3890', '#a848a8', '#c060c0', '#d080d0', '#e0a0e0', '#ecc0ec'],
  'Earth':  ['#4a3020', '#604030', '#785840', '#907050', '#a88868', '#c0a488', '#d4bca4', '#e4d4c0'],
  'Mono':   ['#303030', '#444444', '#5a5a5a', '#727272', '#8c8c8c', '#a8a8a8', '#c0c0c0', '#d8d8d8'],
  'Warm':   ['#7a2018', '#982820', '#b83828', '#d05030', '#e07040', '#ec9060', '#f4b080', '#f8cca0'],
  'Cool':   ['#1a3080', '#244098', '#3058b0', '#4070c4', '#5888d4', '#78a4e0', '#98bcec', '#b8d4f4'],
};

let currentColor = '#5a7d96';

// Layer system: depths relative to the Apply To folder
// depth 0 = top-level children, 1 = subfolders, 2 = sub-subs
// negative depths = parent directories above Apply To
let layerColors = {};       // depth -> color hex or undefined
let layerEnabled = {};      // depth -> boolean (checked for apply)
let layerStartDepth = 0;    // topmost visible layer depth
let layerEndDepth = 2;      // bottommost visible layer depth
let activeLayerDepth = 0;   // currently selected layer for color assignment
let currentBasePath = '';    // the Apply To path
let currentBaseLabel = '';   // display label

function getColorForFolder(folder, depth) {
  if (folder && folder.customColor) return folder.customColor;
  // Each depth is independent. Only uses its own layer color, or main color for depth 0.
  if (layerColors[depth]) return layerColors[depth];
  if (depth === 0) return currentColor;
  return null; // not set
}

// Get the folder name for a given depth relative to base path
function getLayerLabel(depth) {
  if (depth < 0) {
    let parts = currentBasePath.split('/').filter(Boolean);
    const idx = parts.length + depth;
    if (idx >= 0 && idx < parts.length) {
      const name = parts[idx];
      const homeName = homeDir.split('/').filter(Boolean).pop();
      return name === homeName ? 'Home (~)' : name;
    }
    return '/';
  }
  if (depth === 0) return 'Top-level folders';
  if (depth === 1) return 'Subfolders';
  if (depth === 2) return 'Sub-subfolders';
  if (depth === 3) return 'Level 4 deep';
  return 'Level ' + (depth + 1) + ' deep';
}

function getLayerSublabelForRow(depth) {
  if (depth < 0) {
    let parts = currentBasePath.split('/').filter(Boolean);
    const idx = parts.length + depth;
    if (idx >= 0) return parts.slice(0, idx + 1).join('/');
    return '/';
  }
  return getLayerSublabel(depth);
}

function getLayerSublabel(depth) {
  if (depth < 0) {
    const levels = Math.abs(depth);
    return levels === 1 ? 'parent folder' : levels + ' levels up';
  }
  if (depth === 0) return 'top-level folders';
  if (depth === 1) return 'folders inside those';
  if (depth === 2) return 'one level deeper';
  return (depth + 1) + ' levels deep';
}

let homeDir = '';
let smartItems = [];

function el(id) { return document.getElementById(id); }
function txt(e, t) { e.textContent = t; }
function clearChildren(e) { while (e.firstChild) e.removeChild(e.firstChild); }

function createEl(tag, attrs, children) {
  const e = document.createElement(tag);
  if (attrs) {
    Object.entries(attrs).forEach(([k, v]) => {
      if (k === 'className') e.className = v;
      else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
      else if (k === 'textContent') e.textContent = v;
      else if (k === 'checked') e.checked = !!v;
      else e.setAttribute(k, v);
    });
  }
  if (children) (Array.isArray(children) ? children : [children]).forEach(c => {
    if (typeof c === 'string') e.appendChild(document.createTextNode(c));
    else if (c) e.appendChild(c);
  });
  return e;
}

let activeTheme = 'Classic';
let activeLayerTheme = null;

function setLayerThemePresets(colors) {
  const presetsEl = el('presets');
  clearChildren(presetsEl);
  colors.forEach((hex, i) => {
    const wrap = createEl('div', {className: 'preset-wrap'});
    const btn = createEl('div', {className: 'preset' + (hex === currentColor ? ' selected' : ''), 'data-color': hex, style: {background: hex}, draggable: 'true'});
    btn.addEventListener('click', () => selectPreset(hex));
    btn.addEventListener('dragstart', e => { e.dataTransfer.setData('text/plain', hex); e.dataTransfer.effectAllowed = 'copy'; });
    btn.addEventListener('contextmenu', e => { e.preventDefault(); showPresetCtx(e, hex); });
    wrap.appendChild(btn);
    const label = createEl('span', {className: 'preset-name', textContent: 'L' + i});
    wrap.appendChild(label);
    presetsEl.appendChild(wrap);
  });
  // Custom color swatch
  const customWrap = createEl('div', {className: 'preset-wrap'});
  const customBtn = createEl('div', {className: 'preset preset-custom', id: 'customPresetBtn', style: {background: currentColor}});
  const customInput = createEl('input', {type: 'color', value: currentColor});
  customInput.addEventListener('input', e => {
    currentColor = e.target.value;
    customBtn.style.background = currentColor;
    customBtn.classList.add('has-custom-color');
    el('colorWheel').value = currentColor;
    updateColorUI();
    document.querySelectorAll('.preset:not(.preset-custom)').forEach(p => p.classList.remove('selected'));
    customBtn.classList.add('selected');
    setLayerColor(activeLayerDepth, currentColor);
  });
  customBtn.appendChild(customInput);
  customBtn.addEventListener('dragstart', e => { e.dataTransfer.setData('text/plain', currentColor); e.dataTransfer.effectAllowed = 'copy'; });
  customBtn.addEventListener('contextmenu', e => { e.preventDefault(); showPresetCtx(e, currentColor); });
  customBtn.setAttribute('draggable', 'true');
  customWrap.appendChild(customBtn);
  customWrap.appendChild(createEl('span', {className: 'preset-name', textContent: 'Custom'}));
  presetsEl.appendChild(customWrap);
}

function toggleSourceCard(source) {
  const cards = document.querySelectorAll('.source-card');
  const toggles = document.querySelectorAll('.source-toggle');
  const targetCard = document.querySelector('.source-card[data-source="' + source + '"]');
  const targetBtn = document.querySelector('.source-toggle[data-source="' + source + '"]');
  const isOpen = targetCard && targetCard.style.display === 'block';
  // Close all
  cards.forEach(c => { c.style.display = 'none'; });
  toggles.forEach(b => { b.classList.remove('active'); });
  // Open if was closed
  if (!isOpen && targetCard) {
    targetCard.style.display = 'block';
    if (targetBtn) targetBtn.classList.add('active');
  }
}

let aiPaletteLayers = [];
let aiPaletteAccents = [];

function applyAiAsTheme() {
  if (!aiPaletteAccents.length) return;
  THEMES['AI Generated'] = aiPaletteAccents.slice(0, 8);
  // Add pill if not present
  const themesEl = el('themes');
  if (!themesEl.querySelector('[data-ai-theme]')) {
    const btn = createEl('button', {
      className: 'theme-btn',
      textContent: 'AI Generated',
      'data-ai-theme': '1',
      onClick: () => setTheme('AI Generated')
    });
    themesEl.appendChild(btn);
  }
  setTheme('AI Generated');
}

function applyAiAsLayerTheme() {
  if (!aiPaletteLayers.length) return;
  // Deselect all themes
  document.querySelectorAll('#themes .theme-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('#layerThemes .theme-btn').forEach(b => b.classList.remove('active'));
  activeLayerTheme = '__ai__';
  layerEndDepth = layerStartDepth + aiPaletteLayers.length - 1;
  for (let d = 0; d < aiPaletteLayers.length; d++) {
    layerColors[layerStartDepth + d] = aiPaletteLayers[d];
    layerEnabled[layerStartDepth + d] = true;
  }
  currentColor = aiPaletteLayers[0];
  el('colorWheel').value = currentColor;
  setLayerThemePresets(aiPaletteLayers);
  updateColorUI();
  renderLayerTree();
  syncFolderSwatches();
}

function reapplyActiveLayerTheme() {
  if (!activeLayerTheme || !LAYER_THEMES[activeLayerTheme]) return;
  const colors = LAYER_THEMES[activeLayerTheme];
  for (let d = layerStartDepth; d <= layerEndDepth; d++) {
    const idx = d - layerStartDepth;
    const color = idx < colors.length ? colors[idx] : colors[colors.length - 1];
    // Assign color but don't change enabled state
    layerColors[d] = color;
  }
  currentColor = layerColors[layerStartDepth];
  el('colorWheel').value = currentColor;
}

async function init() {
  const res = await fetch('/api/home');
  const data = await res.json();
  homeDir = data.home;

  // Build themes
  const themesEl = el('themes');
  Object.keys(THEMES).forEach(name => {
    const btn = createEl('button', {
      className: 'theme-btn' + (name === activeTheme ? ' active' : ''),
      textContent: name,
      onClick: () => setTheme(name)
    });
    themesEl.appendChild(btn);
  });

  setTheme('Classic');

  // Build layer themes
  const layerThemesEl = el('layerThemes');
  Object.keys(LAYER_THEMES).forEach(name => {
    const colors = LAYER_THEMES[name];
    const btn = createEl('button', {
      className: 'theme-btn',
      onClick: () => {
        // Deselect regular themes, select this layer theme
        document.querySelectorAll('#themes .theme-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('#layerThemes .theme-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        activeLayerTheme = name;
        // Only color existing levels; don't change which are enabled
        for (let d = layerStartDepth; d <= layerEndDepth; d++) {
          const idx = d - layerStartDepth;
          layerColors[d] = colors[Math.min(idx, colors.length - 1)];
        }
        currentColor = colors[0];
        el('colorWheel').value = currentColor;
        // Populate preset grid with the layer theme colors
        setLayerThemePresets(colors);
        updateColorUI();
        renderLayerTree();
        syncFolderSwatches();
        updateFolderCount();
      }
    });
    // Build a mini gradient preview inside the button
    const preview = createEl('span', {style: {
      display: 'inline-flex', gap: '2px', marginRight: '6px', verticalAlign: 'middle'
    }});
    // Show 5 evenly-spaced dots from the 8 colors
    [0, 2, 4, 5, 7].forEach(i => {
      preview.appendChild(createEl('span', {style: {
        display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: colors[i]
      }}));
    });
    btn.appendChild(preview);
    btn.appendChild(document.createTextNode(name));
    layerThemesEl.appendChild(btn);
  });

  // Events
  el('colorWheel').addEventListener('input', e => {
    currentColor = e.target.value; updateColorUI();
    document.querySelectorAll('.preset').forEach(p => p.classList.remove('selected'));
    document.querySelectorAll('.wp-swatch').forEach(p => p.classList.remove('selected'));
    const cb = document.getElementById('customPresetBtn');
    if (cb) { cb.style.background = currentColor; cb.classList.add('has-custom-color'); }
    setLayerColor(activeLayerDepth, currentColor);
  });
  el('opacitySlider').addEventListener('input', e => { txt(el('opacityVal'), e.target.value + '%'); updateFolderPreview(); syncFolderSwatches(); });
  el('smartOpacitySlider').addEventListener('input', e => { txt(el('smartOpacityVal'), e.target.value + '%'); });


  // Initial layer tree render
  renderLayerTree();

  // Auto-load Desktop on startup with depth 0 pre-selected and colored
  layerColors[0] = currentColor;
  layerEnabled[0] = true;
  loadManualFolder(homeDir + '/Desktop', 'Desktop');

  document.querySelectorAll('.topbar-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.topbar-tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      el('panel-' + tab.dataset.tab).classList.add('active');
    });
  });

  el('applyBtn').addEventListener('click', applyManual);
  el('resetBtn').addEventListener('click', resetManual);
  el('scanBtn').addEventListener('click', scanFolder);
  el('applyAllBtn').addEventListener('click', applyAll);
  el('resetAllBtn').addEventListener('click', resetAll);
  // Source toggle buttons
  document.querySelectorAll('.source-toggle').forEach(btn => {
    btn.addEventListener('click', () => toggleSourceCard(btn.dataset.source));
  });
  el('aiUseThemeBtn').addEventListener('click', applyAiAsTheme);
  el('aiUseLayerBtn').addEventListener('click', applyAiAsLayerTheme);
  el('selectAllBtn').addEventListener('click', () => toggleAll(true));
  el('selectNoneBtn').addEventListener('click', () => toggleAll(false));

  // Image upload
  el('imageUpload').addEventListener('change', function() { handleImageUpload(this.files[0]); this.value = ''; });

  // Hex palette
  el('hexGenBtn').addEventListener('click', function() {
    const hex = el('hexInput').value;
    hexGeneratedAccents = generateHexPalette(hex);
    hexGeneratedLayers = generateHexLayerGradient(hex);
    el('hexResults').style.display = 'block';

    function renderHexRow(containerId, colors) {
      const container = el(containerId);
      clearChildren(container);
      colors.forEach(c => {
        container.appendChild(createEl('div', {
          className: 'wp-swatch', 'data-color': c,
          style: {background: c},
          onClick: () => {
            currentColor = c; el('colorWheel').value = c; updateColorUI();
            document.querySelectorAll('.preset').forEach(p => p.classList.remove('selected'));
            document.querySelectorAll('.wp-swatch').forEach(p => p.classList.toggle('selected', p.dataset.color === c));
            setLayerColor(activeLayerDepth, c);
          }
        }));
      });
    }
    renderHexRow('hexSwatches', hexGeneratedAccents);
    renderHexRow('hexLayerSwatches', hexGeneratedLayers);
  });

  el('hexUseThemeBtn').addEventListener('click', function() {
    if (!hexGeneratedAccents.length) return;
    THEMES['Custom Generated'] = hexGeneratedAccents.slice(0, 8);
    const themesEl = el('themes');
    if (!themesEl.querySelector('[data-custom-theme]')) {
      themesEl.appendChild(createEl('button', {
        className: 'theme-btn', textContent: 'Custom Generated',
        'data-custom-theme': '1',
        onClick: () => setTheme('Custom Generated')
      }));
    }
    setTheme('Custom Generated');
  });

  el('hexUseLayerBtn').addEventListener('click', function() {
    if (!hexGeneratedLayers.length) return;
    document.querySelectorAll('#themes .theme-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('#layerThemes .theme-btn').forEach(b => b.classList.remove('active'));
    activeLayerTheme = '__custom__';
    layerEndDepth = layerStartDepth + hexGeneratedLayers.length - 1;
    for (let d = 0; d < hexGeneratedLayers.length; d++) {
      layerColors[layerStartDepth + d] = hexGeneratedLayers[d];
      layerEnabled[layerStartDepth + d] = true;
    }
    currentColor = hexGeneratedLayers[0];
    el('colorWheel').value = currentColor;
    setLayerThemePresets(hexGeneratedLayers);
    updateColorUI();
    renderLayerTree();
    syncFolderSwatches();
  });

  // Smart style pills
  document.querySelectorAll('#smartStylePills .theme-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#smartStylePills .theme-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      smartStyle = btn.dataset.style;
    });
  });
}

function setTheme(name) {
  activeTheme = name;
  activeLayerTheme = null;
  // Deselect layer themes, select regular theme
  document.querySelectorAll('#layerThemes .theme-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('#themes .theme-btn').forEach(b => b.classList.toggle('active', b.textContent === name));
  const colors = THEMES[name];
  const presetsEl = el('presets');
  clearChildren(presetsEl);
  colors.forEach(hex => {
    const wrap = createEl('div', {className: 'preset-wrap'});
    const btn = createEl('div', {className: 'preset', 'data-color': hex, style: {background: hex}, draggable: 'true'});
    btn.addEventListener('click', () => selectPreset(hex));
    btn.addEventListener('dragstart', e => { e.dataTransfer.setData('text/plain', hex); e.dataTransfer.effectAllowed = 'copy'; });
    btn.addEventListener('contextmenu', e => { e.preventDefault(); showPresetCtx(e, hex); });
    wrap.appendChild(btn);
    presetsEl.appendChild(wrap);
  });
  // Custom color swatch as the last grid item
  const customWrap = createEl('div', {className: 'preset-wrap'});
  const customBtn = createEl('div', {className: 'preset preset-custom', id: 'customPresetBtn', style: {background: currentColor}});
  const customInput = createEl('input', {type: 'color', value: currentColor});
  customInput.addEventListener('input', e => {
    currentColor = e.target.value;
    customBtn.style.background = currentColor;
    customBtn.classList.add('has-custom-color');
    el('colorWheel').value = currentColor;
    updateColorUI();
    document.querySelectorAll('.preset:not(.preset-custom)').forEach(p => p.classList.remove('selected'));
    customBtn.classList.add('selected');
    setLayerColor(activeLayerDepth, currentColor);
  });
  customBtn.appendChild(customInput);
  customBtn.addEventListener('dragstart', e => { e.dataTransfer.setData('text/plain', currentColor); e.dataTransfer.effectAllowed = 'copy'; });
  customBtn.addEventListener('contextmenu', e => { e.preventDefault(); showPresetCtx(e, currentColor); });
  customBtn.setAttribute('draggable', 'true');
  customWrap.appendChild(customBtn);
  const customLabel = createEl('span', {className: 'preset-name', textContent: 'Custom'});
  customWrap.appendChild(customLabel);
  presetsEl.appendChild(customWrap);
  selectPreset(colors[0]);
}

function selectPreset(hex) {
  currentColor = hex;
  el('colorWheel').value = hex;
  updateColorUI();
  document.querySelectorAll('.preset').forEach(p => p.classList.toggle('selected', p.dataset.color === hex));
  document.querySelectorAll('.wp-swatch').forEach(p => p.classList.remove('selected'));
  const customBtn = document.getElementById('customPresetBtn');
  if (customBtn) { customBtn.style.background = hex; customBtn.classList.add('has-custom-color'); }
  // Apply to active layer
  setLayerColor(activeLayerDepth, hex);
}

let previewTimer = null;
function updateFolderPreview() {
  clearTimeout(previewTimer);
  const img = el('folderIconImg');
  const spinner = el('previewSpinner');
  img.style.opacity = '0.4';
  spinner.classList.add('visible');
  previewTimer = setTimeout(() => {
    const opacity = parseInt(el('opacitySlider').value) / 100;
    const url = '/api/preview?color=' + encodeURIComponent(currentColor) + '&opacity=' + opacity;
    const loader = new Image();
    loader.onload = function() {
      img.src = url;
      img.style.opacity = '1';
      spinner.classList.remove('visible');
    };
    loader.onerror = function() {
      img.style.opacity = '1';
      spinner.classList.remove('visible');
    };
    loader.src = url;
  }, 150);
  el('folderTintOverlay').style.display = 'none';
}

function syncFolderSwatches() {
  const depth0Color = getColorForFolder(null, 0) || currentColor;
  const depth1Color = getColorForFolder(null, 1) || currentColor;
  const items = el('manualFolderItems');
  if (items) {
    const rows = items.querySelectorAll(':scope > .tree-item');
    rows.forEach((row, i) => {
      const f = manualFolders[i];
      if (!f) return;
      const sw = row.querySelector('.folder-color-pick');
      if (sw && !f.customColor) sw.value = depth0Color;
      if (f.subsLoaded) {
        const subEl = document.getElementById('subs-' + i);
        if (subEl) {
          const subSwatches = subEl.querySelectorAll('.folder-color-pick');
          f.subs.forEach((s, si) => {
            if (!s.customColor && subSwatches[si]) subSwatches[si].value = depth1Color;
          });
        }
      }
    });
  }
  // Update layer tree folder icon tints
  const opacity = parseInt(el('opacitySlider').value) / 100;
  for (let d = layerStartDepth; d <= layerEndDepth; d++) {
    const row = document.querySelector('[data-layer-depth="' + d + '"]');
    if (row) {
      const img = row.querySelector('.layer-folder-img');
      if (img) {
        const effectiveColor = getColorForFolder(null, d);
        if (effectiveColor) {
          img.src = '/api/preview?color=' + encodeURIComponent(effectiveColor) + '&opacity=' + opacity;
        } else {
          img.src = '/api/folder-icon';
        }
      }
      // Update swatch
      const swatch = row.querySelector('.layer-swatch');
      if (swatch && layerColors[d]) {
        swatch.style.background = layerColors[d];
        const dash = swatch.querySelector('.inherit-dash');
        if (dash) dash.style.display = 'none';
        swatch.classList.add('has-color');
        row.classList.add('has-override');
      }
    }
  }
}

function setLayerColor(depth, hex) {
  layerColors[depth] = hex;
  layerEnabled[depth] = true;
  renderLayerTree();
  syncFolderSwatches();
}

function clearLayerColor(depth) {
  for (let d = depth; d <= layerEndDepth; d++) {
    delete layerColors[d];
    layerEnabled[d] = false;
  }
  // Shrink tree: remove this level and below (but keep at least depth 0)
  if (depth > 0) {
    layerEndDepth = depth - 1;
  } else if (depth <= layerStartDepth && depth < 0) {
    layerStartDepth = depth + 1;
  }
  // Keep active layer in bounds
  if (activeLayerDepth > layerEndDepth) activeLayerDepth = layerEndDepth;
  if (activeLayerDepth < layerStartDepth) activeLayerDepth = layerStartDepth;
  renderLayerTree();
  syncFolderSwatches();
}

function renderLayerTree() {
  const tree = el('layerTree');
  clearChildren(tree);
  const opacity = parseInt(el('opacitySlider').value) / 100;

  // Header with location pills
  const header = createEl('div', {className: 'layer-tree-header'});
  const pills = createEl('div', {className: 'layer-loc-pills'});
  const locations = [
    {label: 'Desktop', path: homeDir + '/Desktop'},
    {label: 'Documents', path: homeDir + '/Documents'},
    {label: 'Downloads', path: homeDir + '/Downloads'},
  ];
  // "All" pill
  const allPill = createEl('button', {
    className: 'layer-loc-pill' + (currentBaseLabel === 'All Folders' ? ' active' : ''),
    textContent: 'All',
    onClick: () => loadAllFolders(locations)
  });
  pills.appendChild(allPill);

  locations.forEach(loc => {
    const pill = createEl('button', {
      className: 'layer-loc-pill' + (currentBasePath === loc.path && currentBaseLabel !== 'All Folders' ? ' active' : ''),
      textContent: loc.label,
      onClick: () => loadManualFolder(loc.path, loc.label)
    });
    pills.appendChild(pill);
  });
  const browseBtn = createEl('button', {
    className: 'layer-loc-pill',
    textContent: 'Browse...',
    onClick: async () => {
      try {
        const res = await fetch('/api/pick');
        const data = await res.json();
        if (data.path) loadManualFolder(data.path, displayPath(data.path));
      } catch(e) {}
    }
  });
  pills.appendChild(browseBtn);
  header.appendChild(pills);

  // "Select All" toggle for layer depth levels
  let allLevelsActive = true;
  for (let d = layerStartDepth; d <= layerEndDepth; d++) {
    if (!layerColors[d] || !layerEnabled[d]) { allLevelsActive = false; break; }
  }
  const selectAllBtn = createEl('button', {
    className: 'layer-loc-pill' + (allLevelsActive ? ' active' : ''),
    style: {fontWeight: '600'},
    textContent: allLevelsActive ? 'Deselect All' : 'Select All',
    onClick: () => {
      const newState = !allLevelsActive;
      for (let d = layerStartDepth; d <= layerEndDepth; d++) {
        if (newState) {
          if (!layerColors[d]) layerColors[d] = currentColor;
          layerEnabled[d] = true;
        } else {
          layerEnabled[d] = false;
        }
      }
      renderLayerTree(); syncFolderSwatches(); updateManualButtons(); updateFolderCount();
    }
  });
  header.appendChild(selectAllBtn);
  tree.appendChild(header);

  // Can we go higher?
  const baseParts = currentBasePath.split('/').filter(Boolean);
  const canGoUp = (layerStartDepth > -baseParts.length + 1);
  const canGoDown = true;

  // "+ add parent level" button at top
  const addAboveRow = createEl('div', {className: 'layer-add-row'});
  const addAboveBtn = createEl('button', {
    className: 'layer-add-btn',
    textContent: '+ parent level',
    onClick: () => { layerStartDepth--; reapplyActiveLayerTheme(); renderLayerTree(); syncFolderSwatches(); }
  });
  if (!canGoUp) addAboveBtn.disabled = true;
  addAboveRow.appendChild(addAboveBtn);
  tree.appendChild(addAboveRow);

  // Layer rows
  for (let d = layerStartDepth; d <= layerEndDepth; d++) {
    const indentLevel = d - layerStartDepth;
    const hasColor = !!layerColors[d];
    const effectiveColor = getColorForFolder(null, d);
    const displayColor = effectiveColor || currentColor; // for preview only

    const isActive = (d === activeLayerDepth);
    const row = createEl('div', {
      className: 'layer-row' + (hasColor ? ' has-override' : '') + (effectiveColor ? ' has-color-tint' : '') + (isActive ? ' active-layer' : ''),
      'data-layer-depth': d
    });
    row.addEventListener('click', (function(depth) { return function() { activeLayerDepth = depth; renderLayerTree(); }; })(d));
    row.style.cursor = 'pointer';
    if (effectiveColor) {
      row.style.setProperty('--layer-color', effectiveColor);
      row.style.setProperty('--layer-color-bg', effectiveColor + '18');
    }

    // Indent bars
    const indent = createEl('div', {className: 'layer-indent'});
    for (let b = 0; b < indentLevel; b++) {
      indent.appendChild(createEl('div', {className: 'layer-indent-bar'}));
    }
    row.appendChild(indent);

    // Folder icon preview: tinted if color set, plain default folder if not
    const img = createEl('img', {className: 'layer-folder-img'});
    if (effectiveColor) {
      img.src = '/api/preview?color=' + encodeURIComponent(effectiveColor) + '&opacity=' + opacity;
    } else {
      img.src = '/api/folder-icon';
    }
    row.appendChild(img);

    // Color swatch
    const swatch = createEl('div', {className: 'layer-swatch' + (hasColor ? ' has-color' : '')});
    if (hasColor) { swatch.style.background = layerColors[d]; }
    else { swatch.appendChild(createEl('span', {className: 'inherit-dash', textContent: '+'})); }
    row.appendChild(swatch);

    // Hidden color picker
    const picker = createEl('input', {type: 'color', value: hasColor ? layerColors[d] : currentColor});
    picker.addEventListener('input', (function(depth) { return function() { setLayerColor(depth, this.value); }; })(d));
    row.appendChild(picker);
    swatch.addEventListener('click', (function(p) { return function(e) { e.stopPropagation(); p.click(); }; })(picker));

    // Name and hint
    row.appendChild(createEl('span', {className: 'layer-name', textContent: getLayerLabel(d)}));
    let hintText;
    if (hasColor) hintText = layerColors[d];
    else if (d === 0) hintText = 'uses main color';
    else hintText = 'no color set';
    row.appendChild(createEl('span', {className: 'layer-hint', textContent: hintText}));

    // Clear button
    const clearBtn = createEl('button', {className: 'layer-clear', textContent: '\u00d7'});
    clearBtn.addEventListener('click', (function(depth) { return function(e) { e.stopPropagation(); clearLayerColor(depth); }; })(d));
    row.appendChild(clearBtn);

    // Apply checkbox
    if (layerEnabled[d] === undefined) layerEnabled[d] = (d === 0);
    const cb = createEl('input', {type: 'checkbox', className: 'layer-check', title: 'Include this level when applying'});
    cb.checked = !!layerEnabled[d];
    cb.addEventListener('click', function(e) { e.stopPropagation(); });
    cb.addEventListener('change', (function(depth) { return function() { layerEnabled[depth] = this.checked; syncSubCheckedForDepth(depth, this.checked); updateFolderCount(); }; })(d));
    row.appendChild(cb);


    // Drag drop target
    row.addEventListener('dragover', e => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; row.classList.add('drag-over'); });
    row.addEventListener('dragleave', e => { if (!row.contains(e.relatedTarget)) row.classList.remove('drag-over'); });
    row.addEventListener('drop', (function(depth) { return function(e) {
      e.preventDefault(); row.classList.remove('drag-over');
      const hex = e.dataTransfer.getData('text/plain');
      if (hex && hex.startsWith('#')) setLayerColor(depth, hex);
    }; })(d));

    tree.appendChild(row);
  }

  // Bottom buttons row
  const bottomRow = createEl('div', {className: 'layer-add-row', style: {gap: '8px'}});
  const addBelowBtn = createEl('button', {
    className: 'layer-add-btn',
    textContent: '+ deeper level',
    onClick: () => { layerEndDepth++; reapplyActiveLayerTheme(); renderLayerTree(); syncFolderSwatches(); }
  });
  if (!canGoDown) addBelowBtn.disabled = true;
  bottomRow.appendChild(addBelowBtn);
  tree.appendChild(bottomRow);

  rebuildPresetCtx();
}

function syncSubCheckedForDepth(depth, checked) {
  // depth 0 = top-level manualFolders, depth 1 = their .subs, etc.
  function walk(items, currentDepth) {
    for (const item of items) {
      if (currentDepth === depth) {
        item.checked = checked;
      }
      if (item.subs && item.subs.length && currentDepth < depth) {
        walk(item.subs, currentDepth + 1);
      }
    }
  }
  if (depth === 0) {
    manualFolders.forEach(f => { f.checked = true; });
    el('manualFolderItems').querySelectorAll(':scope > .tree-item > .tree-check').forEach(cb => { cb.checked = checked; });
  } else {
    walk(manualFolders, 0);
  }
  // Sync visible checkboxes in the DOM
  el('manualFolderItems').querySelectorAll('.sub-item .tree-check').forEach(cb => {
    // Walk up to find depth by counting nested subfolder-list ancestors
    let d = 0, node = cb.closest('.subfolder-list');
    while (node) { d++; node = node.parentElement.closest('.subfolder-list'); }
    if (d === depth) {
      cb.checked = checked;
      const swatch = cb.closest('.sub-item').querySelector('.layer-swatch');
      if (swatch) {
        clearChildren(swatch);
        if (checked) {
          const colorDepth = Math.min(d, 5);
          swatch.style.background = getColorForFolder(null, colorDepth) || currentColor;
          swatch.classList.add('has-color');
        } else {
          swatch.style.background = '';
          swatch.classList.remove('has-color');
          swatch.appendChild(createEl('span', {className: 'inherit-dash', textContent: '+'}));
        }
      }
    }
  });
  updateManualButtons();
}

function rebuildPresetCtx() {
  const ctx = el('presetCtx');
  clearChildren(ctx);
  for (let d = layerStartDepth; d <= layerEndDepth; d++) {
    const item = createEl('div', {className: 'preset-ctx-item', 'data-layer': d});
    item.appendChild(createEl('span', {className: 'preset-ctx-dot'}));
    item.appendChild(document.createTextNode('Set as ' + getLayerSublabel(d) + ' color'));
    item.addEventListener('click', (function(depth) { return function() {
      if (ctxColor) setLayerColor(depth, ctxColor);
      el('presetCtx').classList.remove('show');
    }; })(d));
    ctx.appendChild(item);
  }
}

function updateColorUI() {
  txt(el('colorHex'), currentColor); updateFolderPreview();
  syncFolderSwatches();
}

function showStatus(id, msg, type) {
  const s = el(id); s.className = 'status show ' + type; txt(s, msg);
  if (type === 'ok') setTimeout(() => s.classList.remove('show'), 3500);
}
function showStatusSpinner(id, msg, type) {
  const s = el(id); s.className = 'status show ' + type; clearChildren(s);
  s.appendChild(createEl('span', {className: 'spinner'}));
  s.appendChild(document.createTextNode(msg));
}

function showProgress(prefix, current, total) {
  const wrap = el(prefix + 'Progress');
  const bar = el(prefix + 'ProgressBar');
  const text = el(prefix + 'ProgressText');
  wrap.classList.add('show');
  if (total > 0) {
    const pct = Math.round((current / total) * 100);
    bar.style.width = pct + '%';
    text.textContent = current + ' / ' + total + ' folders';
  } else {
    // Indeterminate: just show count
    bar.style.width = '100%';
    bar.style.opacity = '0.5';
    text.textContent = current + ' folders colored...';
  }
}

function hideProgress(prefix) {
  el(prefix + 'Progress').classList.remove('show');
}

function displayPath(path) { return homeDir && path.startsWith(homeDir) ? '~' + path.slice(homeDir.length) : path; }
function resolvePath(input) { return input.startsWith('~') ? homeDir + input.slice(1) : input; }
function getOpacity() { return parseInt(el('opacitySlider').value) / 100; }
function getSmartOpacity() { return parseInt(el('smartOpacitySlider').value) / 100; }

// ── Wallpaper ──

// ── Manual folder list ──
let manualFolders = [];
let includeSubfolders = false;

async function loadAllFolders(locations) {
  currentBasePath = homeDir;
  currentBaseLabel = 'All Folders';
  layerStartDepth = -1;
  layerEndDepth = 2;
  reapplyActiveLayerTheme();

  const container = el('manualFolderList');
  const items = el('manualFolderItems');
  container.style.display = 'block';
  clearChildren(items);

  manualFolders = [];
  locations.forEach((loc, li) => {
    const f = {name: loc.label, path: loc.path, checked: true, customColor: null, subs: [], subsLoaded: false, expanded: false};
    const idx = manualFolders.length;
    manualFolders.push(f);

    const row = createEl('div', {className: 'tree-item'});
    const cb = createEl('input', {type: 'checkbox', className: 'tree-check', checked: true});
    cb.addEventListener('change', () => { f.checked = cb.checked; updateManualButtons(); });
    row.appendChild(cb);
    const swatch = createEl('input', {type: 'color', className: 'folder-color-pick', value: getColorForFolder(null, 0) || currentColor});
    swatch.addEventListener('input', () => { f.customColor = swatch.value; });
    swatch.addEventListener('click', e => { e.stopPropagation(); });
    row.appendChild(swatch);
    row.appendChild(createEl('span', {className: 'tree-name', textContent: loc.label}));

    const arrow = createEl('span', {className: 'folder-expand', textContent: '\u25B6', title: 'Show subfolders'});
    arrow.addEventListener('click', e => { e.stopPropagation(); toggleSubfolders(idx); });
    row.appendChild(arrow);
    items.appendChild(row);

    const subContainer = createEl('div', {className: 'subfolder-list', id: 'subs-' + idx});
    items.appendChild(subContainer);
  });

  txt(el('manualListTitle'), 'All Folders (' + locations.length + ')');
  updateManualButtons();
  renderLayerTree();
  updateFolderCount();
}

async function loadManualFolder(path, label) {
  currentBasePath = path;
  currentBaseLabel = label || displayPath(path);

  const container = el('manualFolderList');
  const items = el('manualFolderItems');
  container.style.display = 'block';
  clearChildren(items);
  items.appendChild(createEl('div', {className: 'empty-msg', textContent: 'Loading...'}));

  const res = await fetch('/api/list?path=' + encodeURIComponent(path));
  const data = await res.json();
  clearChildren(items);

  if (data.error) { items.appendChild(createEl('div', {className: 'empty-msg', textContent: data.error})); return; }
  if (!data.dirs.length) { items.appendChild(createEl('div', {className: 'empty-msg', textContent: 'No subfolders'})); return; }

  txt(el('manualListTitle'), (label || displayPath(path)) + ' (' + data.dirs.length + ')');
  manualFolders = data.dirs.map(d => ({name: d.name, path: d.path, checked: true, customColor: null, subs: [], subsLoaded: false, expanded: false}));
  updateFolderCount();

  manualFolders.forEach((f, i) => {
    const row = createEl('div', {className: 'tree-item'});
    const cb = createEl('input', {type: 'checkbox', className: 'tree-check', checked: true});
    cb.addEventListener('change', () => { f.checked = cb.checked; updateManualButtons(); });
    row.appendChild(cb);

    // Color override swatch (depth 0 = top-level)
    const swatch = createEl('input', {type: 'color', className: 'folder-color-pick', value: getColorForFolder(null, 0), title: 'Set a different color for this folder'});
    swatch.addEventListener('input', () => { f.customColor = swatch.value; });
    swatch.addEventListener('click', e => { e.stopPropagation(); });
    row.appendChild(swatch);

    row.appendChild(createEl('span', {className: 'tree-name', textContent: f.name}));

    // Expand arrow for subfolders
    const arrow = createEl('span', {className: 'folder-expand', textContent: '\u25B6', title: 'Show subfolders'});
    arrow.addEventListener('click', e => { e.stopPropagation(); toggleSubfolders(i); });
    row.appendChild(arrow);

    items.appendChild(row);

    // Subfolder container (hidden initially)
    const subContainer = createEl('div', {className: 'subfolder-list', id: 'subs-' + i});
    items.appendChild(subContainer);
  });
  updateManualButtons();
  renderLayerTree();
}

function renderSubItem(s, parentEl, depth) {
  const row = createEl('div', {className: 'tree-item sub-item'});
  const cb = createEl('input', {type: 'checkbox', className: 'tree-check', checked: s.checked});
  row.appendChild(cb);
  const colorDepth = Math.min(depth, 5);

  // Color picker (hidden, triggered by swatch click)
  const picker = createEl('input', {type: 'color', className: 'folder-color-pick', value: getColorForFolder(null, colorDepth) || currentColor});
  picker.style.display = 'none';
  picker.addEventListener('input', () => { s.customColor = picker.value; swatchEl.style.background = picker.value; swatchEl.classList.add('has-color'); clearChildren(swatchEl); });
  picker.addEventListener('click', e => { e.stopPropagation(); });

  // Visual swatch (layer-swatch style)
  const swatchEl = createEl('div', {className: 'layer-swatch' + (s.checked ? ' has-color' : '')});
  if (s.checked) {
    swatchEl.style.background = getColorForFolder(null, colorDepth) || currentColor;
  } else {
    swatchEl.appendChild(createEl('span', {className: 'inherit-dash', textContent: '+'}));
  }
  swatchEl.addEventListener('click', e => { e.stopPropagation(); picker.click(); });

  cb.addEventListener('change', () => {
    s.checked = cb.checked;
    clearChildren(swatchEl);
    if (cb.checked) {
      const color = s.customColor || getColorForFolder(null, colorDepth) || currentColor;
      swatchEl.style.background = color;
      swatchEl.classList.add('has-color');
    } else {
      swatchEl.style.background = '';
      swatchEl.classList.remove('has-color');
      swatchEl.appendChild(createEl('span', {className: 'inherit-dash', textContent: '+'}));
    }
  });
  row.appendChild(swatchEl);
  row.appendChild(picker);
  row.appendChild(createEl('span', {className: 'tree-name sub-name', textContent: s.name}));

  const arrow = createEl('span', {className: 'folder-expand', textContent: '\u25B6', title: 'Show subfolders'});
  const subContainer = createEl('div', {className: 'subfolder-list', style: {display: 'none'}});

  arrow.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (s.expanded) {
      subContainer.style.display = 'none';
      s.expanded = false;
      arrow.textContent = '\u25B6';
      return;
    }
    s.expanded = true;
    arrow.textContent = '\u25BC';
    subContainer.style.display = 'block';
    if (!s.subsLoaded) {
      clearChildren(subContainer);
      subContainer.appendChild(createEl('div', {className: 'empty-msg sub-loading', textContent: 'Loading...'}));
      const res = await fetch('/api/list?path=' + encodeURIComponent(s.path));
      const data = await res.json();
      clearChildren(subContainer);
      s.subsLoaded = true;
      if (!data.dirs || !data.dirs.length) {
        subContainer.appendChild(createEl('div', {className: 'empty-msg', textContent: 'No subfolders'}));
        return;
      }
      s.subs = data.dirs.map(d => ({name: d.name, path: d.path, checked: !!layerEnabled[depth + 1], customColor: null, subs: [], subsLoaded: false, expanded: false}));
      s.subs.forEach(child => renderSubItem(child, subContainer, depth + 1));
    }
  });
  row.appendChild(arrow);
  parentEl.appendChild(row);
  parentEl.appendChild(subContainer);
}

async function toggleSubfolders(idx) {
  const f = manualFolders[idx];
  const subEl = document.getElementById('subs-' + idx);
  if (!subEl) return;

  if (f.expanded) {
    subEl.style.display = 'none';
    f.expanded = false;
    return;
  }

  f.expanded = true;
  subEl.style.display = 'block';

  if (!f.subsLoaded) {
    clearChildren(subEl);
    subEl.appendChild(createEl('div', {className: 'empty-msg sub-loading', textContent: 'Loading...'}));
    const res = await fetch('/api/list?path=' + encodeURIComponent(f.path));
    const data = await res.json();
    clearChildren(subEl);
    f.subsLoaded = true;

    if (!data.dirs || !data.dirs.length) {
      subEl.appendChild(createEl('div', {className: 'empty-msg', textContent: 'No subfolders'}));
      return;
    }

    f.subs = data.dirs.map(d => ({name: d.name, path: d.path, checked: !!layerEnabled[1], customColor: null, subs: [], subsLoaded: false, expanded: false}));
    f.subs.forEach((s, si) => {
      renderSubItem(s, subEl, 1);
    });
    renderLayerTree();
  }
}

function toggleManualAll(state) {
  manualFolders.forEach(f => { f.checked = state; });
  el('manualFolderItems').querySelectorAll('.tree-check').forEach(cb => { cb.checked = state; });
  updateManualButtons();
}

function updateManualButtons() {
  const anyChecked = manualFolders.some(f => f.checked);
  el('applyBtn').disabled = !anyChecked;
  el('resetBtn').disabled = !anyChecked;
}

let _countAbort = null;
let _lastFolderCount = 0;
function updateFolderCount() {
  if (_countAbort) _countAbort.abort();
  _countAbort = new AbortController();
  const signal = _countAbort.signal;

  // Figure out max enabled depth relative to depth 0
  let maxDepth = 0;
  for (let d = layerStartDepth; d <= layerEndDepth; d++) {
    if (layerEnabled[d] && d > 0) {
      maxDepth = Math.max(maxDepth, d);
    }
  }

  // Check if depth 0 is enabled
  const depth0Enabled = layerEnabled[0];

  // If no deeper levels enabled, show count based on depth 0 status
  if (maxDepth === 0) {
    const label = currentBaseLabel === 'All Folders' ? 'All Folders' : (currentBaseLabel || 'Folders');
    if (depth0Enabled) {
      const checked = manualFolders.filter(f => f.checked).length;
      _lastFolderCount = checked;
      txt(el('manualListTitle'), label + ' (' + checked + ')');
    } else {
      _lastFolderCount = 0;
      txt(el('manualListTitle'), label + ' (0 selected)');
    }
    el('manualStatus').classList.remove('show');
    return;
  }

  const label = currentBaseLabel === 'All Folders' ? 'All Folders' : (currentBaseLabel || 'Folders');
  const checked = manualFolders.filter(f => f.checked);
  txt(el('manualListTitle'), label + ' (' + checked.length + ' top-level, counting subfolders...)');

  // Count subfolders for each checked folder. manualFolders are at depth 0,
  // so to count folders at layer depths 1..maxDepth we use API depth = maxDepth - 1
  const apiDepth = maxDepth - 1;
  const paths = checked.map(f => f.path);
  Promise.all(paths.map(p =>
    fetch('/api/count?path=' + encodeURIComponent(p) + '&depth=' + apiDepth, {signal}).then(r => r.json()).catch(() => ({count: 0}))
  )).then(counts => {
    if (signal.aborted) return;
    const subTotal = counts.reduce((sum, c) => sum + (c.count || 0), 0);
    const total = checked.length + subTotal;
    _lastFolderCount = total;
    let text = label + ' (' + total.toLocaleString() + ' folders)';
    txt(el('manualListTitle'), text);
    if (total > 1000) {
      showStatus('manualStatus', 'Warning: ' + total.toLocaleString() + ' folders selected. Applying colors will take a while.', 'err');
    } else {
      el('manualStatus').classList.remove('show');
    }
  }).catch(() => {});
}

// ── Manual apply/reset ──
async function applyManual() {
  const selected = manualFolders.filter(f => f.checked);
  if (!selected.length) { showStatus('manualStatus', 'Select at least one folder.', 'err'); return; }

  if (_lastFolderCount > 1000) {
    if (!confirm('You are about to color ' + _lastFolderCount.toLocaleString() + ' folders. This will take a while. Continue?')) return;
  }

  const btn = el('applyBtn'); btn.disabled = true; txt(btn, 'Applying...');
  const opacity = getOpacity();
  let ok = 0, fail = 0;
  showProgress('manual', 0, 0);

  // Check if any layer colors are set for depths > 0
  const hasDeepLayers = Object.keys(layerColors).some(d => parseInt(d) > 0 && layerEnabled[parseInt(d)]);

  for (const f of selected) {
    const color = getColorForFolder(f, 0);
    if (color) {
      try {
        const res = await fetch('/api/apply', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({path: f.path, color, opacity})
        });
        const data = await res.json();
        if (data.ok) ok++; else fail++;
      } catch(e) { fail++; }
    }
    showProgress('manual', ok, 0);

    // Apply layer colors to subfolders via the batch endpoint
    if (hasDeepLayers) {
      // Build layers dict for depths > 0 that are enabled
      const batchLayers = {};
      for (let d = 0; d <= layerEndDepth; d++) {
        if (d > 0 && layerColors[d] && layerEnabled[d]) {
          batchLayers[String(d - 1)] = layerColors[d];  // shift: depth 1 in UI = depth 0 in children
        }
      }
      if (Object.keys(batchLayers).length > 0) {
        try {
          const res = await fetch('/api/set-layers', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({path: f.path, layers: batchLayers, opacity})
          });
          const data = await res.json();
          if (data.ok) ok += data.applied || 0;
          showProgress('manual', ok, 0);
        } catch(e) { fail++; }
      }
    }

    // Handle individually expanded subfolders
    if (f.expanded && f.subs.length) {
      // Apply custom colors to checked subs
      for (const s of f.subs.filter(s => s.checked && s.customColor)) {
        try {
          const res = await fetch('/api/apply', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({path: s.path, color: s.customColor, opacity})
          });
          const data = await res.json();
          if (data.ok) ok++; else fail++;
          showProgress('manual', ok, 0);
        } catch(e) { fail++; }
      }
      // Reset unchecked subs that the batch may have colored
      if (hasDeepLayers) {
        const unchecked = f.subs.filter(s => !s.checked).map(s => s.path);
        if (unchecked.length) {
          try {
            await fetch('/api/reset-batch', {
              method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({paths: unchecked})
            });
          } catch(e) {}
        }
      }
    }
  }

  const msg = ok + ' folder' + (ok !== 1 ? 's' : '') + ' colored' + (fail ? ', ' + fail + ' failed' : '') + '. Check Finder.';
  showStatus('manualStatus', msg, fail ? 'err' : 'ok');
  hideProgress('manual');
  btn.disabled = false; txt(btn, 'Apply Color');
}

async function resetManual() {
  const selected = manualFolders.filter(f => f.checked);
  if (!selected.length) { showStatus('manualStatus', 'Select at least one folder.', 'err'); return; }

  const btn = el('resetBtn'); btn.disabled = true; txt(btn, 'Resetting...');
  let count = 0;

  for (const f of selected) {
    try {
      const res = await fetch('/api/reset', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({path: f.path, recursive: true}) });
      const data = await res.json();
      count += data.count || 1;
    } catch(e) { count++; }
  }
  showStatus('manualStatus', count + ' folder' + (count !== 1 ? 's' : '') + ' reset to default.', 'ok');
  btn.disabled = false; txt(btn, 'Reset to Default');
}

// ── Smart ──
let smartStyle = 'intuitive';

async function scanFolder() {
  const path = resolvePath(el('smartPath').value.trim() || '~/Desktop');
  showStatusSpinner('smartStatus', 'Scanning...', 'info');
  const res = await fetch('/api/scan?path=' + encodeURIComponent(path) + '&depth=3&style=' + smartStyle);
  const data = await res.json();
  if (data.error) { showStatus('smartStatus', data.error, 'err'); return; }
  smartItems = []; flattenTree(data.tree);
  el('smartResultsSection').style.display = 'block';
  txt(el('folderCount'), '(' + smartItems.length + ' folders)');
  renderSmartTree(); el('smartStatus').classList.remove('show');
}

function flattenTree(tree) {
  tree.forEach(item => {
    smartItems.push({name: item.name, path: item.path, color: item.color, depth: item.depth, checked: true});
    if (item.children) flattenTree(item.children);
  });
}

function toggleAll(state) {
  smartItems.forEach(item => { item.checked = state; });
  document.querySelectorAll('.tree-check').forEach(cb => { cb.checked = state; });
  updateSelectedCount();
}

function updateSelectedCount() {
  const count = smartItems.filter(s => s.checked).length;
  txt(el('folderCount'), '(' + count + ' of ' + smartItems.length + ' selected)');
}

function renderSmartTree() {
  const c = el('smartTree'); clearChildren(c);
  smartItems.forEach((item, i) => {
    const row = createEl('div', {className: 'tree-item', style: {paddingLeft: (16 + item.depth * 16) + 'px'}});
    for (let d = 0; d < item.depth; d++) row.appendChild(createEl('span', {className: 'tree-depth-bar'}));
    const cb = createEl('input', {type: 'checkbox', className: 'tree-check'});
    cb.checked = item.checked;
    cb.addEventListener('change', e => { smartItems[i].checked = e.target.checked; updateSelectedCount(); });
    row.appendChild(cb);
    const sw = createEl('input', {type: 'color', className: 'tree-swatch', value: item.color});
    sw.addEventListener('change', e => { smartItems[i].color = e.target.value; });
    row.appendChild(sw);
    row.appendChild(createEl('span', {className: 'tree-name', textContent: item.name}));
    row.appendChild(createEl('span', {className: 'tree-path', textContent: displayPath(item.path)}));
    c.appendChild(row);
  });
  updateSelectedCount();
}

async function applyAll() {
  const selected = smartItems.filter(s => s.checked);
  if (!selected.length) { showStatus('smartStatus', 'No folders selected.', 'err'); return; }
  const total = selected.length; const opacity = getSmartOpacity();
  showProgress('smart', 0, total);
  for (let i = 0; i < total; i += 5) {
    const batch = selected.slice(i, i + 5);
    await fetch('/api/apply-batch', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({items: batch, opacity}) });
    showProgress('smart', Math.min(i + 5, total), total);
  }
  hideProgress('smart');
  showStatus('smartStatus', total + ' folders colored. Check Finder.', 'ok');
}

async function resetAll() {
  const selected = smartItems.filter(s => s.checked);
  if (!selected.length) { showStatus('smartStatus', 'No folders selected.', 'err'); return; }
  showStatusSpinner('smartStatus', 'Resetting ' + selected.length + ' folders...', 'info');
  await fetch('/api/reset-batch', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({paths: selected.map(s => s.path)}) });
  showStatus('smartStatus', selected.length + ' folders reset to default.', 'ok');
}

// ── Preset context menu ──
let ctxColor = null;
function showPresetCtx(e, hex) {
  ctxColor = hex;
  const ctx = el('presetCtx');
  ctx.querySelectorAll('.preset-ctx-dot').forEach(dot => { dot.style.background = hex; });
  ctx.style.left = e.clientX + 'px';
  ctx.style.top = e.clientY + 'px';
  ctx.classList.add('show');
}
document.addEventListener('click', () => { el('presetCtx').classList.remove('show'); });

// ── Hex palette generation (JS only) ──
function hexToHSL(hex) {
  hex = hex.replace('#', '');
  const r = parseInt(hex.substring(0, 2), 16) / 255;
  const g = parseInt(hex.substring(2, 4), 16) / 255;
  const b = parseInt(hex.substring(4, 6), 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h, s, l = (max + min) / 2;
  if (max === min) { h = s = 0; }
  else {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
    else if (max === g) h = ((b - r) / d + 2) / 6;
    else h = ((r - g) / d + 4) / 6;
  }
  return [h * 360, s * 100, l * 100];
}

function hslToHex(h, s, l) {
  h = ((h % 360) + 360) % 360;
  s = Math.max(0, Math.min(100, s)) / 100;
  l = Math.max(0, Math.min(100, l)) / 100;
  const a = s * Math.min(l, 1 - l);
  const f = n => {
    const k = (n + h / 30) % 12;
    const color = l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
    return Math.round(255 * color).toString(16).padStart(2, '0');
  };
  return '#' + f(0) + f(8) + f(4);
}

function generateHexPalette(hex) {
  const [h, s, l] = hexToHSL(hex);
  return [
    hslToHex(h, s, l),                    // original
    hslToHex(h + 30, s, l),               // analogous +
    hslToHex(h - 30, s, l),               // analogous -
    hslToHex(h + 180, s, l),              // complementary
    hslToHex(h + 150, s * 0.8, l + 5),    // split-comp +
    hslToHex(h + 210, s * 0.8, l + 5),    // split-comp -
    hslToHex(h, s * 0.6, l + 15),         // tint
    hslToHex(h, s * 0.6, l - 15),         // shade
  ];
}

function generateHexLayerGradient(hex) {
  const [h, s, l] = hexToHSL(hex);
  const result = [];
  for (let i = 0; i < 8; i++) {
    const t = i / 7;
    const li = 22 + t * 52;  // 22% to 74% lightness (stays in reproducible range)
    const si = Math.max(s - t * s * 0.3, s * 0.35);
    result.push(hslToHex(h, si, li));
  }
  return result;
}

let hexGeneratedAccents = [];
let hexGeneratedLayers = [];

// ── Image upload handler ──
async function handleImageUpload(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async function(e) {
    const dataUrl = e.target.result;
    try {
      const res = await fetch('/api/upload-palette', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({image: dataUrl})
      });
      const data = await res.json();
      if (data.error) return;
      el('uploadResults').style.display = 'block';

      function renderSwatchRow(containerId, colors) {
        const container = el(containerId);
        clearChildren(container);
        colors.forEach(hex => {
          container.appendChild(createEl('div', {
            className: 'wp-swatch', 'data-color': hex,
            style: {background: hex},
            onClick: () => {
              currentColor = hex; el('colorWheel').value = hex; updateColorUI();
              document.querySelectorAll('.preset').forEach(p => p.classList.remove('selected'));
              document.querySelectorAll('.wp-swatch').forEach(p => p.classList.toggle('selected', p.dataset.color === hex));
              setLayerColor(activeLayerDepth, hex);
            }
          }));
        });
      }
      renderSwatchRow('uploadSwatches', data.colors || []);
      renderSwatchRow('uploadContrastSwatches', data.suggested || []);
    } catch(e) {}
  };
  reader.readAsDataURL(file);
}

// ── Poll for externally-set layers (from /folder-colors skill) ──
let lastLayersVersion = 0;
function pollForLayers() {
  fetch('/api/get-layers?since=' + lastLayersVersion)
    .then(r => r.json())
    .then(data => {
      if (data.layers && data.version > lastLayersVersion) {
        lastLayersVersion = data.version;
        const entries = Object.entries(data.layers);
        const layerArr = entries.sort((a,b) => parseInt(a[0]) - parseInt(b[0])).map(e => e[1]);
        const accents = data.accents || [];
        const desc = data.description || '';

        // Store AI palette data
        aiPaletteLayers = layerArr;
        aiPaletteAccents = accents;

        // Populate the AI Palette card
        el('aiPaletteHint').style.display = 'none';
        el('aiPaletteResults').style.display = 'block';
        el('aiPaletteDesc').textContent = desc ? '"' + desc + '"' : '';

        function renderAiSwatches(containerId, colors) {
          const container = el(containerId);
          clearChildren(container);
          colors.forEach(hex => {
            container.appendChild(createEl('div', {
              className: 'wp-swatch', 'data-color': hex,
              style: {background: hex},
              onClick: () => {
                currentColor = hex; el('colorWheel').value = hex; updateColorUI();
                document.querySelectorAll('.preset').forEach(p => p.classList.remove('selected'));
                document.querySelectorAll('.wp-swatch').forEach(p => p.classList.toggle('selected', p.dataset.color === hex));
                setLayerColor(activeLayerDepth, hex);
              }
            }));
          });
        }
        renderAiSwatches('aiAccentSwatches', accents);
        renderAiSwatches('aiLayerSwatches', layerArr);

        // Force-open the AI Palette card (don't toggle, always open)
        document.querySelectorAll('.source-card').forEach(c => { c.style.display = 'none'; });
        document.querySelectorAll('.source-toggle').forEach(b => { b.classList.remove('active'); });
        el('aiPaletteCard').style.display = 'block';
        const aiBtn = document.querySelector('.source-toggle[data-source="aiPalette"]');
        if (aiBtn) aiBtn.classList.add('active');

        const descMsg = desc ? ' for "' + desc + '"' : '';
        showStatus('manualStatus', 'AI palette generated' + descMsg + '. Use the buttons to apply.', 'ok');
      }
    })
    .catch(() => {});
}
setInterval(pollForLayers, 2000);
pollForLayers();

// Heartbeat: tell server we're still here
setInterval(() => { fetch('/api/heartbeat').catch(() => {}); }, 4000);

// Welcome banner (shows once, dismissed with localStorage)
(function() {
  var banner = document.getElementById('welcomeBanner');
  var closeBtn = document.getElementById('welcomeBannerClose');
  if (!localStorage.getItem('fc_welcome_dismissed')) {
    banner.style.display = 'flex';
  }
  closeBtn.addEventListener('click', function() {
    banner.style.display = 'none';
    localStorage.setItem('fc_welcome_dismissed', '1');
  });
})();

init();
</script>
</body>
</html>
"""

# ── Main ────────────────────────────────────────────────────────────────────

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
