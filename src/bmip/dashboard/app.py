"""BMIP analytics dashboard v1 (W1-D).

Four business metrics, two time filters, and a freshness badge per metric. The
page reads only the Query API, so the authorisation and fallback rules are the
same ones an analyst gets from curl. No data is invented: a metric without a
value shows the API's own explanation (for example "belum ada model").
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pandas as pd
import streamlit as st

from bmip.dashboard.client import ApiClient, ApiError

SYMBOL = os.getenv("BMIP_DASHBOARD_SYMBOL", "BTCUSDT")
BADGES = {"ok": "🟢", "warn": "🟠", "stale": "🔴", "unknown": "⚪"}


st.set_page_config(
    page_title="BMIP - Bitcoin Market Intelligence",
    page_icon="₿",
    layout="wide",
)


def client() -> ApiClient:
    return ApiClient()


@st.cache_data(ttl=30, show_spinner=False)
def fetch_market_latest(target: str, symbol: str) -> dict[str, Any]:
    return ApiClient(target).market_latest(symbol)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_ohlc(target: str, symbol: str, start: str | None, end: str | None) -> dict[str, Any]:
    return ApiClient(target).market_ohlc(symbol, start=start, end=end)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_volatility(
    target: str, symbol: str, start: str | None, end: str | None
) -> dict[str, Any]:
    return ApiClient(target).volatility_range(symbol, start=start, end=end)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_sentiment(target: str, start: str | None, end: str | None) -> dict[str, Any]:
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


def badge(status: str | None) -> str:
    return BADGES.get(status or "unknown", "⚪")


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


def freshness_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["metric"]: row for row in payload.get("data", [])}


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


def api_target() -> str:
    return os.getenv("BMIP_API_BASE_URL") or "http://localhost:8000"


def main() -> None:
    target = api_target()
    st.title("₿ Bitcoin Market Intelligence")
    st.caption(
        "Sumber: Query API BMIP. Semua angka adalah hasil pipeline "
        "bronze → silver → gold → serving."
    )

    with st.sidebar:
        st.header("Filter")
        preset = st.radio(
            "Rentang waktu",
            ["24 jam", "7 hari", "14 hari", "Semua data", "Rentang khusus"],
            index=0,
        )
        custom = st.date_input(
            "Rentang khusus (UTC)",
            value=(datetime.now(UTC).date() - timedelta(days=7), datetime.now(UTC).date()),
            disabled=preset != "Rentang khusus",
        )
        symbol = st.text_input("Simbol", value=SYMBOL)
        if st.button("Muat ulang", use_container_width=True):
            st.cache_data.clear()
        st.caption(f"API: {target}")

    start, end = filter_window(preset, custom)

    try:
        freshness = fetch_freshness(target)
        latest = fetch_market_latest(target, symbol)
        sentiment = fetch_sentiment(target, start, end)
        model = fetch_model(target)
        quality = fetch_quality(target)
        ohlc = fetch_ohlc(target, symbol, start, end)
        volatility = fetch_volatility(target, symbol, start, end)
    except ApiError as exc:
        st.error(f"API menolak permintaan: {exc}")
        st.stop()

    meta = latest.get("meta", {})
    fresh = freshness_map(freshness)
    clock = meta.get("clock", "live")
    as_of = meta.get("as_of", "")

    if clock == "replay":
        st.warning(
            f"Mode replay: jam efektif = {as_of}. Badge freshness dihitung terhadap jam ini, "
            "bukan waktu dinding."
        )
    if meta.get("stale"):
        st.warning("Jalur lake tidak tersedia; angka berasal dari tabel serving (X-Data-Stale).")

    st.caption(f"Data as-of: {as_of} · instance: {meta.get('instance', '—')} · simbol: {symbol}")

    market_row = latest.get("data") or {}
    sentiment_row = sentiment.get("data") or []
    sentiment_latest = sentiment_row[0] if sentiment_row else {}
    market_badge = badge(fresh.get("market", {}).get("status"))
    sentiment_badge = badge(fresh.get("sentiment", {}).get("status"))
    model_badge = badge(fresh.get("predictions", {}).get("status"))

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(
            f"Harga terakhir ({symbol})",
            fmt(market_row.get("close")),
            help=f"window_start {market_row.get('window_start', '—')}",
        )
        st.caption(f"{market_badge} market · {fresh.get('market', {}).get('status', 'unknown')}")
    with col2:
        st.metric(
            "Volatilitas jam terakhir",
            fmt(market_row.get("realized_vol_1h"), 6),
            help="Std dev log return 1 menit di dalam jam terakhir (gold.mart_market).",
        )
        st.caption(f"{market_badge} freshness pasar")
    with col3:
        st.metric(
            "Skor sentimen",
            fmt(sentiment_latest.get("mean_sentiment"), 3),
            help="Rata-rata compound VADER per jam (gold.mart_sentiment).",
        )
        st.caption(
            f"{sentiment_badge} sentimen · {sentiment_latest.get('post_count', 0)} post"
        )
    with col4:
        if model.get("status") == "available":
            st.metric(
                "Prediksi jam berikutnya",
                fmt(model.get("metrics", {}).get("latest_prediction"), 6),
                help="Model champion, dilayani oleh W2-A.",
            )
            st.caption(f"{model_badge} model v{model.get('version')}")
        else:
            st.metric("Prediksi jam berikutnya", "belum ada model")
            st.caption(f"{model_badge} W2-A belum mendaftarkan champion")

    if model.get("status") != "available":
        st.info(
            "**Belum ada model.** Endpoint `/v1/predict` mengembalikan "
            "`status=not_available` dan dashboard tidak menampilkan angka rekaan. "
            "Training, registry MLflow, dan gate promosi adalah lingkup W2-A."
        )

    st.divider()
    left, right = st.columns(2)

    with left:
        st.subheader("Harga (OHLC, 1 jam)")
        rows = ohlc.get("data", [])
        if rows:
            frame = pd.DataFrame(rows)
            # Drop the tz so the chart labels stay in UTC instead of being
            # converted to the browser's local timezone.
            frame["window_start"] = pd.to_datetime(
                frame["window_start"], utc=True
            ).dt.tz_localize(None)
            st.line_chart(frame.set_index("window_start")["close"], height=240)
            st.caption(
                f"{len(rows)} bar · sumber {ohlc.get('meta', {}).get('source')} · "
                f"stale={ohlc.get('meta', {}).get('stale')} · sumbu waktu UTC"
            )
        else:
            st.info(
                "Tidak ada bar pada rentang ini. Pilih 'Semua data' atau rentang lain; "
                "lihat badge freshness untuk jam data terakhir."
            )

    with right:
        st.subheader("Volatilitas terealisasi (1 jam)")
        rows = volatility.get("data", [])
        if rows:
            frame = pd.DataFrame(rows)
            # Drop the tz so the chart labels stay in UTC instead of being
            # converted to the browser's local timezone.
            frame["window_start"] = pd.to_datetime(
                frame["window_start"], utc=True
            ).dt.tz_localize(None)
            st.line_chart(frame.set_index("window_start")["realized_vol_1h"], height=240)
            st.caption(
                f"{len(rows)} bar · sumber {volatility.get('meta', {}).get('source')} · "
                f"stale={volatility.get('meta', {}).get('stale')} · sumbu waktu UTC"
            )
        else:
            st.info("Belum ada bar volatilitas pada rentang ini.")

    st.subheader("Sentimen per jam")
    if sentiment_row:
        frame = pd.DataFrame(sentiment_row)
        frame["window_start"] = pd.to_datetime(
            frame["window_start"], utc=True
        ).dt.tz_localize(None)
        frame = frame.set_index("window_start")
        st.bar_chart(frame["mean_sentiment"], height=200)
        st.caption(
            f"{len(sentiment_row)} jam · model "
            f"{sentiment_latest.get('sentiment_model_version', '—')} · "
            "sumbu waktu UTC"
        )
    else:
        st.info("Belum ada agregat sentimen pada rentang ini.")

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
        st.dataframe(pd.DataFrame(freshness.get("data", [])), use_container_width=True)
        st.caption(
            "status ok = umur data ≤ SLO · warn = ≤ 2× SLO · stale = di atasnya · "
            "unknown = belum ada data."
        )


if __name__ == "__main__":
    try:
        main()
    except (ApiError, httpx.HTTPError) as exc:  # pragma: no cover - UI guard
        st.error(f"Dashboard tidak bisa memuat data: {exc}")
