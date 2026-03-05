#!/usr/bin/env python3
"""Open multiple color-coded Terminal.app windows tiled across the screen."""

import argparse
import json
import math
import os
import subprocess
import time
import sys


# Gradient ramps derived from folder-colors LAYER_THEMES.
# Each mode goes from darkest to lightest, like the folder-colors layer themes.
# Darkened to terminal-safe range (readable with light text) but with clear gradient steps.
COLOR_MODES = {
    "ocean": [
        "#0a2437",  # Abyss
        "#0d344c",  # Deep Sea
        "#124460",  # Marine
        "#1d5474",  # Steel
        "#2c5f80",  # Cerulean
        "#3a6a8c",  # Surf
    ],
    "forest": [
        "#0a2414",  # Pine
        "#10351e",  # Evergreen
        "#1a442a",  # Moss
        "#245436",  # Jade
        "#306444",  # Canopy
        "#3c7454",  # Fern
    ],
    "sunset": [
        "#3a140c",  # Ember
        "#541c10",  # Brick
        "#6a2818",  # Terracotta
        "#7a3520",  # Clay
        "#8a442c",  # Copper
        "#985438",  # Sandstone
    ],
    "berry": [
        "#240a2a",  # Plum
        "#361440",  # Grape
        "#461e54",  # Orchid
        "#582a68",  # Violet
        "#6a367c",  # Amethyst
        "#7c4290",  # Mulberry
    ],
    "earth": [
        "#1e1410",  # Espresso
        "#302418",  # Walnut
        "#3e3020",  # Umber
        "#4c3c28",  # Bronze
        "#5a4832",  # Caramel
        "#68543c",  # Tan
    ],
    "mono": [
        "#141414",  # Onyx
        "#1e1e1e",  # Charcoal
        "#2a2a2a",  # Graphite
        "#363636",  # Slate
        "#424242",  # Pewter
        "#4e4e4e",  # Ash
    ],
    "warm": [
        "#3a100a",  # Garnet
        "#4e1810",  # Cherry
        "#641e14",  # Cayenne
        "#7a2818",  # Sienna
        "#8e3420",  # Rust
        "#a04028",  # Cinnabar
    ],
    "cool": [
        "#0a1438",  # Midnight
        "#10204c",  # Navy
        "#182c60",  # Cobalt
        "#203a74",  # Royal
        "#2c4888",  # Sapphire
        "#38569c",  # Lapis
    ],
    "classic": [
        "#C0392B", "#D35400", "#D4A017", "#27AE60",
        "#2980B9", "#8E44AD", "#C2185B", "#16A085",
    ],
    "stealth": [
        "#2C3E50", "#34495E", "#1A1A2E", "#3D3D3D",
        "#4A4A4A", "#2D2D2D", "#1B2631", "#283747",
    ],
    "tactical": [
        "#556B2F", "#8B7355", "#4A5D23", "#6B4226",
        "#3B3B3B", "#8B4513", "#2F4F4F", "#704214",
    ],
    "carbon": [
        "#1C1C1C", "#333333", "#4D4D4D", "#666666",
        "#2C2C2C", "#3D3D3D", "#1A1A1A", "#555555",
    ],
    "midnight": [
        "#0D1B2A", "#1B263B", "#415A77", "#778DA9",
        "#2A3950", "#1F3044", "#324A5F", "#0B132B",
    ],
    "mermaid": [
        "#2EC4B6", "#6A89CC", "#82589F", "#3B9B8F",
        "#48DBDB", "#7E57C2", "#5CA0D3", "#38ADA9",
    ],
    "pastel": [
        "#FFB5C2", "#B5D8FF", "#C4B5FF", "#B5FFD9",
        "#FFE4B5", "#E8B5FF", "#B5F0FF", "#FFD1B5",
    ],
    "neutrals": [
        "#C4A882", "#B8A089", "#A69279", "#D4C4AA",
        "#B5A590", "#C9B99A", "#A89070", "#BCA888",
    ],
    "mint": [
        "#3EB489", "#48C9B0", "#76D7C4", "#A3E4D7",
        "#1ABC9C", "#17A589", "#138D75", "#0E6655",
    ],
    "moody": [
        "#9E2C21", "#305853", "#B06821", "#511B18",
        "#1B2A30", "#3B3B3B", "#5C4033", "#2C3E50",
    ],
    "leather": [
        "#8B5E3C", "#A0522D", "#6B4226", "#556B2F",
        "#8F9779", "#D2B48C", "#C19A6B", "#4A3728",
    ],
    "claude": [
        "#8B4513",  # Terracotta (icon orange)
        "#1A1028",  # Deep Violet
        "#3A6B8C",  # Steel Blue (links)
        "#2A0E0E",  # Oxblood
        "#7A6840",  # Parchment (chat warmth)
        "#0D1B2A",  # Abyss
        "#4A7A5A",  # Sage (green accent)
        "#5B3A8C",  # Violet (UI accent)
    ],
}

DEFAULT_MODE = "ocean"
CONFIG_PATH = os.path.expanduser("~/.config/lite-tools/multiple-terminals.json")

# Vertical gap between rows. Set to 0 for seamless tiling. Terminal title bars
# are included within window bounds, so no gap is needed.
TITLEBAR_GAP = 0



BROWSER_APPS = ["Google Chrome", "Safari", "Firefox", "Arc", "Brave Browser",
                 "Microsoft Edge", "Chromium", "Vivaldi", "Opera"]

HUB_LAYOUTS = {"hub-sides", "hub-side-left", "hub-side-right", "hub-grid", "hub-top", "hub-stack", "hub-columns"}


def find_browser_window():
    """Find the first visible browser window on the current desktop.

    Returns dict with app name and window index, or None.
    """
    all_windows = get_all_visible_windows()
    for w in all_windows:
        if w["app"] in BROWSER_APPS:
            return w
    return None


def open_default_browser():
    """Open the default browser and return its app name after it appears."""
    try:
        subprocess.run(["open", "-a", "Safari", "about:blank"],
                       capture_output=True, timeout=5)
        time.sleep(1.5)
        win = find_browser_window()
        if win:
            return win
    except Exception:
        pass
    # Fallback: try Chrome
    try:
        subprocess.run(["open", "-a", "Google Chrome", "about:blank"],
                       capture_output=True, timeout=5)
        time.sleep(1.5)
        return find_browser_window()
    except Exception:
        return None


def get_or_open_browser():
    """Find an existing browser window, or open one. Returns window dict or None."""
    win = find_browser_window()
    if win:
        return win
    return open_default_browser()


def calculate_hub_layout(term_count, variant, bounds, row_gap=0):
    """Calculate layout with a central browser hub and terminals around it.

    Returns (browser_rect, terminal_rects).
    """
    x0, y0, x1, y1 = bounds
    width = x1 - x0
    height = y1 - y0
    term_rects = []

    if variant == "hub-sides":
        # Browser in center column, terminals split evenly on left and right
        left_count = term_count // 2
        right_count = term_count - left_count
        # Browser gets 45% center, terminals split the rest
        browser_w = int(width * 0.45)
        side_w = (width - browser_w) // 2
        browser_left = x0 + side_w
        browser_rect = (browser_left, y0, browser_left + browser_w, y1)

        # Left terminals stacked vertically
        if left_count > 0:
            total_gap = row_gap * (left_count - 1)
            usable = height - total_gap
            th = usable // left_count
            for i in range(left_count):
                t = y0 + i * (th + row_gap)
                b = t + th if i < left_count - 1 else y1
                term_rects.append((x0, t, browser_left, b))

        # Right terminals stacked vertically
        if right_count > 0:
            total_gap = row_gap * (right_count - 1)
            usable = height - total_gap
            th = usable // right_count
            right_x = browser_left + browser_w
            for i in range(right_count):
                t = y0 + i * (th + row_gap)
                b = t + th if i < right_count - 1 else y1
                term_rects.append((right_x, t, x1, b))

    elif variant == "hub-columns":
        # Browser in center column, terminals as full-height columns on each side
        left_count = term_count // 2
        right_count = term_count - left_count
        # Browser gets ~35% center, each side splits the remainder equally
        browser_w = int(width * 0.35)
        side_w = (width - browser_w) // 2
        browser_left = x0 + side_w
        browser_rect = (browser_left, y0, browser_left + browser_w, y1)

        # Left columns (full height each)
        if left_count > 0:
            col_w = side_w // left_count
            for i in range(left_count):
                l = x0 + i * col_w
                r = x0 + (i + 1) * col_w if i < left_count - 1 else browser_left
                term_rects.append((l, y0, r, y1))

        # Right columns (full height each)
        if right_count > 0:
            right_x = browser_left + browser_w
            right_total = x1 - right_x
            col_w = right_total // right_count
            for i in range(right_count):
                l = right_x + i * col_w
                r = right_x + (i + 1) * col_w if i < right_count - 1 else x1
                term_rects.append((l, y0, r, y1))

    elif variant == "hub-side-left":
        # Browser on left 55%, terminals stacked on right
        browser_w = int(width * 0.55)
        browser_rect = (x0, y0, x0 + browser_w, y1)
        right_x = x0 + browser_w
        if term_count > 0:
            total_gap = row_gap * (term_count - 1)
            usable = height - total_gap
            th = usable // term_count
            for i in range(term_count):
                t = y0 + i * (th + row_gap)
                b = t + th if i < term_count - 1 else y1
                term_rects.append((right_x, t, x1, b))

    elif variant == "hub-side-right":
        # Browser on right 55%, terminals stacked on left
        browser_w = int(width * 0.55)
        browser_left = x1 - browser_w
        browser_rect = (browser_left, y0, x1, y1)
        if term_count > 0:
            total_gap = row_gap * (term_count - 1)
            usable = height - total_gap
            th = usable // term_count
            for i in range(term_count):
                t = y0 + i * (th + row_gap)
                b = t + th if i < term_count - 1 else y1
                term_rects.append((x0, t, browser_left, b))

    elif variant == "hub-grid":
        # Browser in center, terminals in corners (2x2 or more around edges)
        browser_w = int(width * 0.40)
        browser_h = int(height * 0.45)
        bx = x0 + (width - browser_w) // 2
        by = y0 + (height - browser_h) // 2
        browser_rect = (bx, by, bx + browser_w, by + browser_h)

        # Place terminals around the edges
        # Top-left, top-right, bottom-left, bottom-right, then extras across top/bottom
        positions = []
        # Corners first
        positions.append((x0, y0, bx, by))                         # top-left
        positions.append((bx + browser_w, y0, x1, by))             # top-right
        positions.append((x0, by + browser_h + row_gap, bx, y1))   # bottom-left
        positions.append((bx + browser_w, by + browser_h + row_gap, x1, y1))  # bottom-right
        # Top center
        positions.append((bx, y0, bx + browser_w, by))             # top-center
        # Bottom center
        positions.append((bx, by + browser_h + row_gap, bx + browser_w, y1))  # bottom-center
        # Left center
        positions.append((x0, by, bx, by + browser_h))             # left-center
        # Right center
        positions.append((bx + browser_w, by, x1, by + browser_h)) # right-center

        for i in range(min(term_count, len(positions))):
            term_rects.append(positions[i])

        # If more terminals than positions, stack extras across bottom
        if term_count > len(positions):
            extra = term_count - len(positions)
            ew = width // extra
            for i in range(extra):
                l = x0 + i * ew
                r = x0 + (i + 1) * ew if i < extra - 1 else x1
                term_rects.append((l, by + browser_h + row_gap, r, y1))

    elif variant == "hub-top":
        # Browser takes bottom portion, terminals in a row across the top
        split = int(height * 0.38)
        browser_rect = (x0, y0 + split + row_gap, x1, y1)

        # Terminals across top row
        tw = width // max(1, term_count)
        for i in range(term_count):
            l = x0 + i * tw
            r = x0 + (i + 1) * tw if i < term_count - 1 else x1
            term_rects.append((l, y0, r, y0 + split))

    elif variant == "hub-stack":
        # Browser top, terminals stacked below in a row
        split = int(height * 0.55)
        browser_rect = (x0, y0, x1, y0 + split)

        # Terminals across bottom row
        tw = width // max(1, term_count)
        for i in range(term_count):
            l = x0 + i * tw
            r = x0 + (i + 1) * tw if i < term_count - 1 else x1
            term_rects.append((l, y0 + split + row_gap, r, y1))

    else:
        browser_rect = (x0, y0, x1, y1)

    return browser_rect, term_rects


TERMINAL_THEMES = [
    "Basic", "Pro", "Homebrew", "Ocean", "Red Sands",
    "Grass", "Man Page", "Novel", "Silver Aerogel",
    "Solid Colors", "Clear Dark", "Clear Light",
]


def hex_to_terminal_rgb(hex_color):
    """Convert a hex color string to Terminal.app's 16-bit RGB format."""
    hex_color = hex_color.strip().lstrip("#")
    # Handle rgb() format: extract numbers
    if hex_color.startswith("rgb"):
        import re
        nums = re.findall(r'\d+', hex_color)
        if len(nums) >= 3:
            return (int(nums[0]) * 257, int(nums[1]) * 257, int(nums[2]) * 257)
        return (0, 0, 0)
    if len(hex_color) < 6:
        return (0, 0, 0)
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return (r * 257, g * 257, b * 257)


def text_color_for_bg(hex_color):
    """Return a high-contrast text color (16-bit RGB) for the given background."""
    h = hex_color.strip().lstrip("#")
    if h.startswith("rgb") or len(h) < 6:
        return (62965, 63993, 62965)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    # Perceived luminance
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    if lum < 128:
        # Dark background: light text (slightly warm white)
        return (62965, 63993, 62965)  # ~F5F9F5
    else:
        # Light background: dark text
        return (5140, 5140, 5654)  # ~141416


def get_screen_bounds():
    """Get usable screen bounds, detecting dock/menu bar auto-hide."""
    screen_bounds = None
    try:
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "Finder" to get bounds of window of desktop'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            if len(parts) == 4:
                screen_bounds = tuple(int(p) for p in parts)
    except Exception:
        pass

    if not screen_bounds:
        screen_bounds = (0, 0, 1440, 900)

    left, top, right, bottom = screen_bounds

    # Terminal.app clamps its minimum y to ~32 (title bar), so always reserve
    # at least 32px from the top regardless of menu bar auto-hide.
    menu_offset = 32
    dock_offset = 0
    try:
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to tell dock preferences to '
             'return {autohide, autohide menu bar}'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            dock_autohide = parts[0].strip() == "true" if len(parts) > 0 else False
            if not dock_autohide:
                dock_offset = 70
    except Exception:
        dock_offset = 70

    return (left, top + menu_offset, right, bottom - dock_offset)


def get_terminal_window_count():
    """Get the number of valid Terminal.app windows (excludes ghost windows)."""
    return len(get_valid_window_indices())


def get_valid_window_indices():
    """Get list of valid Terminal.app window indices on the active desktop.

    Filters out ghost windows (write test) and windows on other Spaces (visible check).
    Only returns windows visible on the current desktop.
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", """
tell application "Terminal"
    set indices to ""
    repeat with i from 1 to (count of windows)
        try
            set n to name of window i
            set b to bounds of window i
            set v to visible of window i
            if v then
                -- Test that we can actually modify this window
                set bounds of window i to b
                set indices to indices & i & ","
            end if
        end try
    end repeat
    return indices
end tell"""],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            raw = result.stdout.strip().rstrip(",")
            if raw:
                return [int(x) for x in raw.split(",")]
    except Exception:
        pass
    return []


def get_all_visible_windows():
    """Get all visible windows on the active desktop from all applications.

    Uses CoreGraphics kCGWindowListOptionOnScreenOnly to only return windows
    on the current Space. Returns list of dicts with app name and window ID.
    Excludes Terminal (handled separately), Finder, Dock, and small windows.
    """
    try:
        import Quartz
    except ImportError:
        return []

    skip_apps = {"Finder", "Dock", "Notification Center", "Control Center",
                 "WindowManager", "Terminal", "Spotlight"}
    options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    cg_windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)

    # Group by app to determine per-app window index
    app_counts = {}
    windows = []
    for w in cg_windows:
        owner = w.get("kCGWindowOwnerName", "")
        layer = w.get("kCGWindowLayer", 0)
        bounds = w.get("kCGWindowBounds", {})
        bw = bounds.get("Width", 0)
        bh = bounds.get("Height", 0)

        # Layer 0 = normal windows, skip tiny windows and excluded apps
        if layer != 0 or bw < 100 or bh < 100 or owner in skip_apps:
            continue

        app_counts[owner] = app_counts.get(owner, 0) + 1
        windows.append({
            "app": owner,
            "index": app_counts[owner],
            "name": w.get("kCGWindowName", ""),
        })

    return windows


def get_window_min_size(app_name, window_index):
    """Detect the minimum size of an app window by shrinking it and reading back.

    Temporarily resizes the window very small, reads the actual size the app
    allowed, then returns (min_width, min_height).
    """
    escaped_app = app_name.replace('"', '\\"')
    script = f"""
tell application "System Events"
    tell process "{escaped_app}"
        set w to window {window_index}
        set origSize to size of w
        set origPos to position of w
        set size of w to {{100, 100}}
        delay 0.15
        set actualSize to size of w
        set size of w to origSize
        set position of w to origPos
        return (item 1 of actualSize) & "," & (item 2 of actualSize)
    end tell
end tell"""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(",")
            if len(parts) == 2:
                return (int(parts[0].strip()), int(parts[1].strip()))
    except Exception:
        pass
    return (500, 300)


def resize_app_window(app_name, window_index, rect):
    """Resize a window from any application.

    First tries the app's own 'set bounds' (works reliably for Chrome, Safari,
    Firefox, etc.). Falls back to System Events for apps without scriptable bounds.
    """
    left, top, right, bottom = rect
    escaped_app = app_name.replace('"', '\\"')

    # Try app-native set bounds first (most reliable for browsers)
    script = f"""
tell application "{escaped_app}"
    set bounds of window {window_index} to {{{left}, {top}, {right}, {bottom}}}
end tell"""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return True
    except Exception:
        pass

    # Fallback: System Events (for apps without scriptable bounds)
    w = right - left
    h = bottom - top
    script = f"""
tell application "System Events"
    tell process "{escaped_app}"
        set w to window {window_index}
        set size of w to {{{w}, {h}}}
        delay 0.1
        set position of w to {{{left}, {top}}}
        delay 0.1
        set position of w to {{{left}, {top}}}
    end tell
end tell"""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def restyle_existing_window(window_index, rect, color_hex=None, theme=None):
    """Restyle an existing Terminal.app window (color/theme + bounds). No new window opened.

    Uses Terminal.app's set bounds which has stable window indices (unlike System Events
    whose indices shift when windows are reordered). Terminal.app clamps minimum y to 32
    (menu bar height), so screen bounds should start at y>=32.
    """
    left, top, right, bottom = rect

    script_lines = [
        'tell application "Terminal"',
        '    activate',
        f'    set targetWindow to window {window_index}',
    ]

    if theme:
        escaped_theme = theme.replace('"', '\\"')
        script_lines.append(
            f'    set current settings of selected tab of targetWindow '
            f'to settings set "{escaped_theme}"'
        )

    if color_hex:
        r, g, b = hex_to_terminal_rgb(color_hex)
        tr, tg, tb = text_color_for_bg(color_hex)
        script_lines.append(
            f'    set background color of selected tab of targetWindow '
            f'to {{{r}, {g}, {b}}}'
        )
        script_lines.append(
            f'    set normal text color of selected tab of targetWindow '
            f'to {{{tr}, {tg}, {tb}}}'
        )

    script_lines.append(
        f'    set bounds of targetWindow to {{{left}, {top}, {right}, {bottom}}}'
    )

    script_lines.append("end tell")
    script = "\n".join(script_lines)

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception as e:
        print(f"Warning: Failed to restyle window: {e}", file=sys.stderr)
        return False


def open_new_terminal_window(rect, command, color_hex=None, theme=None):
    """Open a new Terminal.app window with color or theme, position, and command."""
    left, top, right, bottom = rect

    script_lines = [
        'tell application "Terminal"',
        '    activate',
        '    do script ""',
        '    set targetWindow to window 1',
    ]

    if theme:
        escaped_theme = theme.replace('"', '\\"')
        script_lines.append(
            f'    set current settings of selected tab of targetWindow '
            f'to settings set "{escaped_theme}"'
        )

    if color_hex:
        r, g, b = hex_to_terminal_rgb(color_hex)
        tr, tg, tb = text_color_for_bg(color_hex)
        script_lines.append(
            f'    set background color of selected tab of targetWindow '
            f'to {{{r}, {g}, {b}}}'
        )
        script_lines.append(
            f'    set normal text color of selected tab of targetWindow '
            f'to {{{tr}, {tg}, {tb}}}'
        )

    script_lines.append(
        f'    set bounds of targetWindow to {{{left}, {top}, {right}, {bottom}}}'
    )

    if command:
        escaped_cmd = command.replace("\\", "\\\\").replace('"', '\\"')
        script_lines.append(f'    do script "{escaped_cmd}" in targetWindow')

    script_lines.append("end tell")
    script = "\n".join(script_lines)

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception as e:
        print(f"Warning: Failed to open window: {e}", file=sys.stderr)
        return False


def launch_watcher(colors, sound=False, highlight_color=None, sound_name="Submarine", sound_volume=0.2):
    """Launch the background watcher for idle highlighting on all terminal windows."""
    if not colors:
        return
    watcher_script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "watcher.py"
    )
    total_windows = get_terminal_window_count()
    if total_windows == 0:
        return
    color_str = ",".join(colors[:total_windows])
    watcher_cmd = [
        sys.executable, watcher_script,
        "--colors", color_str,
        "--window-count", str(total_windows)
    ]
    if sound:
        watcher_cmd.append("--sound")
        watcher_cmd += ["--sound-name", sound_name]
        watcher_cmd += ["--sound-volume", str(sound_volume)]
    if highlight_color:
        watcher_cmd += ["--highlight", highlight_color]
    try:
        subprocess.Popen(
            watcher_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
    except Exception:
        pass


def send_enter_to_window(window_index):
    """Send Enter keystroke to a specific Terminal window.

    Brings the window to front and sends Return via System Events.
    Used to auto-confirm Claude's 'trust this folder' prompt.
    """
    script = f"""
tell application "Terminal"
    activate
    set frontmost of window {window_index} to true
end tell
delay 0.3
tell application "System Events"
    tell process "Terminal"
        keystroke return
    end tell
end tell"""
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5
        )
    except Exception:
        pass


def calculate_layout(count, layout, bounds, row_gap=0):
    """Calculate window rects for the given layout.

    row_gap: vertical pixels reserved between rows to prevent title bar overlap.
    Applied to grid and rows layouts only.
    """
    x0, y0, x1, y1 = bounds
    width = x1 - x0
    height = y1 - y0
    rects = []

    if layout == "side-by-side":
        col_width = width // count
        for i in range(count):
            l = x0 + i * col_width
            r = x0 + (i + 1) * col_width if i < count - 1 else x1
            rects.append((l, y0, r, y1))

    elif layout == "grid":
        cols = math.ceil(math.sqrt(count))
        rows = math.ceil(count / cols)
        total_gap = row_gap * (rows - 1)
        usable_height = height - total_gap
        col_width = width // cols
        row_height = usable_height // rows
        for i in range(count):
            row = i // cols
            col = i % cols
            l = x0 + col * col_width
            t = y0 + row * (row_height + row_gap)
            r = x0 + (col + 1) * col_width if col < cols - 1 else x1
            b = t + row_height if row < rows - 1 else y1
            rects.append((l, t, r, b))

    elif layout == "rows":
        total_gap = row_gap * (count - 1)
        usable_height = height - total_gap
        row_height = usable_height // count
        for i in range(count):
            t = y0 + i * (row_height + row_gap)
            b = t + row_height if i < count - 1 else y1
            rects.append((x0, t, x1, b))

    elif layout == "stacked":
        for _ in range(count):
            rects.append((x0, y0, x1, y1))

    return rects


def main():
    mode_names = ", ".join(COLOR_MODES.keys())
    theme_names = ", ".join(TERMINAL_THEMES)

    parser = argparse.ArgumentParser(
        description="Open multiple color-coded Terminal windows"
    )
    parser.add_argument("--count", type=int, default=3,
                        help="Number of terminal windows (default: 3)")
    parser.add_argument("--layout",
                        choices=["side-by-side", "grid", "rows", "stacked",
                                 "hub-sides", "hub-side-left", "hub-side-right",
                                 "hub-grid", "hub-top", "hub-stack", "hub-columns"],
                        default="side-by-side",
                        help="Window layout (default: side-by-side). "
                             "Hub layouts place a browser in the center.")
    parser.add_argument("--mode", type=str, default=None,
                        help=f"Color mode: {mode_names} (default: midnight)")
    parser.add_argument("--theme", type=str, default=None,
                        help=f"Terminal.app theme: {theme_names}")
    parser.add_argument("--colors", type=str, default=None,
                        help="Comma-separated hex colors (overrides --mode)")
    parser.add_argument("--commands", type=str, default=None,
                        help="Comma-separated commands per window")
    parser.add_argument("--no-claude", action="store_true",
                        help="Skip auto-running claude in each window")
    parser.add_argument("--all-new", action="store_true",
                        help="Open all new windows instead of reusing existing one")
    parser.add_argument("--restyle", action="store_true",
                        help="Restyle/rearrange existing Terminal windows without opening new ones")
    parser.add_argument("--notify", action="store_true",
                        help="Enable idle highlighting (background color change when waiting)")
    parser.add_argument("--sound", action="store_true",
                        help="Play a sound when claude finishes or needs input")
    parser.add_argument("--sound-name", type=str, default="Submarine",
                        help="System sound name (default: Submarine)")
    parser.add_argument("--sound-volume", type=float, default=0.2,
                        help="Sound volume 0.0-1.0 (default: 0.2)")
    parser.add_argument("--include-all", action="store_true",
                        help="Include all visible windows (browsers, editors, etc.) in the layout")
    parser.add_argument("--skip-perms", action="store_true",
                        help="Run claude with --dangerously-skip-permissions")
    parser.add_argument("--highlight-color", type=str, default=None,
                        help="Highlight color for idle terminals (hex, e.g. #1a4a5a)")
    parser.add_argument("--list-modes", action="store_true",
                        help="List available color modes and exit")
    parser.add_argument("--list-themes", action="store_true",
                        help="List available Terminal.app themes and exit")
    parser.add_argument("--use-config", action="store_true",
                        help="Load settings from saved config file (~/.config/lite-tools/multiple-terminals.json)")
    args = parser.parse_args()

    # Apply saved config as defaults when --use-config is set
    if args.use_config:
        try:
            with open(CONFIG_PATH, "r") as f:
                cfg = json.load(f)
            if args.count == 3 and cfg.get("count"):
                args.count = cfg["count"]
            if args.layout == "side-by-side" and cfg.get("layout"):
                args.layout = cfg["layout"]
            if args.mode is None and cfg.get("mode"):
                args.mode = cfg["mode"]
            if args.theme is None and cfg.get("theme"):
                args.theme = cfg["theme"]
            if not args.no_claude and cfg.get("noClaude"):
                args.no_claude = True
            if not args.all_new and cfg.get("allNew"):
                args.all_new = True
            if not args.notify and cfg.get("notify"):
                args.notify = True
            if not args.sound and cfg.get("sound"):
                args.sound = True
            if not args.include_all and cfg.get("include") == "all":
                args.include_all = True
            if not args.restyle and cfg.get("restyle"):
                args.restyle = True
            if not args.commands and cfg.get("commands"):
                args.commands = cfg["commands"]
            if not args.skip_perms and cfg.get("skipPerms"):
                args.skip_perms = True
            if not args.highlight_color and cfg.get("highlightColor"):
                args.highlight_color = cfg["highlightColor"]
            if cfg.get("soundName"):
                args.sound_name = cfg["soundName"]
            if cfg.get("soundVolume") is not None:
                args.sound_volume = float(cfg["soundVolume"])
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

    if args.list_modes:
        print("Available color modes:")
        for name in COLOR_MODES:
            swatches = "  ".join(COLOR_MODES[name])
            print(f"  {name:12s}  {swatches}")
        sys.exit(0)

    if args.list_themes:
        print("Available Terminal.app themes:")
        for t in TERMINAL_THEMES:
            print(f"  {t}")
        sys.exit(0)

    count = max(1, args.count)
    use_theme = None
    colors = []

    if args.theme:
        use_theme = args.theme
    elif args.colors:
        color_list = [c.strip().strip('"').strip("'") for c in args.colors.split(",")]
        colors = [color_list[i % len(color_list)] for i in range(count)]
    else:
        mode = args.mode or DEFAULT_MODE
        if mode not in COLOR_MODES:
            print(f"Unknown mode '{mode}'. Available: {mode_names}", file=sys.stderr)
            sys.exit(1)
        color_list = COLOR_MODES[mode]
        colors = [color_list[i % len(color_list)] for i in range(count)]

    # Resolve commands
    if args.commands:
        cmd_list = [c.strip() for c in args.commands.split(",")]
    else:
        cmd_list = []

    claude_cmd = "claude"
    if args.skip_perms:
        claude_cmd = "claude --dangerously-skip-permissions"

    commands = []
    for i in range(count):
        if i < len(cmd_list) and cmd_list[i]:
            cmd = cmd_list[i]
        elif not args.no_claude:
            cmd = claude_cmd
        else:
            cmd = None

        # Wrap command to play a sound when it exits (task done)
        if cmd and (args.notify or args.sound):
            sound = "/System/Library/Sounds/Glass.aiff"
            cmd = f'{cmd}; afplay {sound} &'
        commands.append(cmd)

    bounds = get_screen_bounds()

    # Restyle mode: apply layout/colors to existing windows
    if args.restyle:
        valid_indices = get_valid_window_indices()
        other_windows = []

        if args.include_all or args.layout in HUB_LAYOUTS:
            all_windows = get_all_visible_windows()
            other_windows = [w for w in all_windows if w["app"] != "Terminal"]

        term_count = len(valid_indices)
        other_count = len(other_windows)
        total_count = term_count + other_count
        if total_count == 0:
            print("No windows to restyle.", file=sys.stderr)
            sys.exit(1)

        # Hub layouts: browser in center, terminals around it
        if args.layout in HUB_LAYOUTS:
            browser_win = get_or_open_browser()
            if not browser_win:
                print("Could not find or open a browser window.", file=sys.stderr)
                sys.exit(1)

            # Remove browser from other_windows if present
            other_windows = [w for w in other_windows
                             if not (w["app"] == browser_win["app"]
                                     and w["index"] == browser_win["index"])]

            browser_rect, term_rects = calculate_hub_layout(
                term_count, args.layout, bounds, row_gap=TITLEBAR_GAP)

            # Resize browser
            resize_app_window(browser_win["app"], browser_win["index"], browser_rect)
            time.sleep(0.1)

            # Restyle terminals
            restyled_colors = colors if colors else [None] * term_count
            if colors:
                restyled_colors = [colors[i % len(colors)] for i in range(term_count)]

            restyled = 0
            for i, win_idx in enumerate(valid_indices):
                if i >= len(term_rects):
                    break
                success = restyle_existing_window(
                    win_idx, term_rects[i],
                    color_hex=restyled_colors[i] if i < len(restyled_colors) and restyled_colors[i] else None,
                    theme=use_theme
                )
                if success:
                    restyled += 1
                time.sleep(0.1)

            label = args.layout
            if use_theme:
                label += f", theme: {use_theme}"
            elif args.mode or not args.colors:
                label += f", mode: {args.mode or DEFAULT_MODE}"

            print(f"Restyled {restyled} terminal{'s' if restyled != 1 else ''} + browser ({label})")
            if args.notify and colors:
                launch_watcher(colors, sound=args.sound, highlight_color=args.highlight_color, sound_name=args.sound_name, sound_volume=args.sound_volume)
            sys.exit(0)

        # Calculate layout: terminals get their own layout, other windows
        # are placed in remaining space with their minimum widths respected.
        x0, y0, x1, y1 = bounds
        if other_count > 0 and args.layout in ("side-by-side", "rows"):
            # Detect minimum sizes only when needed (side-by-side/rows may
            # produce cells smaller than an app's minimum width)
            other_min_sizes = []
            for win_info in other_windows:
                min_w, min_h = get_window_min_size(win_info["app"], win_info["index"])
                other_min_sizes.append((min_w, min_h))
            screen_w = x1 - x0
            # Use detected minimum widths, but cap total at 50% of screen
            other_total_w = sum(mw for mw, _ in other_min_sizes)
            max_other = int(screen_w * 0.5)
            if other_total_w > max_other:
                other_total_w = max_other

            term_bounds = (x0, y0, x1 - other_total_w, y1)
            term_rects = calculate_layout(term_count, args.layout, term_bounds, row_gap=TITLEBAR_GAP)

            # Place other windows on the right side, respecting their min widths
            other_rects = []
            other_x = x1 - other_total_w
            if args.layout == "side-by-side":
                # Stack vertically on right
                other_h = (y1 - y0) // max(1, other_count)
                for j in range(other_count):
                    ot = y0 + j * other_h
                    ob = y0 + (j + 1) * other_h if j < other_count - 1 else y1
                    other_rects.append((other_x, ot, x1, ob))
            else:
                # Rows: other windows get columns on the right
                cur_x = other_x
                for j in range(other_count):
                    w = other_min_sizes[j][0] if j < other_count - 1 else (x1 - cur_x)
                    other_rects.append((cur_x, y0, cur_x + w, y1))
                    cur_x += w
        else:
            # Grid or stacked: all windows get equal cells with row gaps.
            all_rects = calculate_layout(total_count, args.layout, (x0, y0, x1, y1), row_gap=TITLEBAR_GAP)
            term_rects = all_rects[:term_count]
            other_rects = all_rects[term_count:]

        # Terminal windows get colors/themes
        restyled_colors = colors if colors else [None] * term_count
        if colors:
            restyled_colors = [colors[i % len(colors)] for i in range(term_count)]

        restyled = 0

        # Restyle Terminal windows first
        for i, win_idx in enumerate(valid_indices):
            success = restyle_existing_window(
                win_idx, term_rects[i],
                color_hex=restyled_colors[i] if i < len(restyled_colors) and restyled_colors[i] else None,
                theme=use_theme
            )
            if success:
                restyled += 1
            time.sleep(0.1)

        # Resize other app windows
        other_resized = 0
        for j, win_info in enumerate(other_windows):
            success = resize_app_window(win_info["app"], win_info["index"], other_rects[j])
            if success:
                other_resized += 1
            time.sleep(0.1)

        label = args.layout
        if use_theme:
            label += f", theme: {use_theme}"
        elif args.mode or not args.colors:
            label += f", mode: {args.mode or DEFAULT_MODE}"

        msg = f"Restyled {restyled} terminal window{'s' if restyled != 1 else ''}"
        if other_resized > 0:
            msg += f" + resized {other_resized} other window{'s' if other_resized != 1 else ''}"
        msg += f" ({label})"
        print(msg)
        if args.notify and colors:
            launch_watcher(colors, sound=args.sound, highlight_color=args.highlight_color, sound_name=args.sound_name, sound_volume=args.sound_volume)
        sys.exit(0)

    # Hub layouts: browser + terminals (restyle existing, open new for remaining)
    if args.layout in HUB_LAYOUTS:
        browser_win = get_or_open_browser()
        browser_rect, term_rects = calculate_hub_layout(
            count, args.layout, bounds, row_gap=TITLEBAR_GAP)

        if browser_win:
            resize_app_window(browser_win["app"], browser_win["index"], browser_rect)
            time.sleep(0.2)

        valid_indices = get_valid_window_indices()
        existing_count = len(valid_indices)
        reuse_count = 0 if args.all_new else min(existing_count, count)
        restyled = 0
        opened = 0

        for i in range(reuse_count):
            if i >= len(term_rects):
                break
            color = colors[i] if colors else None
            success = restyle_existing_window(
                valid_indices[i], term_rects[i],
                color_hex=color, theme=use_theme
            )
            if success:
                restyled += 1
            time.sleep(0.2)

        need_confirm = not args.no_claude

        for i in range(reuse_count, count):
            if i >= len(term_rects):
                break
            color = colors[i] if colors else None
            success = open_new_terminal_window(
                term_rects[i], commands[i] if i < len(commands) else None,
                color_hex=color, theme=use_theme
            )
            if success:
                opened += 1
                if need_confirm:
                    # Wait for trust prompt, then auto-confirm this window
                    time.sleep(2.5)
                    send_enter_to_window(1)  # newest window is always index 1
                    time.sleep(0.5)
                else:
                    time.sleep(0.3)
            else:
                time.sleep(0.3)

        label = args.layout
        if use_theme:
            label += f", theme: {use_theme}"
        elif args.mode or not args.colors:
            label += f", mode: {args.mode or DEFAULT_MODE}"

        parts = []
        if restyled > 0:
            parts.append(f"restyled {restyled}")
        if opened > 0:
            parts.append(f"opened {opened} new")
        msg = " + ".join(parts) if parts else "0 windows"
        print(f"{msg} + browser ({label})")

        if args.notify and colors:
            launch_watcher(colors, sound=args.sound, highlight_color=args.highlight_color, sound_name=args.sound_name, sound_volume=args.sound_volume)

        sys.exit(0)

    rects = calculate_layout(count, args.layout, bounds, row_gap=TITLEBAR_GAP)

    # Restyle existing terminal windows first, then open new ones for remaining slots
    valid_indices = get_valid_window_indices()
    existing_count = len(valid_indices)
    reuse_count = 0 if args.all_new else min(existing_count, count)

    restyled = 0
    opened = 0

    # Restyle existing terminals (no commands, preserves what's running)
    for i in range(reuse_count):
        color = colors[i] if colors else None
        success = restyle_existing_window(
            valid_indices[i], rects[i],
            color_hex=color,
            theme=use_theme
        )
        if success:
            restyled += 1
        time.sleep(0.2)

    # Open new terminals for remaining slots (commands run here only)
    need_confirm = not args.no_claude

    for i in range(reuse_count, count):
        color = colors[i] if colors else None
        success = open_new_terminal_window(
            rects[i], commands[i] if i < len(commands) else None,
            color_hex=color,
            theme=use_theme
        )
        if success:
            opened += 1
            if need_confirm:
                # Wait for trust prompt, then auto-confirm this window
                time.sleep(4)
                send_enter_to_window(1)  # newest window is always index 1
                time.sleep(1)
            else:
                if i < count - 1:
                    time.sleep(0.3)
        else:
            if i < count - 1:
                time.sleep(0.3)

    label = args.layout
    if use_theme:
        label += f", theme: {use_theme}"
    elif args.mode or not args.colors:
        label += f", mode: {args.mode or DEFAULT_MODE}"

    parts = []
    if restyled > 0:
        parts.append(f"restyled {restyled}")
    if opened > 0:
        parts.append(f"opened {opened} new")
    msg = " + ".join(parts) if parts else "0 windows"
    print(f"{msg} ({label})")
    if opened < count:
        print(f"Warning: {count - opened} window(s) failed to open", file=sys.stderr)

    # Launch background watcher for idle detection
    if args.notify and colors:
        launch_watcher(colors, sound=args.sound, highlight_color=args.highlight_color, sound_name=args.sound_name, sound_volume=args.sound_volume)


if __name__ == "__main__":
    main()
