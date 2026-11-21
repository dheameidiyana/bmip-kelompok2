"""BMIP data catalog portal v1 (W2-C).

Search, dataset detail, schema, lineage, quality, and freshness. The portal
reads only the Query API, so RBAC and caching stay in one place. The five-view
governance portal is C3-C; this page covers the W2-C Must and Should items.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from bmip.catalog.client import CatalogClient
from bmip.common.logging import configure_logging, get_logger
from bmip.dashboard import theme
from bmip.dashboard.client import ApiError

load_dotenv()


@st.cache_resource
def _logging() -> bool:
    configure_logging(service="catalog")
    get_logger("bmip.catalog").info(
        "catalog started", extra={"ctx_target": os.getenv("BMIP_API_BASE_URL", "")}
    )
    return True


_logging()

st.set_page_config(
    page_title=os.getenv("BMIP_CATALOG_TITLE", "BMIP Data Catalog"),
    layout="wide",
    initial_sidebar_state="expanded",
)
theme.apply()

FRESHNESS_BY_DOMAIN = {
    "market": "market",
    "social": "sentiment",
    "ml": "predictions",
    "ops": "quality",
}


def freshness_metric(dataset: dict[str, Any]) -> str:
    if "prediction" in str(dataset.get("id", "")):
        return "predictions"
    return FRESHNESS_BY_DOMAIN.get(str(dataset.get("domain", "")), "market")


def client() -> CatalogClient:
    return CatalogClient()


def main() -> None:
    target = os.getenv("BMIP_API_BASE_URL", "http://localhost:8000")
    st.title("BMIP Data Catalog")
    st.caption(f"Sumber metadata: Query API {target}")

    api = client()
    try:
        identity = api.whoami()
    except ApiError:
        identity = {}
    role = str(identity.get("role", "anonymous"))
    actor = str(identity.get("actor", "anonymous"))

    with st.sidebar:
        st.subheader("Identitas")
        st.write(f"**Actor:** {actor}")
        st.write(f"**Role:** {role}")
        st.divider()
        st.subheader("Pencarian")
        query = st.text_input("Nama, owner, tag", "")
        domain = st.selectbox("Domain", ["semua", "market", "social", "ml", "ops"])
        layer = st.selectbox("Layer", ["semua", "bronze", "silver", "gold", "serving"])
        classification = st.selectbox(
            "Klasifikasi",
            ["semua", "public", "internal", "confidential", "restricted", "pii"],
        )

    try:
        page = api.datasets(
            query=query or None,
            domain=None if domain == "semua" else domain,
            layer=None if layer == "semua" else layer,
            classification=None if classification == "semua" else classification,
        )
    except ApiError as exc:
        st.error(f"Katalog tidak bisa dibaca: {exc}")
        return

    rows = page.get("data", [])
    st.subheader(f"Dataset ({len(rows)})")
    if not rows:
        st.info("Tidak ada dataset yang cocok dengan filter.")
        return

    st.dataframe(
        [
            {
                "id": row["id"],
                "owner": row["owner"],
                "layer": row["layer"],
                "domain": row["domain"],
                "klasifikasi": row["classification"],
                "saran": row.get("auto_classification") or "-",
                "retensi (hari)": row["retention_days"],
            }
            for row in rows
        ],
        hide_index=True,
        use_container_width=True,
    )

    dataset_id = st.selectbox("Pilih dataset", [row["id"] for row in rows])
    detail = next(row for row in rows if row["id"] == dataset_id)
    declared = str(detail.get("classification") or "")
    suggested = str(detail.get("auto_classification") or "")
    if suggested and suggested != declared:
        st.warning(
            f"Klasifikasi deklarasi '{declared}' berbeda dari saran kolom '{suggested}'. "
            "Tinjau di governance review."
        )

    left, right = st.columns([3, 2])
    with left:
        st.markdown(f"### {detail['name']}")
        st.write(detail.get("description") or "-")
        st.markdown(
            f"**Owner:** {detail['owner']}  \n"
            f"**Layer/domain:** {detail['layer']} / {detail['domain']}  \n"
            f"**Klasifikasi:** {declared}  \n"
            f"**Retensi:** {detail['retention_days']} hari  \n"
            f"**Refresh:** {detail.get('refresh_schedule') or '-'}  \n"
            f"**SLA:** {detail.get('sla') or '-'}  \n"
            f"**Lisensi:** {detail.get('license') or '-'}  \n"
            f"**Lokasi:** `{detail.get('location')}`"
        )
        if detail.get("tags"):
            st.write("**Tag:** " + ", ".join(detail["tags"]))

    with right:
        st.markdown("### Status")
        freshness = _freshness(api, detail)
        if freshness:
            st.metric(
                "Freshness",
                freshness.get("status", "unknown"),
                delta=f"{freshness.get('age_seconds', 0):.0f}s",
            )
            st.caption(
                f"metric `{freshness.get('metric')}`, SLO "
                f"{freshness.get('slo_seconds')}s, clock {freshness.get('clock')}"
            )
        else:
            st.info("Freshness belum tersedia untuk dataset ini.")
        quality = _quality(api)
        if quality:
            st.metric("DQ status", quality.get("status", "unknown"))
            failures = quality.get("failures") or []
            st.caption(f"{len(failures)} rule gagal pada run terakhir")

    st.divider()
    st.subheader("Schema")
    try:
        schema = api.schema(dataset_id)
        columns = schema.get("columns") or []
    except ApiError as exc:
        st.warning(f"Schema tidak tersedia: {exc}")
        columns = []
    if columns:
        st.dataframe(columns, hide_index=True, use_container_width=True)
    else:
        st.info("Schema belum tersimpan untuk dataset ini.")

    st.divider()
    st.subheader("Lineage")
    try:
        lineage = api.lineage(dataset_id)
        upstream = lineage.get("upstream") or []
        downstream = lineage.get("downstream") or []
    except ApiError as exc:
        st.warning(f"Lineage tidak tersedia: {exc}")
        upstream, downstream = [], []
    st.markdown("**Upstream:** " + (", ".join(upstream) if upstream else "-"))
    st.markdown("**Downstream:** " + (", ".join(downstream) if downstream else "-"))
    if upstream or downstream:
        chain = " -> ".join([*upstream, dataset_id, *downstream])
        st.code(chain, language="text")

    _admin_actions(api, role)


def _freshness(api: CatalogClient, dataset: dict[str, Any]) -> dict[str, Any] | None:
    try:
        payload = api.freshness()
    except ApiError:
        return None
    metric = freshness_metric(dataset)
    for row in payload.get("data", []):
        if row.get("metric") == metric:
            return row
    return None


def _quality(api: CatalogClient) -> dict[str, Any] | None:
    try:
        return api.quality().get("data")
    except ApiError:
        return None


def _admin_actions(api: CatalogClient, role: str) -> None:
    if role not in {"operator", "admin"}:
        return
    st.divider()
    st.subheader("Aksi")
    if role == "admin":
        if st.button("Reload katalog dari ops.dataset_registry"):
            try:
                result = api.reload_catalog()
                st.success(f"Katalog di-reload: {result.get('datasets', 0)} dataset")
            except ApiError as exc:
                st.error(f"Reload gagal: {exc}")
    start = st.date_input("Backfill dari", value=datetime.now(UTC) - timedelta(days=1))
    end = st.date_input("Backfill sampai", value=datetime.now(UTC))
    if st.button("Queue backfill"):
        try:
            result = api.queue_backfill(
                datetime.combine(start, datetime.min.time(), tzinfo=UTC).isoformat(),
                datetime.combine(end, datetime.min.time(), tzinfo=UTC).isoformat(),
            )
            st.success(f"Backfill {result.get('request_id')} status {result.get('status')}")
        except ApiError as exc:
            st.error(f"Backfill ditolak: {exc}")


main()
