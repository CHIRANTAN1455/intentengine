"""Premium visual system for HireQuity (Streamlit-injected CSS)."""
from __future__ import annotations

BRAND = "HireQuity"


def get_global_css() -> str:
    return """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');

  :root {
    --hq-bg0: #07070a;
    --hq-bg1: #0d0d14;
    --hq-surface: rgba(255, 255, 255, 0.03);
    --hq-surface2: rgba(255, 255, 255, 0.06);
    --hq-border: rgba(255, 255, 255, 0.09);
    --hq-border-strong: rgba(168, 85, 247, 0.35);
    --hq-text: #f4f4f5;
    --hq-muted: #a1a1aa;
    --hq-dim: #71717a;
    --hq-accent: #a855f7;
    --hq-accent2: #22d3ee;
    --hq-success: #34d399;
    --hq-warn: #fbbf24;
    --hq-danger: #fb7185;
    --hq-radius: 16px;
    --hq-radius-sm: 10px;
  }

  .stApp {
    background: var(--hq-bg0) !important;
    color: var(--hq-text) !important;
  }
  [data-testid="stAppViewContainer"] {
    background: linear-gradient(165deg, var(--hq-bg0) 0%, #0f0a1a 45%, var(--hq-bg1) 100%) !important;
  }
  [data-testid="stAppViewContainer"]::before {
    content: "";
    position: fixed;
    inset: 0;
    background-image: radial-gradient(ellipse 80% 50% at 20% 0%, rgba(168, 85, 247, 0.12), transparent 50%),
      radial-gradient(ellipse 60% 40% at 90% 10%, rgba(34, 211, 238, 0.08), transparent 45%),
      linear-gradient(180deg, rgba(0,0,0,0.2) 0%, transparent 30%);
    pointer-events: none;
    z-index: 0;
  }
  [data-testid="stAppViewContainer"] > .main { position: relative; z-index: 1; }
  [data-testid="stAppViewContainer"] [data-testid="stHeader"] { background: transparent !important; }
  [data-testid="stToolbar"] { display: none !important; }
  [data-testid="stDecoration"] { display: none !important; }

  html, body, p, li, label, span, h1, h2, h3, h4, h5, h6, [class*="stMarkdown"] p {
    font-family: 'Outfit', system-ui, sans-serif !important;
    color: var(--hq-text) !important;
  }
  .stCaption, [data-testid="stCaption"] { color: var(--hq-dim) !important; }

  /* Main block spacing */
  .block-container { padding-top: 1.2rem !important; max-width: 1200px !important; }

  /* Default Streamlit vertical blocks: flatten */
  [data-testid="stVerticalBlock"] > [style*="flex"] > [data-testid="stVerticalBlock"] {
    gap: 0.25rem;
  }

  /* Sidebar */
  [data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0a0a10 0%, #12121c 100%) !important;
    border-right: 1px solid var(--hq-border) !important;
  }
  [data-testid="stSidebar"] * {
    color: var(--hq-text) !important;
  }
  [data-testid="stSidebar"] p, [data-testid="stSidebar"] li, [data-testid="stSidebar"] small {
    color: var(--hq-muted) !important;
  }
  [data-testid="stSidebar"] .stSelectbox label, [data-testid="stSidebar"] [data-baseweb="input"] { color: var(--hq-text) !important; }

  /* Widgets */
  [data-baseweb="select"] > div, [data-baseweb="input"] > div {
    background: var(--hq-surface) !important;
    border-color: var(--hq-border) !important;
    border-radius: var(--hq-radius-sm) !important;
  }
  [data-baseweb="input"] input, div[data-baseweb="input"] {
    color: var(--hq-text) !important;
  }

  .stTextInput > div > div, .stTextInput input {
    background: var(--hq-surface) !important;
    color: var(--hq-text) !important;
  }

  /* Buttons */
  .stButton > button {
    font-family: 'Outfit', sans-serif !important;
    font-weight: 600 !important;
    border-radius: 12px !important;
    border: 1px solid var(--hq-border) !important;
    background: var(--hq-surface) !important;
    color: var(--hq-text) !important;
    padding: 0.5rem 1rem !important;
    transition: transform 0.12s ease, box-shadow 0.12s ease, border-color 0.12s;
  }
  .stButton > button:hover { border-color: var(--hq-border-strong) !important; box-shadow: 0 0 24px rgba(168, 85, 247, 0.12); }
  .stButton > button:disabled { opacity: 0.35 !important; }
  .stButton > button[kind="primary"] {
    background: linear-gradient(125deg, #7c3aed 0%, #a855f7 45%, #22d3ee 160%) !important;
    color: #fff !important;
    border: none !important;
    box-shadow: 0 4px 24px rgba(124, 58, 237, 0.35) !important;
  }
  .stButton > button[kind="primary"]:hover { box-shadow: 0 6px 32px rgba(124, 58, 237, 0.45) !important; }

  /* Alerts */
  [data-baseweb="notification"] { border-radius: var(--hq-radius-sm) !important; }
  div.stAlert, [data-testid="stAlert"] {
    background: var(--hq-surface) !important;
    border: 1px solid var(--hq-border) !important;
    border-radius: var(--hq-radius) !important;
  }

  /* Metrics */
  [data-testid="stMetricValue"] { color: var(--hq-text) !important; }
  [data-testid="stMetricLabel"] { color: var(--hq-muted) !important; }
  [data-testid="metric-container"] { background: var(--hq-surface) !important; border: 1px solid var(--hq-border) !important; border-radius: var(--hq-radius) !important; padding: 1rem 1.1rem !important; }

  /* Dataframes in glass panel */
  [data-testid="stDataFrame"] { background: #0a0a10 !important; border-radius: 12px; border: 1px solid var(--hq-border) !important; }
  [data-testid="stDataFrame"] * { font-size: 0.85rem; }

  /* Code */
  [data-testid="stCode"] { border-radius: 12px !important; }
  [data-testid="stCode"] pre { background: #050508 !important; border: 1px solid var(--hq-border) !important; }
  [data-testid="stCode"] code, pre code { font-family: 'DM Mono', ui-monospace, monospace !important; color: #e4d4f7 !important; }

  .hq-hero { margin-bottom: 0.4rem; }
  .hq-eyebrow {
    display: inline-block; font-size: 0.68rem; font-weight: 700; letter-spacing: 0.22em; text-transform: uppercase;
    color: #c4b5fd !important; margin-bottom: 0.4rem; padding: 0.35rem 0.6rem; border-radius: 999px;
    background: rgba(168, 85, 247, 0.12);
    border: 1px solid rgba(168, 85, 247, 0.25);
  }
  .hq-title {
    font-size: clamp(1.6rem, 3.2vw, 2.1rem) !important; font-weight: 700; letter-spacing: -0.03em; margin: 0 0 0.2rem 0; line-height: 1.12;
    background: linear-gradient(100deg, #fff 0%, #c4b5fd 50%, #67e8f9 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
  }
  .hq-sub { font-size: 0.95rem; color: var(--hq-muted) !important; margin: 0 0 0.2rem 0; max-width: 46rem; line-height: 1.5; }
  .hq-pipeline-bar {
    display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 0.35rem;
    margin: 1rem 0 1.25rem 0; padding: 0.6rem; border-radius: 999px;
    background: rgba(255,255,255,0.03);
    border: 1px solid var(--hq-border);
  }
  .hq-step {
    display: flex; flex-direction: column; align-items: center; min-width: 0; flex: 1; padding: 0.2rem; cursor: default;
  }
  .hq-step-n {
    width: 26px; height: 26px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center; font-size: 0.68rem; font-weight: 700; margin-bottom: 4px;
    background: rgba(255,255,255,0.06);
    color: #a1a1aa !important; border: 1px solid var(--hq-border);
  }
  .hq-step.lite .hq-step-n { color: #71717a !important; }
  .hq-step.on .hq-step-n {
    background: linear-gradient(140deg, #6d28d9, #a855f7 55%, #22d3ee);
    color: #fff !important; border: none; box-shadow: 0 0 20px rgba(168, 85, 247, 0.45);
  }
  .hq-step.on .hq-step-l { color: #f4f4f5 !important; font-weight: 600; }
  .hq-step-l { font-size: 0.58rem; letter-spacing: 0.08em; text-transform: uppercase; color: #52525b !important; text-align: center; line-height: 1.1; }
  .hq-step-line { flex: 0.15; min-width: 4px; height: 1px; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.12), transparent); }
  @media (max-width: 900px) { .hq-pipeline-bar { border-radius: 16px; } .hq-step-l { display: none; } }

  .hq-glass { background: var(--hq-surface) !important; border: 1px solid var(--hq-border) !important; border-radius: var(--hq-radius) !important; padding: 1.1rem 1.25rem !important; }
  .hq-glass h3 { font-size: 0.8rem; letter-spacing: 0.12em; text-transform: uppercase; color: #a78bfa !important; margin: 0 0 0.5rem 0; font-weight: 600; }
  .hq-glass p { color: var(--hq-muted) !important; font-size: 0.9rem; margin: 0 0 0.5rem; }

  .hq-section { margin: 0.6rem 0 0.2rem; }
  .hq-section h2 { font-size: 1.05rem !important; font-weight: 600; color: #fafafa !important; margin: 0 0 0.2rem; letter-spacing: -0.02em; }
  .hq-section p { color: var(--hq-muted) !important; font-size: 0.9rem; margin: 0 0 0.5rem; }

  .hq-grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0.9rem; }
  @media (max-width: 800px) { .hq-grid2 { grid-template-columns: 1fr; } }

  .hq-pill { display: inline-block; font-size: 0.7rem; font-weight: 600; padding: 0.2rem 0.5rem; border-radius: 6px; margin-right: 0.3rem; }
  .hq-pill.ok { background: rgba(52, 211, 153, 0.15); color: #6ee7b7 !important; border: 1px solid rgba(52, 211, 153, 0.25); }
  .hq-pill.me { background: rgba(250, 204, 21, 0.12); color: #fde047 !important; border: 1px solid rgba(250, 204, 21, 0.25); }
  .hq-pill.lo { background: rgba(244, 63, 94, 0.12); color: #fda4af !important; border: 1px solid rgba(244, 63, 94, 0.2); }
  .hq-pill.un { background: rgba(161, 161, 170, 0.15); color: #a1a1aa !important; }

  .hq-lead { border: 1px solid var(--hq-border); border-radius: 14px; padding: 1rem; margin: 0.5rem 0; background: rgba(0,0,0,0.15); }
  .hq-lead h4 { margin: 0 0 0.5rem; font-size: 0.95rem; color: #fafafa !important; }
  .hq-lead .meta { color: #71717a !important; font-size: 0.78rem; margin-bottom: 0.4rem; }

  .email-draft-box, .hq-mail {
    background: linear-gradient(180deg, rgba(124, 58, 237, 0.08) 0%, rgba(0,0,0,0.2) 100%) !important;
    border: 1px solid rgba(124, 58, 237, 0.25) !important;
    border-radius: 12px !important;
    padding: 0.85rem 1rem !important;
    font-size: 0.88rem !important;
    line-height: 1.5;
    color: #e4e4e7 !important;
  }

  .hq-stat-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 0.65rem; }
  .hq-stat {
    background: linear-gradient(180deg, rgba(255,255,255,0.05) 0%, rgba(0,0,0,0.2) 100%);
    border: 1px solid var(--hq-border);
    border-radius: 14px; padding: 0.9rem 1rem; text-align: left;
  }
  .hq-stat .v { font-size: 1.5rem; font-weight: 700; background: linear-gradient(90deg, #fff, #c4b5fd); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  .hq-stat .k { font-size: 0.65rem; letter-spacing: 0.1em; text-transform: uppercase; color: #71717a !important; margin-top: 0.25rem; }
  .hq-dash-section { font-size: 0.7rem; letter-spacing: 0.18em; text-transform: uppercase; color: #7c3aed !important; margin: 1.2rem 0 0.5rem; font-weight: 700; }
  .hq-fade { color: #71717a !important; font-size: 0.82rem; }

  [data-testid="stProgress"] > div { background: rgba(255,255,255,0.08) !important; border-radius: 999px; }
  [data-testid="stProgress"] [role="progressbar"] { background: linear-gradient(90deg, #6d28d9, #a855f7, #22d3ee) !important; border-radius: 999px; }
</style>
"""


def render_hero(brand: str) -> str:
    return f"""
    <div class="hq-hero">
      <span class="hq-eyebrow">Client command center</span>
      <h1 class="hq-title">{brand}</h1>
      <p class="hq-sub">Single pipeline: hiring intent, waterfall enrichment, email + Walego, reply intelligence, and CRM with live performance you can present in the room.</p>
    </div>
    """


def render_stepper(current_idx: int) -> str:
    steps = [
        ("1", "Intent"),
        ("2", "Scoring"),
        ("3", "Enrich"),
        ("4", "Outreach"),
        ("5", "Replies"),
        ("6", "CRM"),
        ("7", "Data"),
    ]
    out = ['<div class="hq-pipeline-bar">']
    for i, (num, name) in enumerate(steps):
        on = " on" if i == int(current_idx) else ""
        out.append(
            f'<div class="hq-step{on}"><div class="hq-step-n">{num}</div><div class="hq-step-l">{name}</div></div>'
        )
    out.append("</div>")
    return "".join(out)


def section_header(title: str, subtitle: str) -> str:
    return f"""
    <div class="hq-section">
      <h2>{title}</h2>
      <p>{subtitle}</p>
    </div>
    """


def glass_card_start(title: str) -> str:
    return f'<div class="hq-glass"><h3>{title}</h3>'


def glass_card_end() -> str:
    return "</div>"


def pill_for_reply(label: str) -> str:
    t = (label or "").lower()
    if "interested" in t and "not" not in t:
        cls = "ok"
    elif "unsub" in t:
        cls = "un"
    elif "not" in t:
        cls = "lo"
    else:
        cls = "me"
    return f'<span class="hq-pill {cls}">{label}</span>'


def render_stat_grid(sections: list[tuple[str, list[tuple[str, str]]]]) -> str:
    """
    sections: [ ("TOP OF FUNNEL", [("42", "Leads generated"), ...]), ... ]
    value is HTML-escaped if needed by caller
    """
    parts = []
    for sec_title, stats in sections:
        parts.append(f'<div class="hq-dash-section">{sec_title}</div><div class="hq-stat-grid">')
        for val, key in stats:
            parts.append(f'<div class="hq-stat"><div class="v">{val}</div><div class="k">{key}</div></div>')
        parts.append("</div>")
    return "".join(parts)
