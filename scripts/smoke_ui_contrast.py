#!/usr/bin/env python3
"""Smoke-test UI contrast contract in ui_theme.get_global_css().

Rules checked:
  - Dark surfaces pair with light text (#f4f4f5 / --hq-on-dark)
  - Light surfaces pair with dark text (#0f172a / --hq-on-light)
  - Key Streamlit widgets used in main.py are covered
  - Sidebar no longer blanket-forces white on every descendant

Also writes scripts/smoke_ui_contrast_preview.html for a visual pass
(open in a browser and toggle OS light/dark appearance).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ui_theme import get_global_css  # noqa: E402

ON_DARK = ("#f4f4f5", "--hq-on-dark", "#fafafa", "#fff", "#ffffff")
ON_LIGHT = ("#0f172a", "--hq-on-light", "#020617")
DARK_SURFACES = ("#16161f", "--hq-field-dark", "#12121a", "#1c1c28", "#0a0a10", "#050508")
LIGHT_SURFACES = ("#eef2f7", "--hq-field-light", "#f8fafc", "#ffffff", "#fff")

WIDGET_NEEDLES = (
    ".stTextInput",
    ".stTextArea",
    ".stSelectbox",
    ".stMultiSelect",
    ".stNumberInput",
    ".stSlider",
    ".stRadio",
    ".stCheckbox",
    ".stButton",
    "stExpander",
    "stAlert",
    "stCaption",
    "stBaseButton-secondary",
    "stBaseButton-primary",
    "data-baseweb=\"select\"",
    "data-baseweb=\"input\"",
    "data-baseweb=\"textarea\"",
    "data-baseweb=\"popover\"",
)


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _blocks(css: str) -> list[tuple[str, str]]:
    """Return (selector, body) for top-level rule blocks (best-effort)."""
    out: list[tuple[str, str]] = []
    for m in re.finditer(r"([^{}@][^{]*)\{([^{}]*)\}", css):
        sel = " ".join(m.group(1).split())
        body = m.group(2)
        if sel.strip():
            out.append((sel, body))
    return out


def _has_any(text: str, tokens: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(t.lower() in low for t in tokens)


def check_contract(css: str) -> list[str]:
    errors: list[str] = []
    raw = css
    plain = _strip_comments(css)

    if "--hq-on-dark" not in plain or "--hq-on-light" not in plain:
        errors.append("Missing --hq-on-dark / --hq-on-light contrast tokens")

    # Sidebar must NOT force color on every descendant (white-on-light inputs).
    if re.search(r'\[data-testid="stSidebar"\]\s+\*\s*\{[^}]*color:', plain):
        errors.append('Sidebar still has blanket `[data-testid="stSidebar"] * { color: ... }`')

    for needle in WIDGET_NEEDLES:
        if needle not in plain:
            errors.append(f"Missing widget coverage: {needle}")

    # In light media query, field surfaces should use on-light text.
    light_mq = re.search(
        r"@media\s*\(\s*prefers-color-scheme:\s*light\s*\)\s*\{(.*)\}",
        plain,
        flags=re.S,
    )
    if not light_mq:
        errors.append("Missing @media (prefers-color-scheme: light) block")
    else:
        # Only take until we can't reliably parse nested braces — check substring presence.
        # Find all light MQ chunks.
        light_chunks = re.findall(
            r"@media\s*\(\s*prefers-color-scheme:\s*light\s*\)\s*\{",
            plain,
        )
        if not light_chunks:
            errors.append("Light-mode media query not found")
        if "--hq-on-light" not in plain or "#0f172a" not in plain:
            errors.append("Light mode missing dark text token (#0f172a / --hq-on-light)")
        if "--hq-field-light" not in plain and "#eef2f7" not in plain:
            errors.append("Light mode missing light field surface")

    # Pairing: any rule that sets a light background should also set dark text
    # when the selector looks like a form control / button / expander.
    formish = re.compile(
        r"(TextInput|TextArea|Selectbox|MultiSelect|NumberInput|Expander|baseweb=\"input\"|"
        r"baseweb=\"textarea\"|baseweb=\"select\"|stButton|BaseButton)",
        re.I,
    )
    for sel, body in _blocks(plain):
        if not formish.search(sel):
            continue
        if "primary" in sel.lower():
            continue
        # Only treat background:/background-color: light fills as light surfaces.
        bg_light = bool(
            re.search(
                r"background(?:-color)?\s*:\s*[^;]*(#eef2f7|#f8fafc|--hq-field-light)",
                body,
                flags=re.I,
            )
        )
        if not bg_light:
            continue
        if not _has_any(body, ON_LIGHT):
            if "background" in body.lower() and "color" not in body.lower():
                continue
            errors.append(f"Light surface without dark text in rule: {sel[:80]}")

    for sel, body in _blocks(plain):
        if not formish.search(sel):
            continue
        if "primary" in sel.lower():
            continue
        bg_dark = bool(
            re.search(
                r"background(?:-color)?\s*:\s*[^;]*(#16161f|#12121a|#1c1c28|--hq-field-dark)",
                body,
                flags=re.I,
            )
        )
        if not bg_dark:
            continue
        if "color" in body.lower() and not _has_any(body, ON_DARK):
            if _has_any(body, ON_LIGHT):
                errors.append(f"Dark surface with light-mode text in default rule: {sel[:80]}")

    # Inline code chips must be light fill + dark text (readable on dark chrome).
    if "stCaption" in plain and "code" in plain:
        if not (_has_any(plain, LIGHT_SURFACES) and _has_any(plain, ON_LIGHT)):
            errors.append("Caption/inline code contrast tokens missing")

    if "CONTRAST CONTRACT" not in raw:
        errors.append("Contrast contract comment marker missing (theme may have regressed)")

    return errors


def write_preview(css: str, path: Path) -> None:
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>IntentEngine UI contrast smoke</title>
  {css}
  <style>
    body {{ margin: 0; font-family: Outfit, system-ui, sans-serif; }}
    .wrap {{ max-width: 880px; margin: 0 auto; padding: 1.5rem; }}
    .grid {{ display: grid; gap: 1rem; grid-template-columns: 1fr 1fr; }}
    @media (max-width: 700px) {{ .grid {{ grid-template-columns: 1fr; }} }}
    .card {{ border: 1px solid rgba(255,255,255,0.12); border-radius: 14px; padding: 1rem; background: rgba(255,255,255,0.03); }}
    .card h3 {{ margin: 0 0 0.75rem; font-size: 0.8rem; letter-spacing: 0.12em; text-transform: uppercase; color: #a78bfa; }}
    /* Fixture mimics of Streamlit widgets */
    .stButton > button {{ width: 100%; cursor: pointer; }}
    .fixture-field {{
      border-radius: 10px; padding: 0.65rem 0.75rem; border: 1px solid rgba(255,255,255,0.12);
      background: var(--hq-field-dark); color: var(--hq-on-dark);
    }}
    @media (prefers-color-scheme: light) {{
      .fixture-field {{
        background: var(--hq-field-light); color: var(--hq-on-light);
        border-color: rgba(15,23,42,0.18);
      }}
    }}
    .note {{ color: #a1a1aa; font-size: 0.85rem; margin-top: 1rem; }}
  </style>
</head>
<body>
  <div class="stApp">
    <div data-testid="stAppViewContainer">
      <div class="wrap">
        <h1 style="color:var(--hq-text)">Contrast smoke preview</h1>
        <p class="note">Toggle your OS appearance (light/dark). Fields and buttons should stay readable:
        light fill → dark text, dark fill → light text.</p>
        <div class="grid">
          <div class="card">
            <h3>Text input</h3>
            <div class="stTextInput"><div><div class="fixture-field">Session id sample text</div></div></div>
          </div>
          <div class="card">
            <h3>Text area</h3>
            <div class="stTextArea"><div><div class="fixture-field">Outreach body sample — should stay readable.</div></div></div>
          </div>
          <div class="card">
            <h3>Select / multiselect</h3>
            <div class="stSelectbox"><div><div class="fixture-field">High, Medium</div></div></div>
          </div>
          <div class="card">
            <h3>Secondary button</h3>
            <div class="stButton"><button kind="secondary">Save fetched data to NocoDB</button></div>
          </div>
          <div class="card">
            <h3>Primary button</h3>
            <div class="stButton"><button kind="primary">Continue to scoring →</button></div>
          </div>
          <div class="card">
            <h3>Alert + caption code</h3>
            <div data-testid="stAlert" class="stAlert"><p>Fetched data saved.</p></div>
            <p class="stCaption" data-testid="stCaption" style="margin-top:0.75rem">
              Requires <code>NOCODB_*</code> in secrets.
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def main() -> int:
    css = get_global_css()
    errors = check_contract(css)
    preview = ROOT / "scripts" / "smoke_ui_contrast_preview.html"
    write_preview(css, preview)

    if errors:
        print("UI contrast smoke FAILED:")
        for e in errors:
            print(f"  - {e}")
        print(f"Preview written: {preview}")
        return 1

    print("UI contrast smoke OK")
    print(f"  tokens: --hq-on-dark / --hq-on-light present")
    print(f"  widgets covered: {len(WIDGET_NEEDLES)}")
    print(f"  preview: {preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
