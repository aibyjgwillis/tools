#!/usr/bin/env python3
"""Sync theme across all lite-tools skills.

Finds marker comments in skill Python files and replaces content between them
with the latest values from theme.py. Never touches code outside markers.

Markers in CSS:  /* ==THEME:NAME== */ ... /* ==/THEME:NAME== */
Markers in HTML: <!-- ==THEME:NAME== --> ... <!-- ==/THEME:NAME== -->

Usage: python3 sync.py [--dry-run] [--skill SKILL_NAME]
"""

import os
import re
import sys
import importlib.util

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.dirname(SCRIPT_DIR)

# Load theme.py
spec = importlib.util.spec_from_file_location("theme", os.path.join(SCRIPT_DIR, "theme.py"))
theme = importlib.util.module_from_spec(spec)
spec.loader.exec_module(theme)

# Map marker names to theme attributes
MARKER_MAP = {
    "FONTS":         "FONTS_LINK",
    "VARS":          "CSS_VARS",
    "NOISE_CSS":     "CSS_NOISE",
    "TOPBAR":        "CSS_TOPBAR",
    "FADEIN":        "CSS_FADEIN",
    "PAGE_TITLE":    "CSS_PAGE_TITLE",
    "SECTION_LABEL": "CSS_SECTION_LABEL",
    "CARDS":         "CSS_CARDS",
    "BUTTONS":       "CSS_BUTTONS",
    "FOOTER_CSS":    "CSS_FOOTER",
    "NOISE_HTML":    "HTML_NOISE",
    "FOOTER_HTML":   "HTML_FOOTER",
    "WAITLIST":      "JS_WAITLIST",
    "HEARTBEAT":     "JS_HEARTBEAT",
}

# Regex patterns for both CSS and HTML markers
CSS_PATTERN = re.compile(
    r'(/\* ==THEME:(\w+)== \*/\n)(.*?)(\n/\* ==/THEME:\2== \*/)',
    re.DOTALL
)
HTML_PATTERN = re.compile(
    r'(<!-- ==THEME:(\w+)== -->\n)(.*?)(\n<!-- ==/THEME:\2== -->)',
    re.DOTALL
)


def sync_file(filepath, dry_run=False):
    """Replace content between theme markers with latest theme values."""
    with open(filepath, "r") as f:
        original = f.read()

    content = original
    changes = []

    for pattern in [CSS_PATTERN, HTML_PATTERN]:
        def replacer(match):
            marker_name = match.group(2)
            attr_name = MARKER_MAP.get(marker_name)
            if not attr_name:
                return match.group(0)  # Unknown marker, skip
            new_value = getattr(theme, attr_name, None)
            if new_value is None:
                return match.group(0)  # No theme value, skip
            old_value = match.group(3)
            if old_value.strip() != new_value.strip():
                changes.append(marker_name)
            return match.group(1) + new_value + match.group(4)

        content = pattern.sub(replacer, content)

    if content != original:
        if not dry_run:
            with open(filepath, "w") as f:
                f.write(content)
        return changes
    return []


def find_skill_files(skill_name=None):
    """Find all Python files in skill directories that contain theme markers."""
    files = []
    for skill_dir in os.listdir(SKILLS_DIR):
        if skill_dir == "plugin-styling":
            continue
        if skill_name and skill_dir != skill_name:
            continue
        skill_path = os.path.join(SKILLS_DIR, skill_dir)
        if not os.path.isdir(skill_path):
            continue
        for fname in os.listdir(skill_path):
            if fname.endswith(".py"):
                fpath = os.path.join(skill_path, fname)
                with open(fpath, "r") as f:
                    if "==THEME:" in f.read():
                        files.append((skill_dir, fpath))
    return files


def verify_syntax(filepath):
    """Check that the file still compiles after sync."""
    import py_compile
    try:
        py_compile.compile(filepath, doraise=True)
        return True
    except py_compile.PyCompileError as e:
        return str(e)


def main():
    dry_run = "--dry-run" in sys.argv
    skill_name = None
    if "--skill" in sys.argv:
        idx = sys.argv.index("--skill")
        if idx + 1 < len(sys.argv):
            skill_name = sys.argv[idx + 1]

    files = find_skill_files(skill_name)

    if not files:
        print("No skill files with theme markers found.")
        if skill_name:
            print(f"Skill '{skill_name}' may not have markers yet.")
        return

    print(f"\nPlugin Styling Sync {'(DRY RUN)' if dry_run else ''}")
    print(f"Found {len(files)} file(s) with theme markers\n")

    all_ok = True
    for skill, filepath in files:
        changes = sync_file(filepath, dry_run)
        fname = os.path.basename(filepath)
        if changes:
            # Verify syntax after sync
            if not dry_run:
                result = verify_syntax(filepath)
                if result is True:
                    status = "synced"
                else:
                    status = "BROKEN"
                    all_ok = False
                    print(f"  ERROR: {result}")
            else:
                status = "would sync"
            print(f"  {skill}/{fname} ... {status} ({', '.join(changes)})")
        else:
            print(f"  {skill}/{fname} ... up to date")

    if not all_ok:
        print("\nSome files have syntax errors after sync. Review manually.")
    elif not dry_run:
        print("\nAll files synced and verified.")
    else:
        print("\nDry run complete. Run without --dry-run to apply.")


if __name__ == "__main__":
    main()
