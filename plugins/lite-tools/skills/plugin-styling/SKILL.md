---
name: plugin-styling
description: Unified design system for all lite-tools skills. Edit the theme in one place and sync it across every skill without breaking functionality.
user_invocable: true
---

# Plugin Styling

Manages the shared visual theme across all lite-tools skills. Edit `theme.py` to change fonts, colors, layout components, or footer content, then run `sync.py` to propagate changes to every skill that uses theme markers.

## How It Works

Each skill file contains marker comments that delimit theme-controlled sections:

- CSS markers: `/* ==THEME:NAME== */` ... `/* ==/THEME:NAME== */`
- HTML markers: `<!-- ==THEME:NAME== -->` ... `<!-- ==/THEME:NAME== -->`

The sync script finds these markers and replaces the content between them with the latest values from `theme.py`. Code outside markers is never touched.

## Available Theme Sections

| Marker | Controls |
|--------|----------|
| `FONTS` | Google Fonts link tags |
| `VARS` | CSS variables and base reset |
| `NOISE_CSS` | Noise overlay styles |
| `TOPBAR` | Top navigation bar, brand, pill, tabs |
| `FADEIN` | FadeUp animation keyframes |
| `PAGE_TITLE` | Playfair italic page title + subtitle |
| `SECTION_LABEL` | Mono uppercase section labels |
| `CARDS` | Card component styles |
| `BUTTONS` | Button component styles |
| `FOOTER_CSS` | Footer styles |
| `NOISE_HTML` | SVG noise overlay markup |
| `FOOTER_HTML` | Footer markup with links and social icons |
| `HEARTBEAT` | JS heartbeat auto-shutdown snippet |

## Step 1: Edit the Theme

Open and edit the theme definition:

```
${CLAUDE_PLUGIN_ROOT}/skills/plugin-styling/theme.py
```

Each variable is a plain string containing CSS, HTML, or JS. Edit whichever sections need updating.

## Step 2: Preview Changes (Dry Run)

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/plugin-styling/sync.py --dry-run
```

This shows which files would be updated without making changes.

## Step 3: Apply Changes

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/plugin-styling/sync.py
```

The script will:
1. Find all skill `.py` files containing theme markers
2. Replace marker content with the latest theme values
3. Verify each file still compiles after syncing
4. Report results per file

To sync a single skill:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/plugin-styling/sync.py --skill folder-colors
```

## Adding Markers to a New Skill

When building a new skill, wrap theme-controlled sections with the appropriate markers. Example for CSS inside a Python string:

```
/* ==THEME:VARS== */
:root { ... }
/* ==/THEME:VARS== */
```

And for HTML:

```
<!-- ==THEME:FOOTER_HTML== -->
<div class="footer">...</div>
<!-- ==/THEME:FOOTER_HTML== -->
```

Only wrap sections that should stay consistent across skills. Skill-specific styles should remain outside markers.
