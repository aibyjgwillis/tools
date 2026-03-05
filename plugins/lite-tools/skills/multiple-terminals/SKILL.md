---
name: multiple-terminals
description: Open multiple color-coded Terminal.app windows tiled across your screen, each running claude by default. Use when the user wants a multi-terminal workspace, multiple claude sessions, side-by-side terminals, or to rearrange existing terminal windows.
user_invocable: true
---

# Multiple Terminals

When this skill is invoked, determine the user's intent:

## 1. Quick Launch (default, most common)

If the user just wants terminals opened with their preferences, run the script directly. Do NOT open the configurator UI.

**IMPORTANT**: If the user says something generic like "setup my terminals" or "launch terminals" without specifying parameters, use `--use-config` to load their saved preferences:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/multiple-terminals/multiple-terminals.py --use-config
```

If the user asks to load a named preset (e.g. "use my work setup", "load coding preset"), use `--preset`:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/multiple-terminals/multiple-terminals.py --preset "preset name"
```

To list available presets:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/multiple-terminals/multiple-terminals.py --list-presets
```

If the user specifies parameters, parse them and run:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/multiple-terminals/multiple-terminals.py --count N --layout LAYOUT
```

Optional flags:
- `--use-config` to load saved settings from `~/.config/lite-tools/multiple-terminals.json`
- `--preset "NAME"` to load a named preset from the config file
- `--list-presets` to list available named presets
- `--mode NAME` for a color palette (ocean, forest, sunset, berry, earth, mono, warm, cool, classic, stealth, tactical, carbon, midnight, mermaid, pastel, neutrals, mint, moody, leather, claude)
- `--theme "NAME"` for a Terminal.app theme (Pro, Homebrew, Ocean, Red Sands, Grass, Man Page, Novel, Basic, Silver Aerogel)
- `--colors "#hex1,#hex2,#hex3"` for custom colors
- `--commands "cmd1,cmd2,cmd3"` for custom commands per window
- `--no-claude` to skip auto-launching claude
- `--notify` to enable idle highlighting (background color change when claude is waiting)
- `--sound` to play a sound when claude finishes or needs input
- `--sound-name NAME` system sound name (Submarine, Pop, Purr, Glass, Bottle, Blow, Tink, Ping, Morse, Hero, Funk)
- `--sound-volume 0.0-1.0` notification volume (default 0.2)
- `--highlight-color "#hex"` idle highlight background color
- `--skip-perms` to run claude with --dangerously-skip-permissions
- `--all-new` to open all new windows (default reuses current terminal)
- `--include-all` to resize all visible windows (browsers, editors, etc.) alongside terminals
- `--layout hub-sides|hub-columns|hub-grid|hub-top|hub-bottom` for browser-centered layouts

Defaults: 3 windows, side-by-side, ocean mode, claude running in each, reuses current terminal. When `--use-config` is used, all defaults come from the saved config instead.

**Limitation:** Only detects and organizes Terminal windows on the active desktop. Windows on other macOS Spaces are ignored.

## 2. Configure (when the user wants to change their setup)

If the user says they want to "configure", "customize", "pick colors", "set up", "choose a layout", "change my setup", "edit my terminal settings", "tweak my terminals", or anything suggesting they want to visually adjust their terminal configuration, launch the web configurator:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/multiple-terminals/server.py
```

Then tell the user the configurator is running at http://localhost:9848. It auto-closes when the browser tab closes.

If port 9848 is already in use, kill the existing process first:

```bash
lsof -ti:9848 | xargs kill 2>/dev/null; sleep 0.5; python3 ${CLAUDE_PLUGIN_ROOT}/skills/multiple-terminals/server.py
```

## 3. Restyle/Rearrange existing terminals

If the user wants to rearrange or restyle terminals that are already open, use the `--restyle` flag. This applies a new layout, color mode, or theme to all existing Terminal.app windows without opening new ones:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/multiple-terminals/multiple-terminals.py --restyle --layout LAYOUT --mode MODE
```

The `--restyle` flag skips opening new windows and instead applies the layout and appearance to existing windows.

## Examples

- `/multiple-terminals` - launch with last saved config
- `/multiple-terminals 4 grid ocean` - 4 ocean-themed grid terminals
- `/multiple-terminals configure` or `/multiple-terminals change my setup` - open the web configurator
- `/multiple-terminals use my work preset` - load the "work" named preset
- `/multiple-terminals rearrange to grid` - rearrange existing windows to grid
- `/multiple-terminals restyle to ember` - change existing windows to ember colors
- `/multiple-terminals 2 with Pro theme` - 2 terminals using Terminal.app Pro theme
- `/multiple-terminals 3 with notifications` - 3 terminals with sound alerts
- `/multiple-terminals 3 skip permissions` - 3 terminals with dangerously-skip-permissions

Do NOT ask questions. Run immediately based on the user's request.
