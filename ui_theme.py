"""Premium visual system for hirequity (Streamlit-injected CSS)."""
from __future__ import annotations

import math
from html import escape

BRAND = "hirequity"

# Tiny scene: night skyline + rising “intent” bars (72×32, crisp-edge rects).
_WELCOME_PIXEL_SVG = """
<svg viewBox="0 0 72 32" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges" aria-hidden="true">
  <rect width="72" height="32" fill="#0c0618"/>
  <rect x="0" y="0" width="72" height="14" fill="#140a28"/>
  <rect x="5" y="4" width="1" height="1" fill="#fde68a"/>
  <rect x="22" y="2" width="1" height="1" fill="#e9d5ff"/>
  <rect x="58" y="5" width="1" height="1" fill="#a5f3fc"/>
  <rect x="44" y="8" width="1" height="1" fill="#fde68a"/>
  <rect x="6" y="14" width="14" height="14" fill="#31285a"/>
  <rect x="9" y="17" width="2" height="2" fill="#fbbf24"/>
  <rect x="13" y="20" width="2" height="2" fill="#fbbf24"/>
  <rect x="9" y="23" width="2" height="2" fill="#fbbf24"/>
  <rect x="52" y="10" width="14" height="18" fill="#2a1f4a"/>
  <rect x="55" y="13" width="2" height="2" fill="#67e8f9"/>
  <rect x="59" y="16" width="2" height="2" fill="#67e8f9"/>
  <rect x="63" y="19" width="2" height="2" fill="#67e8f9"/>
  <rect x="26" y="27" width="20" height="1" fill="#3f3b55"/>
  <rect x="28" y="19" width="4" height="8" fill="#6d28d9"/>
  <rect x="34" y="16" width="4" height="11" fill="#7c3aed"/>
  <rect x="40" y="21" width="4" height="6" fill="#5b21b6"/>
  <rect x="46" y="13" width="4" height="14" fill="#a855f7"/>
  <rect x="30" y="27" width="4" height="1" fill="#22d3ee"/>
  <rect x="36" y="27" width="4" height="1" fill="#22d3ee"/>
  <rect x="42" y="27" width="4" height="1" fill="#22d3ee"/>
  <rect x="48" y="27" width="4" height="1" fill="#22d3ee"/>
  <rect x="47" y="22" width="3" height="4" fill="#4338ca"/>
  <rect x="48" y="20" width="1" height="2" fill="#fcd34d"/>
  <rect x="0" y="31" width="72" height="1" fill="#1a1530"/>
</svg>
""".strip()


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

  .hq-loader {
    position: relative;
    border: 1px solid var(--hq-border);
    border-radius: 20px;
    padding: 1.2rem 1.2rem;
    background: linear-gradient(165deg, rgba(124,58,237,0.14) 0%, rgba(34,211,238,0.06) 100%);
    overflow: hidden;
    margin: 0.4rem 0 0.8rem;
  }
  .hq-loader:before {
    content: "";
    position: absolute;
    inset: -30% auto auto -35%;
    width: 70%;
    height: 190%;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.11), transparent);
    transform: rotate(12deg);
    animation: hq-sweep 2.2s linear infinite;
    pointer-events: none;
  }
  .hq-loader h3 {
    margin: 0 0 0.5rem;
    font-size: 0.92rem;
    letter-spacing: 0.11em;
    text-transform: uppercase;
    color: #ddd6fe !important;
  }
  .hq-loader p {
    margin: 0 0 0.75rem;
    color: #d4d4d8 !important;
    font-size: 0.93rem;
  }
  .hq-loader-rail {
    height: 8px;
    border-radius: 999px;
    background: rgba(255,255,255,0.11);
    overflow: hidden;
  }
  .hq-loader-bar {
    width: 45%;
    height: 100%;
    border-radius: 999px;
    background: linear-gradient(90deg, #6d28d9, #a855f7, #22d3ee);
    animation: hq-pulse 1.3s ease-in-out infinite;
    box-shadow: 0 0 18px rgba(168,85,247,0.45);
  }
  @keyframes hq-sweep {
    0% { left: -40%; }
    100% { left: 120%; }
  }
  @keyframes hq-pulse {
    0%, 100% { transform: translateX(0%); width: 38%; }
    50% { transform: translateX(130%); width: 52%; }
  }

  /* --- Client welcome landing --- */
  .hq-welcome-wrap {
    position: relative;
    min-height: 72vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 2rem 1.25rem 3rem;
    margin: -0.5rem -1rem 1.5rem;
    border-radius: 24px;
    border: 1px solid var(--hq-border);
    background: radial-gradient(ellipse 100% 80% at 50% -20%, rgba(124, 58, 237, 0.35), transparent 55%),
      linear-gradient(165deg, rgba(15, 10, 28, 0.95) 0%, rgba(8, 8, 14, 0.98) 100%);
    overflow: hidden;
  }
  .hq-welcome-wrap::before {
    content: "";
    position: absolute;
    width: 140%;
    height: 140%;
    top: -20%;
    left: -20%;
    background: radial-gradient(circle at 30% 40%, rgba(168, 85, 247, 0.15), transparent 42%),
      radial-gradient(circle at 70% 55%, rgba(34, 211, 238, 0.12), transparent 40%);
    animation: hq-welcome-aurora 14s ease-in-out infinite alternate;
    pointer-events: none;
  }
  .hq-welcome-wrap::after {
    content: "";
    position: absolute;
    inset: 0;
    background: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.04'/%3E%3C/svg%3E");
    opacity: 0.5;
    pointer-events: none;
  }
  @keyframes hq-welcome-aurora {
    0% { transform: translate(0, 0) rotate(0deg); }
    100% { transform: translate(-3%, 2%) rotate(4deg); }
  }
  .hq-welcome-inner { position: relative; z-index: 2; max-width: 640px; }
  .hq-welcome-kicker {
    display: inline-block;
    font-size: 0.68rem;
    letter-spacing: 0.28em;
    text-transform: uppercase;
    color: #c4b5fd !important;
    margin-bottom: 1rem;
    animation: hq-fade-up 1s ease-out both;
  }
  .hq-welcome-title {
    font-size: clamp(2.1rem, 5vw, 3.1rem);
    font-weight: 700;
    line-height: 1.08;
    margin: 0 0 1rem;
    background: linear-gradient(120deg, #fff 0%, #e9d5ff 35%, #a5f3fc 70%, #fff 100%);
    background-size: 200% auto;
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    animation: hq-fade-up 0.9s ease-out 0.12s both, hq-shimmer-text 5s linear infinite;
  }
  @keyframes hq-shimmer-text {
    0% { background-position: 0% center; }
    100% { background-position: 200% center; }
  }
  @keyframes hq-fade-up {
    from { opacity: 0; transform: translateY(18px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .hq-welcome-lead {
    font-size: 1.05rem;
    line-height: 1.65;
    color: #d4d4d8 !important;
    margin: 0 0 1.75rem;
    animation: hq-fade-up 0.85s ease-out 0.28s both;
  }
  .hq-welcome-orbs {
    position: absolute;
    inset: 0;
    pointer-events: none;
    z-index: 1;
  }
  .hq-orb {
    position: absolute;
    border-radius: 50%;
    filter: blur(40px);
    opacity: 0.5;
    animation: hq-orb-float 8s ease-in-out infinite;
  }
  .hq-orb.a { width: 180px; height: 180px; background: #7c3aed; top: 8%; left: 5%; animation-delay: 0s; }
  .hq-orb.b { width: 220px; height: 220px; background: #0891b2; bottom: 5%; right: 0%; animation-delay: -2s; }
  .hq-orb.c { width: 120px; height: 120px; background: #a855f7; top: 40%; right: 12%; animation-delay: -4s; }
  @keyframes hq-orb-float {
    0%, 100% { transform: translate(0, 0) scale(1); }
    50% { transform: translate(12px, -16px) scale(1.06); }
  }
  .hq-welcome-foot {
    font-size: 0.78rem;
    color: #71717a !important;
    margin-top: 1.25rem;
    animation: hq-fade-up 1s ease-out 0.55s both;
  }

  /* Pixel vignette + micro-story (welcome landing) */
  .hq-pixel-panel {
    display: flex;
    flex-wrap: wrap;
    align-items: stretch;
    justify-content: center;
    gap: 1.35rem 1.75rem;
    margin: 1.65rem 0 0.25rem;
    padding: 1.15rem 0.35rem 1.35rem;
    border-top: 1px solid rgba(255, 255, 255, 0.09);
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  }
  .hq-pixel-frame {
    flex: 0 0 auto;
    align-self: center;
    padding: 10px 12px 12px;
    background: rgba(0, 0, 0, 0.42);
    border: 2px solid rgba(168, 85, 247, 0.5);
    border-radius: 10px;
    box-shadow: inset 0 0 0 2px rgba(255, 255, 255, 0.05), 0 14px 36px rgba(0, 0, 0, 0.4);
  }
  .hq-pixel-frame svg {
    display: block;
    width: min(300px, 78vw);
    height: auto;
    image-rendering: pixelated;
    image-rendering: crisp-edges;
  }
  .hq-pixel-tale {
    flex: 1 1 220px;
    max-width: 26rem;
    text-align: left;
    align-self: center;
  }
  .hq-pixel-line {
    font-family: 'DM Mono', ui-monospace, monospace !important;
    font-size: 0.74rem;
    line-height: 1.72;
    color: #ddd6fe !important;
    margin: 0 0 0.5rem 0;
    opacity: 0;
    animation: hq-fade-up 0.75s ease-out forwards;
  }
  .hq-pixel-line:nth-child(1) { animation-delay: 0.2s; }
  .hq-pixel-line:nth-child(2) { animation-delay: 0.55s; }
  .hq-pixel-line:nth-child(3) { animation-delay: 0.9s; }
  .hq-pixel-line strong { color: #f5f3ff !important; font-weight: 600; }
</style>
"""


def _build_connect_dots_svg() -> str:
    """Connect-the-dots mesh scaled to fill the left panel (square viewBox, no stretch)."""
    w = h = 500
    pad_x, pad_y = 36, 40
    inner_w = w - pad_x * 2
    inner_h = h - pad_y * 2
    rows = 8
    nodes: list[tuple[float, float]] = []
    grid: list[list[int]] = []
    idx = 0

    for ri in range(rows):
        t_row = ri / max(rows - 1, 1)
        # Wider at vertical center, taper toward top/bottom — fills the panel evenly
        band = math.sin(t_row * math.pi) ** 0.75
        n_cols = max(5, int(5 + band * 6))
        row_ids: list[int] = []
        for ci in range(n_cols):
            t_col = ci / max(n_cols - 1, 1)
            # Fan uses ~88% of inner width; spine continues to the right edge
            x = pad_x + t_col * inner_w * (0.52 + 0.36 * band)
            y = pad_y + t_row * inner_h + math.sin(t_col * math.pi * 1.05) * 10 * band
            nodes.append((x, y))
            row_ids.append(idx)
            idx += 1
        grid.append(row_ids)

    hub = (w - pad_x * 0.55, h * 0.5)
    spine_start = len(nodes)
    spine_x0 = pad_x + inner_w * 0.58
    for i in range(12):
        t = i / 11
        nodes.append(
            (
                spine_x0 + t * (hub[0] - spine_x0),
                h * 0.5 + math.sin(t * math.pi) * 10 * (1 - t * 0.5),
            )
        )

    edges: list[tuple[int, int]] = []
    for ri, row in enumerate(grid):
        for ci, nid in enumerate(row):
            for dr, dc in ((0, 1), (1, 0)):
                r2, c2 = ri + dr, ci + dc
                if r2 >= len(grid) or c2 >= len(grid[r2]):
                    continue
                j = grid[r2][c2]
                if j > nid:
                    edges.append((nid, j))
    for k in range(spine_start, len(nodes) - 1):
        edges.append((k, k + 1))

    lines: list[str] = []
    for i, j in edges:
        x1, y1 = nodes[i]
        x2, y2 = nodes[j]
        d = math.hypot(x2 - x1, y2 - y1)
        op = 0.2 + 0.5 * (1 - min(d / 62, 1))
        lines.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#7dd3fc" stroke-opacity="{op:.2f}" stroke-width="1.2"/>'
        )

    dots: list[str] = []
    for i, (x, y) in enumerate(nodes):
        r = 3.4 if i >= spine_start else 2.0 + (x / w) * 1.4
        fill = "#f0f9ff" if i >= len(nodes) - 1 else "#bae6fd"
        dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{fill}"/>')

    hx, hy = hub
    mid_y = h * 0.5
    return f"""<svg class="hq-login-mesh-svg" viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet"
  xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Connecting signals network">
  <defs>
    <radialGradient id="hqGlow" cx="35%" cy="50%" r="70%">
      <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.3"/>
      <stop offset="100%" stop-color="#38bdf8" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="{w}" height="{h}" fill="transparent"/>
  <ellipse cx="{w*0.32:.0f}" cy="{mid_y:.0f}" rx="{w*0.42:.0f}" ry="{h*0.4:.0f}" fill="url(#hqGlow)"/>
  <g stroke-linecap="round">{"".join(lines)}</g>
  <path d="M {pad_x} {mid_y:.0f} Q {w*0.28:.0f} {mid_y-40:.0f} {hx-36:.0f} {hy:.0f} T {hx:.0f} {hy:.0f}"
        fill="none" stroke="#a5f3fc" stroke-width="2.4" stroke-opacity="0.65"/>
  <g>{"".join(dots)}</g>
  <circle cx="{hx:.0f}" cy="{hy:.0f}" r="9" fill="#e0f2fe" opacity="0.4"/>
  <circle cx="{hx:.0f}" cy="{hy:.0f}" r="5" fill="#ffffff"/>
</svg>"""


_LOGIN_MESH_SVG = _build_connect_dots_svg()


def get_login_css() -> str:
    return """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Naskh+Arabic:wght@400;500;600&display=swap');

  [data-testid="stAppViewContainer"]:has(.hq-login-marker) [data-testid="stSidebar"] {
    display: none !important;
  }
  [data-testid="stAppViewContainer"]:has(.hq-login-marker) .block-container {
    max-width: 100% !important;
    padding: 0.75rem 1.25rem 1.5rem !important;
  }
  [data-testid="stAppViewContainer"]:has(.hq-login-marker)::before {
    background: radial-gradient(ellipse 70% 55% at 12% 40%, rgba(125, 211, 252, 0.14), transparent 55%),
      linear-gradient(165deg, #050814 0%, #0a1020 48%, #07070a 100%) !important;
  }
  .hq-login-card-wrap { display: none !important; }
  [data-testid="stAppViewContainer"]:has(.hq-login-marker) .hq-login-card-wrap + div {
    width: 100% !important;
    max-width: none !important;
    min-height: min(88vh, 860px);
    margin: 0 !important;
    padding: 0 !important;
    border: none !important;
    border-radius: 0 !important;
    background: transparent !important;
    box-shadow: none !important;
    align-items: stretch !important;
  }
  [data-testid="stAppViewContainer"]:has(.hq-login-marker) .hq-login-card-wrap + div [data-testid="column"]:first-child {
    border-right: 1px solid rgba(255, 255, 255, 0.07);
    background: radial-gradient(ellipse 95% 80% at 20% 50%, rgba(56, 189, 248, 0.12), transparent 62%),
      linear-gradient(165deg, rgba(10, 16, 32, 0.98) 0%, rgba(6, 8, 16, 0.99) 100%);
    padding: 0.5rem 0.25rem 0.5rem 0.5rem !important;
    min-height: min(88vh, 860px);
    display: flex;
    flex-direction: column;
    justify-content: center;
  }
  [data-testid="stAppViewContainer"]:has(.hq-login-marker) .hq-login-card-wrap + div [data-testid="column"]:last-child {
    padding: clamp(1.5rem, 4vw, 3rem) clamp(1.25rem, 3vw, 2.5rem) !important;
    display: flex;
    flex-direction: column;
    justify-content: center;
    min-height: min(88vh, 860px);
  }
  .hq-login-mesh-panel {
    width: 100%;
    height: 100%;
    min-height: min(82vh, 780px);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 1.5rem 1rem 1.25rem;
    box-sizing: border-box;
  }
  .hq-login-mesh-panel .hq-login-mesh-frame {
    width: 100%;
    max-width: 100%;
    aspect-ratio: 1 / 1;
    max-height: min(72vh, calc(50vw - 2rem));
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .hq-login-mesh-panel svg.hq-login-mesh-svg {
    width: 100% !important;
    height: 100% !important;
    max-width: 100% !important;
    max-height: 100% !important;
    display: block !important;
    filter: drop-shadow(0 12px 40px rgba(56, 189, 248, 0.14));
  }
  .hq-login-mesh-tag {
    font-family: 'DM Mono', ui-monospace, monospace !important;
    font-size: clamp(0.65rem, 1vw, 0.8rem);
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: #67e8f9 !important;
    margin: 1.25rem 0 0;
    opacity: 0.92;
    align-self: flex-start;
    padding-left: 0.5rem;
  }
  .hq-login-kicker {
    font-size: 0.72rem;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: #94a3b8 !important;
    margin: 0 0 0.85rem;
  }
  .hq-login-title {
    font-size: clamp(2rem, 4.2vw, 3.15rem);
    font-weight: 700;
    line-height: 1.08;
    margin: 0 0 0.35rem;
    color: #9bdcfb !important;
    letter-spacing: -0.03em;
  }
  .hq-login-title em {
    font-style: normal;
    color: #e0f2fe !important;
  }
  .hq-login-byline {
    font-size: 0.88rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #94a3b8 !important;
    margin: 0 0 0.65rem;
    line-height: 1.5;
  }
  .hq-login-byline strong {
    color: #e0f2fe !important;
    font-weight: 600;
    letter-spacing: 0.08em;
  }
  .hq-login-byline-ar {
    font-family: 'Noto Naskh Arabic', 'Traditional Arabic', serif !important;
    font-size: 1.12rem;
    font-weight: 500;
    color: #cbd5e1 !important;
    margin: 0 0 1.5rem;
    line-height: 1.65;
    direction: rtl;
    text-align: right;
    unicode-bidi: plaintext;
  }
  .hq-login-byline-ar strong {
    color: #f0f9ff !important;
    font-weight: 600;
    font-size: 1.18rem;
  }
  .hq-login-byline-ar .hq-ar-dim {
    color: #67e8f9 !important;
    font-size: 0.95rem;
    opacity: 0.92;
  }
  .hq-login-field-label {
    font-size: 0.72rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #94a3b8 !important;
    margin: 0.35rem 0 0.35rem;
  }
  .hq-login-foot,
  .hq-login-status {
    font-family: 'DM Mono', ui-monospace, monospace !important;
    font-size: 0.78rem;
    line-height: 1.65;
    color: #e2e8f0 !important;
    margin: 1.1rem 0 0;
  }
  .hq-login-status--err { color: #fda4af !important; }

  [data-testid="stAppViewContainer"]:has(.hq-login-marker) .stTextInput > div > div {
    background: rgba(255, 255, 255, 0.04) !important;
    border: 1px solid rgba(148, 163, 184, 0.35) !important;
    border-radius: 12px !important;
  }
  [data-testid="stAppViewContainer"]:has(.hq-login-marker) .stTextInput input {
    color: #f8fafc !important;
    font-family: 'DM Mono', ui-monospace, monospace !important;
    font-size: 0.88rem !important;
  }
  [data-testid="stAppViewContainer"]:has(.hq-login-marker) .stTextInput input::placeholder {
    color: #64748b !important;
  }
  [data-testid="stAppViewContainer"]:has(.hq-login-marker) .stButton > button,
  [data-testid="stAppViewContainer"]:has(.hq-login-marker) [data-testid="baseButton-primary"] {
    background: #f8fafc !important;
    color: #0f172a !important;
    -webkit-text-fill-color: #0f172a !important;
    border: none !important;
    box-shadow: 0 8px 28px rgba(248, 250, 252, 0.12) !important;
    font-weight: 700 !important;
    border-radius: 999px !important;
    padding: 0.62rem 1.25rem !important;
  }
  [data-testid="stAppViewContainer"]:has(.hq-login-marker) .stButton > button:hover,
  [data-testid="stAppViewContainer"]:has(.hq-login-marker) [data-testid="baseButton-primary"]:hover {
    background: #ffffff !important;
    color: #020617 !important;
    -webkit-text-fill-color: #020617 !important;
    box-shadow: 0 10px 32px rgba(248, 250, 252, 0.2) !important;
  }
  [data-testid="stAppViewContainer"]:has(.hq-login-marker) .stButton > button *,
  [data-testid="stAppViewContainer"]:has(.hq-login-marker) [data-testid="baseButton-primary"] *,
  [data-testid="stAppViewContainer"]:has(.hq-login-marker) .stButton > button p,
  [data-testid="stAppViewContainer"]:has(.hq-login-marker) .stButton > button span,
  [data-testid="stAppViewContainer"]:has(.hq-login-marker) .stButton > button div {
    color: #0f172a !important;
    -webkit-text-fill-color: #0f172a !important;
    fill: #0f172a !important;
  }
  @media (max-width: 900px) {
    [data-testid="stAppViewContainer"]:has(.hq-login-marker) .hq-login-card-wrap + div [data-testid="column"]:first-child {
      border-right: none !important;
      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    }
  }
</style>
"""


def render_login_mesh_component() -> None:
    """Render connect-the-dots mesh (inline SVG — preserves aspect ratio)."""
    import streamlit as st

    st.markdown(
        f'<div class="hq-login-mesh-panel">'
        f'<div class="hq-login-mesh-frame">{_LOGIN_MESH_SVG}</div>'
        '<p class="hq-login-mesh-tag">Signals connect · intent surfaces</p></div>',
        unsafe_allow_html=True,
    )


def render_login_headline() -> str:
    return """
    <p class="hq-login-kicker">Exclusive access</p>
    <h1 class="hq-login-title">Welcome to <em>hirequity</em></h1>
    <p class="hq-login-byline">Powered by <strong>ELV8 AI</strong></p>
    <p class="hq-login-byline-ar" lang="ar" dir="rtl">
      <span class="hq-ar-dim">محركات من</span> <strong>سلودوبيت AI</strong>
    </p>
    """


def render_client_welcome(brand: str) -> str:
    """Full-width animated welcome panel (use with get_global_css already on the page)."""
    safe = escape(brand)
    return f"""
    <div class="hq-welcome-wrap">
      <div class="hq-welcome-orbs" aria-hidden="true">
        <div class="hq-orb a"></div>
        <div class="hq-orb b"></div>
        <div class="hq-orb c"></div>
      </div>
      <div class="hq-welcome-inner">
        <span class="hq-welcome-kicker">Welcome</span>
        <h1 class="hq-welcome-title">{safe}</h1>
        <p class="hq-welcome-lead">
          Your live hiring-intent workspace is warming up in the background — job boards, scoring,
          and pipeline context — so when you step in, the first rows are already in motion.
        </p>
        <div class="hq-pixel-panel">
          <div class="hq-pixel-frame">{_WELCOME_PIXEL_SVG}</div>
          <div class="hq-pixel-tale">
            <p class="hq-pixel-line">
              <strong>02:14</strong> — Another sales role hits the wire. The city pretends to sleep.
            </p>
            <p class="hq-pixel-line">
              Miles away, a stack blinks: signals stack, tiers settle, someone worth the ping appears.
            </p>
            <p class="hq-pixel-line">
              <strong>{safe}</strong> is the quiet layer that turns that noise into a room you can own.
            </p>
          </div>
        </div>
        <p class="hq-welcome-foot">
          Enjoy the vignette while data loads — then step into the command center when you are ready.
        </p>
      </div>
    </div>
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


def render_loader(title: str, subtitle: str) -> str:
    return f"""
    <div class="hq-loader">
      <h3>{title}</h3>
      <p>{subtitle}</p>
      <div class="hq-loader-rail"><div class="hq-loader-bar"></div></div>
    </div>
    """
