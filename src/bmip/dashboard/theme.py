"""Visual system for the BMIP dashboard.

Rules from the W1-D revision: Poppins, light mode only, five colours
(black, grey, white, navy, pink), no emoji, no decorative chrome.
Charts are explicit Altair specs so the Streamlit defaults (blue/green) never
appear on screen.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

# ----------------------------------------------------------------- palette

WHITE = "#FFFFFF"
SURFACE = "#F5F6F8"
BORDER = "#E5E7EB"
MUTED = "#6B7280"
BLACK = "#0A0A0A"
NAVY = "#0B1F3A"
NAVY_SOFT = "#163A66"
PINK = "#E85D9E"

FONT_STACK = "'Poppins', 'Segoe UI', 'Helvetica Neue', sans-serif"

FONT_LINKS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600&display=swap"
      rel="stylesheet">
"""

CSS = f"""
<style>
html, body, .stApp, .stApp p, .stApp h1, .stApp h2, .stApp h3, .stApp h4,
.stApp label, .stApp button, .stApp input, .stApp select, .stApp textarea,
[data-testid="stMetricLabel"], [data-testid="stMetricValue"],
[data-testid="stWidgetLabel"], [data-testid="stMarkdownContainer"] {{
    font-family: {FONT_STACK} !important;
}}
/* Streamlit's icon glyphs are ligatures from Material Symbols; a global font
   override turns them into words, so the icon font must be restored. */
[data-testid="stIconMaterial"], .material-symbols-rounded,
.material-icons, .material-icons-round, [data-testid="stExpanderToggleIcon"] {{
    font-family: 'Material Symbols Rounded', 'Material Icons' !important;
}}
.stApp {{ background: {WHITE}; color: {BLACK}; }}
[data-testid="stSidebar"] {{
    background: {SURFACE};
    border-right: 1px solid {BORDER};
}}
[data-testid="stHeader"] {{ background: {WHITE}; }}
h1, h2, h3, h4 {{ color: {NAVY} !important; font-weight: 600 !important; }}
p, label {{ color: {BLACK}; }}
[data-testid="stMetricLabel"] p {{ color: {MUTED} !important; font-weight: 500 !important; }}
[data-testid="stMetricValue"] {{ color: {NAVY} !important; font-weight: 600 !important; }}
[data-testid="stMetricValue"] > div {{
    font-size: 1.6rem;
    line-height: 1.2;
    white-space: normal;
}}
hr {{ border-color: {BORDER}; }}
.stButton > button {{
    background: {NAVY};
    color: {WHITE};
    border: 1px solid {NAVY};
    border-radius: 6px;
    font-weight: 500;
}}
.stButton > button:hover {{
    background: {PINK};
    border-color: {PINK};
    color: {WHITE};
}}
[data-testid="stExpander"] {{ border: 1px solid {BORDER}; border-radius: 6px; }}
[data-testid="stExpander"] summary {{ color: {NAVY}; font-weight: 500; }}
/* Streamlit alerts default to blue/red; keep them inside the palette. */
[data-testid="stAlert"] {{
    background: {SURFACE} !important;
    border: 1px solid {BORDER} !important;
    border-left: 3px solid {NAVY} !important;
    color: {BLACK} !important;
}}
[data-testid="stAlert"] p, [data-testid="stAlert"] div, [data-testid="stAlert"] span {{
    color: {BLACK} !important;
}}
[data-testid="stAlert"] svg {{ fill: {NAVY} !important; }}
/* Remove Streamlit chrome that would introduce colours outside the palette. */
[data-testid="stToolbar"] {{ display: none; }}
[data-testid="stDecoration"] {{ display: none; }}
#MainMenu {{ visibility: hidden; }}
footer {{ visibility: hidden; }}
</style>
"""


def apply() -> None:
    st.markdown(FONT_LINKS + CSS, unsafe_allow_html=True)


# ------------------------------------------------------------------ charts


def _axis(title: str | None = None) -> alt.Axis:
    return alt.Axis(
        labelColor=MUTED,
        title=title,
        titleColor=MUTED,
        gridColor=BORDER,
        domainColor=BORDER,
        tickColor=BORDER,
        labelFont=FONT_STACK,
        titleFont=FONT_STACK,
    )


def price_line(frame: pd.DataFrame, *, height: int = 300) -> alt.Chart:
    return (
        alt.Chart(frame)
        .mark_line(color=NAVY, strokeWidth=2)
        .encode(
            x=alt.X("window_start:T", axis=_axis()),
            y=alt.Y("close:Q", axis=_axis()),
        )
        .properties(height=height, width="container", background=WHITE)
    )


def value_bars(
    frame: pd.DataFrame,
    column: str,
    *,
    color: str = PINK,
    height: int = 260,
    domain: tuple[float, float] | None = None,
) -> alt.LayerChart:
    scale = alt.Scale(domain=list(domain)) if domain else alt.Scale()
    bars = (
        alt.Chart(frame)
        .mark_bar(color=color, size=28)
        .encode(
            x=alt.X("window_start:T", axis=_axis()),
            y=alt.Y(f"{column}:Q", axis=_axis(), scale=scale),
        )
    )
    baseline = (
        alt.Chart(pd.DataFrame({"y": [0.0]}))
        .mark_rule(color=BORDER, strokeWidth=1)
        .encode(y="y:Q")
    )
    return (bars + baseline).properties(
        height=height, width="container", background=WHITE
    )
