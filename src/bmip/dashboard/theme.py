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

WHITE = "#FFFFFF"
SURFACE = "#F5F6F8"
BORDER = "#E5E7EB"
MUTED = "#6B7280"
BLACK = "#0A0A0A"
NAVY = "#0B1F3A"
NAVY_SOFT = "#163A66"
PINK = "#E85D9E"
DEEP_PINK = "#B02862"
AMBER = "#D97706"

SERIES_COLORS = {
    "BTCUSDT": NAVY,
    "ETHUSDT": PINK,
    "BNBUSDT": NAVY_SOFT,
    "SOLUSDT": DEEP_PINK,
    "XRPUSDT": MUTED,
}

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
.stButton > button p, .stButton > button div, .stButton > button span {{
    color: {WHITE} !important;
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
/* Keep the sidebar toggle reachable: Streamlit shows it on hover only, which
   makes a collapsed sidebar look like a missing filter panel. */
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapsedControl"] {{
    visibility: visible !important;
    opacity: 1 !important;
}}
/* Remove only the deploy chrome, never the sidebar controls. */
[data-testid="stAppDeployButton"] {{ display: none; }}
[data-testid="stDecoration"] {{ display: none; }}
#MainMenu {{ visibility: hidden; }}
footer {{ visibility: hidden; }}
</style>
"""


def apply() -> None:
    st.markdown(FONT_LINKS + CSS, unsafe_allow_html=True)


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
        alt.Chart(pd.DataFrame({"y": [0.0]})).mark_rule(color=BORDER, strokeWidth=1).encode(y="y:Q")
    )
    return (bars + baseline).properties(height=height, width="container", background=WHITE)


def multi_line(
    frame: pd.DataFrame,
    column: str,
    *,
    height: int = 320,
    y_title: str | None = None,
    domain: tuple[float, float] | None = None,
) -> alt.Chart:
    """One line per symbol; caller supplies window_start, symbol, value."""
    if frame.empty:
        return alt.Chart(pd.DataFrame({"x": [], "y": []})).mark_line()
    scale = alt.Scale(domain=list(domain)) if domain else alt.Scale()
    return (
        alt.Chart(frame)
        .mark_line(strokeWidth=2)
        .encode(
            x=alt.X("window_start:T", axis=_axis()),
            y=alt.Y(f"{column}:Q", axis=_axis(y_title), scale=scale),
            color=alt.Color(
                "symbol:N",
                scale=alt.Scale(
                    domain=list(SERIES_COLORS),
                    range=list(SERIES_COLORS.values()),
                ),
                legend=alt.Legend(orient="top", labelFont=FONT_STACK, title=None),
            ),
            tooltip=["symbol:N", alt.Tooltip(f"{column}:Q", format=".4f")],
        )
        .properties(height=height, width="container", background=WHITE)
    )


def heatmap(matrix: pd.DataFrame, *, height: int = 360) -> alt.Chart:
    if matrix.empty:
        return alt.Chart(pd.DataFrame({"x": [], "y": []})).mark_rect()
    long = matrix.reset_index().melt(id_vars="index", var_name="right", value_name="correlation")
    long = long.rename(columns={"index": "left"})
    base = alt.Chart(long).encode(
        x=alt.X("right:N", axis=_axis(), sort=list(matrix.columns)),
        y=alt.Y("left:N", axis=_axis(), sort=list(matrix.index)),
    )
    rect = base.mark_rect().encode(
        color=alt.Color(
            "correlation:Q",
            scale=alt.Scale(domain=[-1, 0, 1], range=[NAVY, WHITE, PINK]),
            legend=alt.Legend(title="r", labelFont=FONT_STACK, titleFont=FONT_STACK),
        ),
        tooltip=["left:N", "right:N", alt.Tooltip("correlation:Q", format=".3f")],
    )
    text = base.mark_text(font=FONT_STACK, fontSize=11).encode(
        text=alt.Text("correlation:Q", format=".2f"),
        color=alt.condition(
            (alt.datum.correlation > 0.55) | (alt.datum.correlation < -0.55),
            alt.value(WHITE),
            alt.value(BLACK),
        ),
    )
    return (rect + text).properties(height=height, width="container", background=WHITE)


def correlation_line(frame: pd.DataFrame, *, height: int = 260) -> alt.Chart:
    if frame.empty:
        return alt.Chart(pd.DataFrame({"x": [], "y": []})).mark_line()
    return (
        alt.Chart(frame)
        .mark_line(color=NAVY, strokeWidth=2)
        .encode(
            x=alt.X("window_start:T", axis=_axis()),
            y=alt.Y("correlation:Q", axis=_axis("r"), scale=alt.Scale(domain=[-1, 1])),
        )
        .properties(height=height, width="container", background=WHITE)
    )


def lead_lag_bars(frame: pd.DataFrame, *, height: int = 240) -> alt.Chart:
    if frame.empty:
        return alt.Chart(pd.DataFrame({"x": [], "y": []})).mark_bar()
    return (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            x=alt.X("lag:O", axis=_axis("lag (jam)")),
            y=alt.Y("correlation:Q", axis=_axis("r"), scale=alt.Scale(domain=[-1, 1])),
            color=alt.condition(
                alt.datum.correlation >= 0,
                alt.value(PINK),
                alt.value(NAVY),
            ),
            tooltip=["lag:O", alt.Tooltip("correlation:Q", format=".3f")],
        )
        .properties(height=height, width="container", background=WHITE)
    )


def scatter(
    frame: pd.DataFrame,
    x: str,
    y: str,
    *,
    height: int = 280,
) -> alt.Chart:
    if frame.empty:
        return alt.Chart(pd.DataFrame({"x": [], "y": []})).mark_circle()
    return (
        alt.Chart(frame)
        .mark_circle(size=45, color=PINK, opacity=0.7)
        .encode(
            x=alt.X(f"{x}:Q", axis=_axis(x)),
            y=alt.Y(f"{y}:Q", axis=_axis(y)),
            tooltip=[alt.Tooltip(x, format=".4f"), alt.Tooltip(y, format=".4f")],
        )
        .properties(height=height, width="container", background=WHITE)
    )
