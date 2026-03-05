#!/usr/bin/env python3
"""Background watcher that highlights Terminal windows when Claude is waiting for input.

Polls terminal contents every 2 seconds. When a window shows Claude's idle prompt,
changes its background to a highlight color. Restores original color when active.

Usage: python3 watcher.py --colors "#0a0e1a,#111633,#1a1040" --highlight "#1a3a5a"
       (launched automatically by multiple-terminals.py --notify)

Pass original colors so they can be restored. Runs until all tracked windows close.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time

# PID file so we can stop previous watchers
PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".watcher.pid")

# Default highlight color (muted teal-blue glow)
DEFAULT_HIGHLIGHT = "#1a4a5a"
CONFIG_PATH = os.path.expanduser("~/.config/lite-tools/multiple-terminals.json")


def read_config():
    """Read saved config, returning a dict (empty on failure)."""
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_highlight_from_config(fallback):
    """Read highlight color from saved config, falling back to the given default."""
    cfg = read_config()
    color = cfg.get("highlightColor", "").strip()
    if color and color.startswith("#") and len(color) in (4, 7):
        return color
    return fallback


def get_sound_settings_from_config(default_name, default_volume):
    """Read sound name and volume from saved config."""
    cfg = read_config()
    name = cfg.get("soundName", default_name)
    volume = cfg.get("soundVolume", default_volume)
    try:
        volume = float(volume)
    except (TypeError, ValueError):
        volume = default_volume
    return name, max(0.0, min(1.0, volume))


def hex_to_terminal_rgb(hex_color):
    """Convert hex to Terminal.app 16-bit RGB."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (r * 257, g * 257, b * 257)


def get_window_count():
    """Get current number of Terminal.app windows."""
    try:
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "Terminal" to return count of windows'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except Exception:
        pass
    return 0


def get_window_title(window_index):
    """Get the title of a Terminal window."""
    try:
        result = subprocess.run(
            ["osascript", "-e",
             f'tell application "Terminal" to return name of window {window_index}'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def set_window_background(window_index, hex_color):
    """Set background color of a Terminal window."""
    r, g, b = hex_to_terminal_rgb(hex_color)
    try:
        subprocess.run(
            ["osascript", "-e",
             f'tell application "Terminal" to set background color of selected tab '
             f'of window {window_index} to {{{r}, {g}, {b}}}'],
            capture_output=True, text=True, timeout=5
        )
    except Exception:
        pass


def is_idle(title):
    """Check if a Terminal window title indicates Claude is waiting for input.

    Claude Code sets window title status indicators:
      ✳ (eight-spoked asterisk) = idle / waiting for input
      Braille spinner chars (⠂⠈⠐⠠ etc.) = actively working
    """
    if not title:
        return False
    # Idle when the title contains the idle marker
    if "\u2733" in title:  # ✳
        return True
    return False


def play_sound(sound_name="Submarine", volume=0.2):
    """Play a notification sound."""
    path = f"/System/Library/Sounds/{sound_name}.aiff"
    if not os.path.exists(path):
        path = "/System/Library/Sounds/Submarine.aiff"
    try:
        subprocess.Popen(
            ["afplay", "-v", str(volume), path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        pass


def kill_existing_watcher():
    """Kill any previously running watcher process."""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, signal.SIGTERM)
        except (ProcessLookupError, ValueError, OSError):
            pass
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


def write_pid():
    """Write current PID to file."""
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def cleanup(signum=None, frame=None):
    """Clean up PID file on exit."""
    try:
        os.remove(PID_FILE)
    except OSError:
        pass
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="Watch Terminal windows for Claude idle state")
    parser.add_argument("--colors", type=str, required=True,
                        help="Comma-separated original hex colors for each window")
    parser.add_argument("--highlight", type=str, default=DEFAULT_HIGHLIGHT,
                        help=f"Highlight color when idle (default: {DEFAULT_HIGHLIGHT})")
    parser.add_argument("--sound", action="store_true", default=False,
                        help="Play a sound when a window becomes idle")
    parser.add_argument("--sound-name", type=str, default="Submarine",
                        help="System sound name (default: Submarine)")
    parser.add_argument("--sound-volume", type=float, default=0.2,
                        help="Sound volume 0.0-1.0 (default: 0.2)")
    parser.add_argument("--window-count", type=int, default=0,
                        help="Number of windows to track (0 = auto-detect)")
    args = parser.parse_args()

    kill_existing_watcher()
    write_pid()
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    original_colors = [c.strip().strip('"').strip("'") for c in args.colors.split(",")]
    highlight = get_highlight_from_config(args.highlight)
    sound_name, sound_volume = get_sound_settings_from_config(args.sound_name, args.sound_volume)
    tracked_count = args.window_count if args.window_count > 0 else len(original_colors)

    # Track which windows are currently highlighted
    highlighted = set()
    # Track which windows have already played their sound (reset only on genuine activity)
    sound_played = set()
    # Debounce: count consecutive polls in the same state before acting
    idle_streak = {}    # window_idx -> consecutive idle polls
    active_streak = {}  # window_idx -> consecutive active polls
    IDLE_THRESHOLD = 1    # highlight immediately on first idle detection
    ACTIVE_THRESHOLD = 2  # require 2 consecutive active polls before restoring (prevents flicker)
    poll_interval = 2.0
    empty_polls = 0
    config_check_counter = 0

    while True:
        try:
            # Re-read highlight color from config every 5 polls (~10s)
            config_check_counter += 1
            if config_check_counter >= 5:
                config_check_counter = 0
                new_highlight = get_highlight_from_config(args.highlight)
                if new_highlight != highlight:
                    highlight = new_highlight
                    for w in list(highlighted):
                        set_window_background(w, highlight)
                sound_name, sound_volume = get_sound_settings_from_config(args.sound_name, args.sound_volume)

            current_count = get_window_count()
            if current_count == 0:
                empty_polls += 1
                if empty_polls > 3:
                    break
                time.sleep(poll_interval)
                continue
            empty_polls = 0

            check_count = min(tracked_count, current_count)

            for i in range(check_count):
                window_idx = i + 1
                title = get_window_title(window_idx)
                idle = is_idle(title)

                if idle:
                    idle_streak[window_idx] = idle_streak.get(window_idx, 0) + 1
                    active_streak[window_idx] = 0
                else:
                    active_streak[window_idx] = active_streak.get(window_idx, 0) + 1
                    idle_streak[window_idx] = 0

                if idle and window_idx not in highlighted:
                    if idle_streak.get(window_idx, 0) >= IDLE_THRESHOLD:
                        set_window_background(window_idx, highlight)
                        highlighted.add(window_idx)
                        if args.sound and window_idx not in sound_played:
                            play_sound(sound_name, sound_volume)
                            sound_played.add(window_idx)
                elif not idle and window_idx in highlighted:
                    if active_streak.get(window_idx, 0) >= ACTIVE_THRESHOLD:
                        color_idx = i % len(original_colors)
                        set_window_background(window_idx, original_colors[color_idx])
                        highlighted.discard(window_idx)
                        sound_played.discard(window_idx)

            time.sleep(poll_interval)

        except Exception:
            time.sleep(poll_interval)

    cleanup()


if __name__ == "__main__":
    main()
