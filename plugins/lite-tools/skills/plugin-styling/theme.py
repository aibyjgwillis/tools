"""Unified theme definition for all lite-tools skills.

Edit these snippets to change the design across all skills.
Run sync.py to propagate changes.
"""

# Google Fonts link tag
FONTS_LINK = '<link rel="preconnect" href="https://fonts.googleapis.com">\n<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Playfair+Display:ital,wght@0,400;0,700;1,400&family=JetBrains+Mono:wght@300;400;500&display=swap" rel="stylesheet">'

# CSS variables and base reset
CSS_VARS = """:root {
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
}"""

# Noise overlay CSS
CSS_NOISE = ".noise-overlay { position: fixed; inset: 0; z-index: 9999; pointer-events: none; opacity: 0.04; }"

# Topbar CSS
CSS_TOPBAR = """.topbar {
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
.topbar-tab.active { background: var(--slate); color: var(--ivory); }"""

# FadeUp animation CSS
CSS_FADEIN = "@keyframes fadeUp { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }"

# Page title CSS (Playfair italic)
CSS_PAGE_TITLE = """.page-title {
  font-family: var(--font-drama); font-size: 32px; font-weight: 400;
  font-style: italic; text-align: center; margin-bottom: 8px;
}
.page-subtitle {
  font-family: var(--font-mono); font-size: 12px; color: var(--champagne);
  text-align: center; margin-bottom: 40px;
}"""

# Section label CSS
CSS_SECTION_LABEL = """.section-label {
  font-family: var(--font-mono); font-size: 10px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.14em; color: var(--champagne);
  margin-bottom: 12px;
}"""

# Card CSS
CSS_CARDS = """.card {
  background: white; border: 1px solid rgba(28,28,30,0.08);
  border-radius: 12px; padding: 20px 24px; margin-bottom: 20px;
}
.card-champagne { background: rgba(90,125,150,0.04); border-color: rgba(90,125,150,0.12); }
.card-amber { background: var(--amber-bg); border-color: rgba(184,134,11,0.15); }"""

# Button CSS
CSS_BUTTONS = """.btn {
  font-family: var(--font-heading); font-size: 13px; font-weight: 500;
  padding: 10px 20px; border-radius: 8px; border: 1px solid transparent;
  cursor: pointer; transition: all 0.2s;
}
.btn-primary { background: var(--slate); color: var(--ivory); }
.btn-primary:hover { background: var(--obsidian); }
.btn-secondary { background: white; border-color: rgba(28,28,30,0.15); color: var(--champagne); }
.btn-secondary:hover { border-color: rgba(28,28,30,0.45); color: var(--slate); }"""

# Footer CSS
CSS_FOOTER = """.footer {
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
.footer-socials a:hover svg { opacity: 1; }"""

# Noise overlay HTML
HTML_NOISE = """<svg class="noise-overlay" width="100%" height="100%">
  <filter id="noise"><feTurbulence type="fractalNoise" baseFrequency="0.65" numOctaves="3" stitchTiles="stitch"/></filter>
  <rect width="100%" height="100%" filter="url(#noise)"/>
</svg>"""

# Footer HTML
HTML_FOOTER = """<div class="footer">
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
</div>"""

# Heartbeat JS (shared auto-shutdown pattern)
JS_HEARTBEAT = "setInterval(() => { fetch('/api/heartbeat').catch(() => {}); }, 4000);"
