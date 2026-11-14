"""BMIP analytics dashboard v1.

Layout: one price row, then sentiment and volatility side by side. Four
business metrics, two time filters, and a data-quality panel. The page reads
only the Query API; nothing is synthesised when a value is missing.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from bmip.dashboard import theme
from bmip.dashboard.client import ApiClient, ApiError

load_dotenv()

SYMBOL = os.getenv("BMIP_DASHBOARD_SYMBOL", "BTCUSDT")

st.set_page_config(
    page_title="Bitcoin Market Intelligence Platform (BMIP)",
    layout="wide",
)
theme.apply()


def api_target() -> str:
    return os.getenv("BMIP_API_BASE_URL") or "http://localhost:8000"


@st.cache_data(ttl=30, show_spinner=False)
def fetch_market_latest(target: str, symbol: str) -> dict[str, Any]:
    return ApiClient(target).market_latest(symbol)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_ohlc(
    target: str, symbol: str, start: str | None, end: str | None
) -> dict[str, Any]:
    return ApiClient(target).market_ohlc(symbol, start=start, end=end)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_volatility(
    target: str, symbol: str, start: str | None, end: str | None
) -> dict[str, Any]:
    return ApiClient(target).volatility_range(symbol, start=start, end=end)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_sentiment(
    target: str, start: str | None, end: str | None
) -> dict[str, Any]:
    return ApiClient(target).sentiment_hourly(start=start, end=end)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_freshness(target: str) -> dict[str, Any]:
    return ApiClient(target).freshness()


@st.cache_data(ttl=30, show_spinner=False)
def fetch_model(target: str) -> dict[str, Any]:
    return ApiClient(target).model_latest()


@st.cache_data(ttl=30, show_spinner=False)
def fetch_quality(target: str) -> dict[str, Any]:
    return ApiClient(target).quality_status()


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def fmt(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:,.{digits}f}"


def filter_window(preset: str, custom: Any) -> tuple[str | None, str | None]:
    """Two time filters: a preset window and an explicit date range."""
    if preset != "Rentang khusus":
        days = {"24 jam": 1, "7 hari": 7, "14 hari": 14}.get(preset)
        if days is None:
            return None, None
        end = datetime.now(UTC)
        return (end - timedelta(days=days)).isoformat(), end.isoformat()
    if not isinstance(custom, (tuple, list)) or len(custom) < 2:
        return None, None
    start, end = custom[0], custom[1]
    if start is None or end is None:
        return None, None
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
    end_dt = datetime.combine(end, datetime.min.time(), tzinfo=UTC) + timedelta(days=1)
    return start_dt.isoformat(), end_dt.isoformat()


def utc_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Naive UTC timestamps so chart labels are not converted to local time."""
    frame = pd.DataFrame(rows)
    frame["window_start"] = pd.to_datetime(
        frame["window_start"], utc=True
    ).dt.tz_localize(None)
    return frame.set_index("window_start").reset_index()


def main() -> None:
    target = api_target()
    st.title("Bitcoin Market Intelligence Platform (BMIP)")

    with st.sidebar:
        st.header("Filter")
        preset = st.selectbox(
            "Rentang waktu",
            ["24 jam", "7 hari", "14 hari", "Semua data", "Rentang khusus"],
            index=0,
        )
        custom = st.date_input(
            "Rentang khusus (UTC)",
            value=(
                datetime.now(UTC).date() - timedelta(days=7),
                datetime.now(UTC).date(),
            ),
            disabled=preset != "Rentang khusus",
        )
        if st.button("Muat ulang", width="stretch"):
            st.cache_data.clear()
        st.caption(f"API: {target}")

    start, end = filter_window(preset, custom)

    try:
        latest = fetch_market_latest(target, SYMBOL)
        sentiment = fetch_sentiment(target, start, end)
        model = fetch_model(target)
        quality = fetch_quality(target)
        ohlc = fetch_ohlc(target, SYMBOL, start, end)
        volatility = fetch_volatility(target, SYMBOL, start, end)
        freshness = fetch_freshness(target)
    except ApiError as exc:
        st.error(f"API menolak permintaan: {exc}")
        st.stop()

    market_row = latest.get("data") or {}
    sentiment_rows = sentiment.get("data") or []
    sentiment_latest = sentiment_rows[0] if sentiment_rows else {}

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(
            f"Harga terakhir ({SYMBOL})",
            fmt(market_row.get("close")),
            help=f"window_start {market_row.get('window_start', '—')}",
        )
    with col2:
        st.metric(
            "Volatilitas jam terakhir",
            fmt(market_row.get("realized_vol_1h"), 6),
            help="Std dev log return 1 menit di dalam jam terakhir (gold.mart_market).",
        )
    with col3:
        st.metric(
            "Skor sentimen",
            fmt(sentiment_latest.get("mean_sentiment"), 3),
            help="Rata-rata compound VADER per jam (gold.mart_sentiment).",
        )
    with col4:
        if model.get("status") == "available":
            st.metric(
                "Prediksi jam berikutnya",
                fmt(model.get("metrics", {}).get("latest_prediction"), 6),
                help="Model champion.",
            )
        else:
            st.metric("Prediksi jam berikutnya", "belum ada model")

    st.divider()

    st.subheader("Harga (OHLC, 1 jam)")
    if ohlc.get("data"):
        st.altair_chart(theme.price_line(utc_frame(ohlc["data"])))
    else:
        st.info(
            "Tidak ada bar pada rentang ini. Pilih 'Semua data' atau rentang lain."
        )

    left, right = st.columns(2)
    with left:
        st.subheader("Sentimen per jam")
        if sentiment_rows:
            st.altair_chart(
                theme.value_bars(
                    utc_frame(sentiment_rows),
                    "mean_sentiment",
                    color=theme.PINK,
                    domain=(-1.0, 1.0),
                )
            )
        else:
            st.info("Belum ada agregat sentimen pada rentang ini.")

    with right:
        st.subheader("Volatilitas terealisasi (1 jam)")
        if volatility.get("data"):
            st.altair_chart(
                theme.value_bars(
                    utc_frame(volatility["data"]),
                    "realized_vol_1h",
                    color=theme.NAVY_SOFT,
                )
            )
        else:
            st.info("Belum ada bar volatilitas pada rentang ini.")

    with st.expander("Kualitas data dan freshness"):
        quality_data = quality.get("data", {})
        st.write(
            {
                "status": quality_data.get("status", "unknown"),
                "run_ts": quality_data.get("run_ts"),
                "critical_failures": quality_data.get("critical_failures", 0),
                "warning_failures": quality_data.get("warning_failures", 0),
                "commit": quality_data.get("commit_sha"),
            }
        )
        for failure in quality_data.get("failures", [])[:10]:
            st.write(
                f"- {failure.get('severity')} · {failure.get('suite')} · "
                f"{failure.get('rule_id')} — {failure.get('detail')}"
            )
        rows = freshness.get("data", [])
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch")
        st.caption(
            "ok = umur data <= SLO · warn = <= 2x SLO · stale = di atasnya · "
            "unknown = belum ada data"
        )


if __name__ == "__main__":
    try:
        main()
    except (ApiError, httpx.HTTPError) as exc:  # pragma: no cover - UI guard
        st.error(f"Dashboard tidak bisa memuat data: {exc}")
