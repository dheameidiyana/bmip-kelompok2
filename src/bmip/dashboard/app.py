"""Multi-Asset Market Intelligence Platform dashboard.

The page is read-only: every number comes from the Query API. It is split into
small tabs so each question gets one focused view instead of one long page.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import numpy as np
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from bmip.common.logging import configure_logging, get_logger
from bmip.common.symbols import DEFAULT_MARKET_SYMBOLS
from bmip.dashboard import analytics as an
from bmip.dashboard import theme
from bmip.dashboard.client import ApiClient, ApiError

load_dotenv()

PAGE_TITLE = "Multi-Asset Market Intelligence Platform"
SUBTITLE = "Lima Binance spot pair · BTC, ETH, BNB, SOL, XRP"


@st.cache_resource
def _logging() -> bool:
    configure_logging(service="dashboard")
    get_logger("bmip.dashboard").info(
        "dashboard started", extra={"ctx_target": os.getenv("BMIP_API_BASE_URL", "")}
    )
    return True


_logging()


def dashboard_symbols() -> tuple[str, ...]:
    raw = os.getenv("BMIP_DASHBOARD_SYMBOLS") or os.getenv("MARKET_SYMBOLS")
    if not raw:
        return DEFAULT_MARKET_SYMBOLS
    symbols = tuple(part.strip().upper() for part in raw.split(",") if part.strip())
    return symbols or DEFAULT_MARKET_SYMBOLS


SYMBOLS = dashboard_symbols()

st.set_page_config(
    page_title=PAGE_TITLE,
    layout="wide",
    initial_sidebar_state="expanded",
)
theme.apply()


def api_target() -> str:
    return os.getenv("BMIP_API_BASE_URL") or "http://localhost:8000"


@st.cache_data(ttl=30, show_spinner=False)
def fetch_market_latest(target: str, symbol: str) -> dict[str, Any]:
    return ApiClient(target).market_latest(symbol)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_all_latest(target: str, symbols: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    client = ApiClient(target)
    return {symbol: client.market_latest(symbol) for symbol in symbols}


@st.cache_data(ttl=30, show_spinner=False)
def fetch_ohlc(target: str, symbol: str, start: str | None, end: str | None) -> dict[str, Any]:
    return ApiClient(target).market_ohlc(symbol, start=start, end=end, limit=500)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_all_ohlc(
    target: str, symbols: tuple[str, ...], start: str | None, end: str | None
) -> dict[str, dict[str, Any]]:
    client = ApiClient(target)
    return {
        symbol: client.market_ohlc(symbol, start=start, end=end, limit=500) for symbol in symbols
    }


@st.cache_data(ttl=30, show_spinner=False)
def fetch_all_volatility(
    target: str, symbols: tuple[str, ...], start: str | None, end: str | None
) -> dict[str, dict[str, Any]]:
    client = ApiClient(target)
    return {
        symbol: client.volatility_range(symbol, start=start, end=end, limit=500)
        for symbol in symbols
    }


@st.cache_data(ttl=30, show_spinner=False)
def fetch_sentiment(target: str, start: str | None, end: str | None) -> dict[str, Any]:
    return ApiClient(target).sentiment_hourly(start=start, end=end, limit=500)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_freshness(target: str) -> dict[str, Any]:
    return ApiClient(target).freshness()


@st.cache_data(ttl=30, show_spinner=False)
def fetch_model(target: str) -> dict[str, Any]:
    return ApiClient(target).model_latest()


@st.cache_data(ttl=30, show_spinner=False)
def fetch_quality(target: str) -> dict[str, Any]:
    return ApiClient(target).quality_status()


@st.cache_data(ttl=30, show_spinner=False)
def fetch_datasets(target: str, query: str | None) -> dict[str, Any]:
    return ApiClient(target).datasets(query=query, limit=100)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_dataset(target: str, dataset_id: str) -> dict[str, Any]:
    return ApiClient(target).dataset_detail(dataset_id)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_lineage(target: str, dataset_id: str) -> dict[str, Any]:
    return ApiClient(target).lineage(dataset_id)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_instance(target: str) -> dict[str, Any]:
    return ApiClient(target).meta_instance()


def fmt(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:,.{digits}f}"


def filter_window(preset: str, custom: Any) -> tuple[str | None, str | None]:
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


def chip(label: str, value: str, tone: str = "navy") -> None:
    colors = {"navy": theme.NAVY, "pink": theme.PINK, "amber": theme.AMBER, "muted": theme.MUTED}
    color = colors.get(tone, theme.NAVY)
    st.markdown(
        f"<span style='display:inline-block;border:1px solid {theme.BORDER};"
        f"border-radius:999px;padding:4px 10px;margin:2px 6px 2px 0;"
        f"font-size:12px;color:{color}'>{label} · <b>{value}</b></span>",
        unsafe_allow_html=True,
    )


def frame_map(payload: dict[str, dict[str, Any]]) -> dict[str, pd.DataFrame]:
    return {
        symbol: an.utc_frame((body or {}).get("data") or []) for symbol, body in payload.items()
    }


def long_frame(frames: dict[str, pd.DataFrame], column: str) -> pd.DataFrame:
    rows = []
    for symbol, frame in frames.items():
        if frame.empty or column not in frame:
            continue
        part = frame[["window_start", column]].copy()
        part["symbol"] = symbol
        rows.append(part)
    if not rows:
        return pd.DataFrame(columns=["window_start", "symbol", column])
    return pd.concat(rows, ignore_index=True).sort_values("window_start")


def worst_freshness(rows: list[dict[str, Any]]) -> tuple[str, str]:
    order = {"stale": 3, "warn": 2, "ok": 1, "unknown": 0}
    worst = "unknown"
    for row in rows:
        status = str(row.get("status", "unknown"))
        if order.get(status, 0) > order.get(worst, 0):
            worst = status
    return worst, {"stale": "amber", "warn": "amber", "ok": "navy"}.get(worst, "muted")


def main() -> None:
    target = api_target()
    st.title(PAGE_TITLE)
    st.caption(SUBTITLE)

    with st.sidebar:
        st.header("Filter")
        symbol = st.selectbox("Symbol", SYMBOLS, index=0)
        preset = st.selectbox(
            "Rentang waktu",
            ["24 jam", "7 hari", "14 hari", "Semua data", "Rentang khusus"],
            index=3,
        )
        custom = st.date_input(
            "Rentang khusus (UTC)",
            value=(datetime.now(UTC).date() - timedelta(days=7), datetime.now(UTC).date()),
            disabled=preset != "Rentang khusus",
        )
        if st.button("Muat ulang", width="stretch"):
            st.cache_data.clear()
        st.caption(f"API: {target}")

    start, end = filter_window(preset, custom)

    try:
        latest = fetch_market_latest(target, symbol)
        all_latest = fetch_all_latest(target, SYMBOLS)
        all_ohlc = fetch_all_ohlc(target, SYMBOLS, start, end)
        all_vol = fetch_all_volatility(target, SYMBOLS, start, end)
        sentiment = fetch_sentiment(target, start, end)
        quality = fetch_quality(target)
        freshness = fetch_freshness(target)
        model = fetch_model(target)
        datasets = fetch_datasets(target, None)
        instance = fetch_instance(target)
    except ApiError as exc:
        st.error(f"API menolak permintaan: {exc}")
        st.stop()

    frames = frame_map(all_ohlc)
    vol_frames = frame_map(all_vol)
    sentiment_rows = sentiment.get("data") or []
    sentiment_frame = an.utc_frame(sentiment_rows)
    latest_row = latest.get("data") or {}

    tabs = st.tabs(
        [
            "Ringkasan",
            "Market",
            "Volatilitas",
            "Korelasi",
            "Sentimen",
            "Kualitas",
            "Katalog",
            "Lineage",
        ]
    )

    with tabs[0]:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(f"Harga terakhir ({symbol})", fmt(latest_row.get("close")))
        with col2:
            st.metric("Volatilitas 1 jam", fmt(latest_row.get("realized_vol_1h"), 6))
        with col3:
            score = (
                sentiment_frame["mean_sentiment"].iloc[-1] if not sentiment_frame.empty else None
            )
            st.metric("Sentimen pasar", fmt(score, 3))
        with col4:
            if model.get("status") == "available":
                st.metric(
                    "Prediksi berikutnya", fmt(model.get("metrics", {}).get("latest_prediction"), 6)
                )
            else:
                st.metric("Prediksi berikutnya", "belum ada model")

        worst, tone = worst_freshness(freshness.get("data") or [])
        dataset_count = len(datasets.get("data") or [])
        quality_data = quality.get("data") or {}
        chips = st.columns(4)
        with chips[0]:
            chip("freshness", worst, tone)
        with chips[1]:
            chip(
                "quality",
                str(quality_data.get("status", "unknown")),
                "pink" if quality_data.get("critical_failures") else "navy",
            )
        with chips[2]:
            chip("katalog", f"{dataset_count} dataset")
        with chips[3]:
            chip("instance", str((instance.get("data") or {}).get("instance", "—")), "muted")

        performance = []
        for symbol_name, frame in frames.items():
            if frame.empty or "close" not in frame:
                continue
            values = an.normalized(frame)
            if values.empty:
                continue
            part = pd.DataFrame(
                {"window_start": frame["window_start"], "symbol": symbol_name, "value": values}
            )
            performance.append(part)
        if performance:
            st.subheader("Performa ternormalisasi (awal = 100)")
            st.altair_chart(theme.multi_line(pd.concat(performance, ignore_index=True), "value"))
        else:
            st.info("Belum ada data harga pada rentang ini.")

        table = []
        for symbol_name, body in all_latest.items():
            row = (body or {}).get("data") or {}
            if row:
                table.append(
                    {
                        "symbol": symbol_name,
                        "close": row.get("close"),
                        "volatilitas": row.get("realized_vol_1h"),
                        "window_start": row.get("window_start"),
                    }
                )
        if table:
            st.dataframe(pd.DataFrame(table), width="stretch", hide_index=True)

    with tabs[1]:
        st.subheader("Harga 5 symbol")
        normalized = []
        for symbol_name, frame in frames.items():
            values = an.normalized(frame)
            if values.empty:
                continue
            normalized.append(
                pd.DataFrame(
                    {"window_start": frame["window_start"], "symbol": symbol_name, "value": values}
                )
            )
        if normalized:
            st.altair_chart(theme.multi_line(pd.concat(normalized, ignore_index=True), "value"))
        else:
            st.info("Belum ada data harga pada rentang ini.")

        st.subheader(f"Detail {symbol}")
        selected = frames.get(symbol, pd.DataFrame())
        if not selected.empty:
            st.altair_chart(theme.price_line(selected))
        else:
            st.info("Symbol ini belum punya bar pada rentang tersebut.")

    with tabs[2]:
        st.subheader("Volatilitas terealisasi 5 symbol")
        vol_long = long_frame(vol_frames, "realized_vol_1h")
        if vol_long.empty:
            st.info("Belum ada bar volatilitas pada rentang ini.")
        else:
            st.altair_chart(
                theme.multi_line(vol_long, "realized_vol_1h", y_title="realized vol 1h")
            )
            summary = (
                vol_long.groupby("symbol")["realized_vol_1h"]
                .agg(["count", "mean", "max"])
                .reset_index()
                .rename(columns={"count": "n", "mean": "rata-rata", "max": "maks"})
            )
            st.dataframe(summary, width="stretch", hide_index=True)

    with tabs[3]:
        st.subheader("Korelasi 5 symbol")
        st.caption("Korelasi mengukur pergerakan bersama, bukan sebab-akibat.")
        basis = st.radio(
            "Basis", ["Return", "Volatilitas"], horizontal=True, label_visibility="collapsed"
        )
        returns = an.returns_frame(frames)
        volatility = an.volatility_frame(vol_frames)
        matrix_frame = returns if basis == "Return" else volatility
        n = len(matrix_frame)
        status = an.sample_status(n)
        if status == "insufficient":
            st.warning(
                f"Data berpasangan belum cukup: n={n}. Minimal {an.MIN_PAIRS} jam; "
                "tidak ada korelasi yang dihitung."
            )
            counts = {symbol_name: len(frame) for symbol_name, frame in frames.items()}
            st.dataframe(pd.DataFrame([counts]), width="stretch", hide_index=True)
        else:
            if status == "small":
                st.caption(f"Sample kecil: n={n}. Pakai sebagai indikasi, bukan kesimpulan.")
            matrix = an.correlation_matrix(matrix_frame)
            if matrix.empty:
                st.info("Matrix korelasi belum bisa dihitung.")
            else:
                st.altair_chart(theme.heatmap(matrix))
                summary = an.pairwise_summary(matrix)
                strongest = summary.iloc[0]
                cols = st.columns(3)
                with cols[0]:
                    st.metric("Rata-rata pairwise", fmt(float(summary["correlation"].mean()), 3))
                with cols[1]:
                    st.metric(
                        "Pasangan terkuat",
                        strongest["pair"],
                        help=f"r = {strongest['correlation']:.3f}",
                    )
                with cols[2]:
                    st.metric("Jumlah jam", str(n))

                pair_options = [
                    name for name in SYMBOLS if name != symbol and name in matrix_frame.columns
                ]
                if pair_options:
                    pair = st.selectbox("Pasangan rolling", pair_options, index=0)
                    rolling = an.rolling_correlation(matrix_frame, symbol, pair, window=24)
                    st.subheader(f"Rolling 24 jam · {symbol} / {pair}")
                    if rolling.empty:
                        st.info("Rolling correlation belum tersedia untuk pasangan ini.")
                    else:
                        st.altair_chart(theme.correlation_line(rolling))
                    lag = an.lead_lag(matrix_frame, symbol, pair, max_lag=3)
                    st.subheader(f"Lead-lag · {symbol} / {pair}")
                    if lag.empty:
                        st.info("Lead-lag belum tersedia.")
                    else:
                        st.altair_chart(theme.lead_lag_bars(lag))
                        st.caption(
                            "Lag positif berarti pergerakan symbol pertama "
                            "mendahului symbol kedua pada data historis."
                        )

    with tabs[4]:
        st.subheader("Sentimen per jam")
        if sentiment_frame.empty:
            st.info("Belum ada agregat sentimen pada rentang ini.")
        else:
            st.altair_chart(
                theme.value_bars(
                    sentiment_frame,
                    "mean_sentiment",
                    color=theme.PINK,
                    domain=(-1.0, 1.0),
                )
            )
            btc = frames.get("BTCUSDT", pd.DataFrame())
            if not btc.empty:
                prices = btc.set_index("window_start")["close"].astype(float)
                returns = np.log(prices / prices.shift(1)).rename("return_btc").reset_index()
                joined = sentiment_frame.merge(returns, on="window_start", how="inner").dropna(
                    subset=["mean_sentiment", "return_btc"]
                )
                if len(joined) >= an.MIN_PAIRS:
                    st.subheader("Sentimen vs return BTC")
                    st.altair_chart(theme.scatter(joined, "mean_sentiment", "return_btc"))
                else:
                    st.caption(
                        f"Scatter sentimen vs return butuh minimal {an.MIN_PAIRS} jam; "
                        f"tersedia {len(joined)}."
                    )
            summary = (
                sentiment_frame["mean_sentiment"].agg(["count", "mean", "min", "max"]).to_dict()
            )
            st.dataframe(pd.DataFrame([summary]), width="stretch", hide_index=True)

    with tabs[5]:
        st.subheader("Kualitas data")
        quality_data = quality.get("data") or {}
        cols = st.columns(4)
        with cols[0]:
            st.metric("Status", str(quality_data.get("status", "unknown")))
        with cols[1]:
            st.metric("Critical", str(quality_data.get("critical_failures", 0)))
        with cols[2]:
            st.metric("Warning", str(quality_data.get("warning_failures", 0)))
        with cols[3]:
            st.metric("Run", str(quality_data.get("run_ts", "—")))
        failures = quality_data.get("failures") or []
        if failures:
            st.dataframe(pd.DataFrame(failures), width="stretch", hide_index=True)
        else:
            st.caption("Tidak ada failure pada run terakhir.")

        st.subheader("Freshness")
        freshness_rows = freshness.get("data") or []
        if freshness_rows:
            st.dataframe(pd.DataFrame(freshness_rows), width="stretch", hide_index=True)
        else:
            st.info("Belum ada data freshness.")
        st.caption(
            "ok = umur <= SLO · warn = <= 2x SLO · stale = di atasnya · unknown = belum ada data"
        )

    with tabs[6]:
        st.subheader("Katalog dataset")
        query = st.text_input("Cari nama, owner, atau tag", value="")
        try:
            result = fetch_datasets(target, query or None)
        except ApiError as exc:
            st.error(f"Katalog tidak bisa dimuat: {exc}")
            result = {"data": []}
        items = result.get("data") or []
        if items:
            table = pd.DataFrame(
                [
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "layer": item.get("layer"),
                        "domain": item.get("domain"),
                        "owner": item.get("owner"),
                        "classification": item.get("classification"),
                        "retention": item.get("retention_days"),
                        "refresh": item.get("refresh_schedule"),
                    }
                    for item in items
                ]
            )
            st.dataframe(table, width="stretch", hide_index=True)
            dataset_id = st.selectbox("Detail dataset", [item["id"] for item in items])
            try:
                detail = fetch_dataset(target, dataset_id)
                st.dataframe(
                    pd.DataFrame(
                        [
                            {"field": key, "value": str(value)}
                            for key, value in detail.items()
                            if key != "meta"
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                )
            except ApiError as exc:
                st.error(f"Detail dataset gagal: {exc}")
        else:
            st.info("Tidak ada dataset yang cocok.")

    with tabs[7]:
        st.subheader("Lineage dataset")
        try:
            catalog = fetch_datasets(target, None)
        except ApiError as exc:
            st.error(f"Lineage tidak bisa dimuat: {exc}")
            catalog = {"data": []}
        ids = [item["id"] for item in (catalog.get("data") or [])]
        if not ids:
            st.info("Katalog kosong.")
        else:
            dataset_id = st.selectbox(
                "Dataset",
                ids,
                index=ids.index("gold.mart_market") if "gold.mart_market" in ids else 0,
            )
            try:
                payload = fetch_lineage(target, dataset_id)
                upstream = payload.get("upstream") or []
                downstream = payload.get("downstream") or []
                st.write(f"**Upstream** {len(upstream)} · **Downstream** {len(downstream)}")
                st.code(" -> ".join([*upstream, dataset_id, *downstream]), language="text")
                st.dataframe(
                    pd.DataFrame(
                        [{"arah": "upstream", "dataset": item} for item in upstream]
                        + [{"arah": "downstream", "dataset": item} for item in downstream]
                    ),
                    width="stretch",
                    hide_index=True,
                )
            except ApiError as exc:
                st.error(f"Lineage gagal: {exc}")

    st.divider()
    instance_data = instance.get("data") or {}
    st.caption(
        f"source API · instance {instance_data.get('instance', '—')} · "
        f"version {instance_data.get('version', '—')} · commit {instance_data.get('commit', '—')}"
    )


if __name__ == "__main__":
    try:
        main()
    except (ApiError, httpx.HTTPError) as exc:  # pragma: no cover - UI guard
        st.error(f"Dashboard tidak bisa memuat data: {exc}")
