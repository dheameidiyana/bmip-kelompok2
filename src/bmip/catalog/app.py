"""BMIP data catalog portal (C3-C, five views).

The portal is read-only towards the Query API, except for the existing admin
reload/backfill actions. Five views cover the ARCHITECTURE 14.3 requirement:
Search, Dataset detail, Lineage, Quality, and Governance.
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

VIEWS = ["Search", "Dataset detail", "Lineage", "Quality", "Governance"]
LAYER_RETENTION = {"bronze": 14, "silver": 30, "gold": 90}
FRESHNESS_BY_DOMAIN = {
    "market": "market",
    "social": "sentiment",
    "ml": "predictions",
    "ops": "quality",
}
DOCS_BASE = os.getenv("BMIP_DOCS_BASE_URL", "https://docs.bmip.local")


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


def client() -> CatalogClient:
    return CatalogClient()


def _freshness_metric(dataset: dict[str, Any]) -> str:
    if "prediction" in str(dataset.get("id", "")):
        return "predictions"
    return FRESHNESS_BY_DOMAIN.get(str(dataset.get("domain", "")), "market")


def _status_badge(dataset: dict[str, Any]) -> str:
    status = str(dataset.get("status") or "active")
    if status == "active":
        return "active"
    removal = dataset.get("removal_date")
    return f"{status} (removal {removal})" if removal else status


def _filters(api: CatalogClient) -> dict[str, Any]:
    st.sidebar.subheader("Pencarian")
    query = st.sidebar.text_input("Nama, owner, tag", "")
    owner = st.sidebar.text_input("Owner", "")
    domain = st.sidebar.selectbox("Domain", ["semua", "market", "social", "ml", "ops"])
    layer = st.sidebar.selectbox("Layer", ["semua", "bronze", "silver", "gold", "serving"])
    classification = st.sidebar.selectbox(
        "Klasifikasi",
        ["semua", "public", "internal", "confidential", "restricted", "pii"],
    )
    return {
        "query": query or None,
        "owner": owner or None,
        "domain": None if domain == "semua" else domain,
        "layer": None if layer == "semua" else layer,
        "classification": None if classification == "semua" else classification,
    }


def _load_datasets(api: CatalogClient, filters: dict[str, Any]) -> list[dict[str, Any]]:
    page = api.datasets(**filters)
    return page.get("data", [])


def _select_dataset(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    if not rows:
        st.info("Tidak ada dataset yang bisa dipilih.")
        return None
    ids = [row["id"] for row in rows]
    current = st.session_state.get("selected_dataset")
    index = ids.index(current) if current in ids else 0
    selected = st.selectbox("Pilih dataset", ids, index=index, key=key)
    st.session_state["selected_dataset"] = selected
    return next(row for row in rows if row["id"] == selected)


def _dataset_table(rows: list[dict[str, Any]]) -> None:
    st.dataframe(
        [
            {
                "id": row["id"],
                "name": row["name"],
                "owner": row["owner"],
                "layer": row["layer"],
                "domain": row["domain"],
                "klasifikasi": row["classification"],
                "status": row.get("status") or "active",
                "retensi (hari)": row["retention_days"],
                "refresh": row.get("refresh_schedule") or "-",
            }
            for row in rows
        ],
        hide_index=True,
        use_container_width=True,
    )


def _freshness(api: CatalogClient, dataset: dict[str, Any]) -> dict[str, Any] | None:
    try:
        payload = api.freshness()
    except ApiError:
        return None
    metric = _freshness_metric(dataset)
    for row in payload.get("data", []):
        if row.get("metric") == metric:
            return row
    return None


def _quality(api: CatalogClient) -> dict[str, Any] | None:
    try:
        return api.quality().get("data")
    except ApiError:
        return None


def _render_search(api: CatalogClient, filters: dict[str, Any]) -> list[dict[str, Any]]:
    st.subheader("Search")
    st.caption(
        "Pencarian nama, deskripsi, owner, tag, dan kolom memakai PostgreSQL "
        "`tsvector` + `pg_trgm`; filter domain, layer, dan klasifikasi."
    )
    rows = _load_datasets(api, filters)
    st.metric("Dataset cocok", len(rows))
    if not rows:
        st.info("Tidak ada dataset yang cocok dengan filter.")
        return rows
    _dataset_table(rows)
    selected = _select_dataset(rows, "search-dataset")
    if selected:
        st.session_state["selected_dataset"] = selected["id"]
        st.caption(
            f"Dataset dipilih: `{selected['id']}`. Buka tab **Dataset detail** "
            "untuk schema, lineage, dan quality."
        )
    return rows


def _render_detail(api: CatalogClient, rows: list[dict[str, Any]]) -> None:
    st.subheader("Dataset detail")
    dataset = _select_dataset(rows, "detail-dataset")
    if dataset is None:
        return
    detail = dataset
    try:
        detail = api.dataset(dataset["id"]).get("data", dataset)
    except ApiError:
        pass

    left, right = st.columns([3, 2])
    with left:
        st.markdown(f"### {detail['name']}")
        st.write(detail.get("description") or "-")
        st.markdown(
            f"**Owner:** {detail['owner']}  \n"
            f"**Layer/domain:** {detail['layer']} / {detail['domain']}  \n"
            f"**Klasifikasi:** {detail['classification']}  \n"
            f"**Status:** {_status_badge(detail)}  \n"
            f"**Retensi:** {detail['retention_days']} hari  \n"
            f"**Refresh:** {detail.get('refresh_schedule') or '-'}  \n"
            f"**SLA:** {detail.get('sla') or '-'}  \n"
            f"**Lisensi:** {detail.get('license') or '-'}  \n"
            f"**Kontrak:** {detail.get('contract_version') or '-'}  \n"
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
            st.caption(f"{len(quality.get('failures') or [])} rule gagal pada run terakhir")

    st.divider()
    st.subheader("Schema")
    try:
        schema = api.schema(dataset["id"])
        columns = schema.get("columns") or []
    except ApiError as exc:
        st.warning(f"Schema tidak tersedia: {exc}")
        columns = []
    if columns:
        st.dataframe(columns, hide_index=True, use_container_width=True)
    else:
        st.info("Schema belum tersimpan untuk dataset ini.")

    st.divider()
    st.subheader("Lineage langsung")
    try:
        lineage = api.lineage(dataset["id"])
        upstream = lineage.get("upstream") or []
        downstream = lineage.get("downstream") or []
    except ApiError as exc:
        st.warning(f"Lineage tidak tersedia: {exc}")
        upstream, downstream = [], []
    st.markdown("**Upstream:** " + (", ".join(upstream) if upstream else "-"))
    st.markdown("**Downstream:** " + (", ".join(downstream) if downstream else "-"))
    if upstream or downstream:
        st.code(" -> ".join([*upstream, dataset["id"], *downstream]), language="text")


def _lineage_dot(dataset_id: str, upstream: list[str], downstream: list[str]) -> str:
    lines = [
        "digraph lineage {",
        "  rankdir=LR;",
        '  node [shape=box, style="rounded,filled", fontname="Helvetica"];',
    ]
    for name in upstream:
        lines.append(f'  "{name}" [fillcolor="#dbeafe"];')
    lines.append(f'  "{dataset_id}" [fillcolor="#fde68a", penwidth=2];')
    for name in downstream:
        lines.append(f'  "{name}" [fillcolor="#dcfce7"];')
    for name in upstream:
        lines.append(f'  "{name}" -> "{dataset_id}";')
    for name in downstream:
        lines.append(f'  "{dataset_id}" -> "{name}";')
    lines.append("}")
    return "\n".join(lines)


def _render_lineage(api: CatalogClient, rows: list[dict[str, Any]]) -> None:
    st.subheader("Lineage")
    st.caption(
        "Grafik memakai edge OpenLineage yang di-cache di `ops.lineage_edges`. "
        "Pilih node lewat dropdown di bawah grafik untuk membuka detail."
    )
    dataset = _select_dataset(rows, "lineage-dataset")
    if dataset is None:
        return
    try:
        lineage = api.lineage(dataset["id"])
    except ApiError as exc:
        st.warning(f"Lineage tidak tersedia: {exc}")
        return
    upstream = lineage.get("upstream") or []
    downstream = lineage.get("downstream") or []
    if not upstream and not downstream:
        st.info("Belum ada edge lineage untuk dataset ini.")
        return
    st.graphviz_chart(_lineage_dot(dataset["id"], upstream, downstream), use_container_width=True)
    st.markdown(
        "**Upstream:** " + (", ".join(upstream) if upstream else "-") + "  \n"
        "**Downstream:** " + (", ".join(downstream) if downstream else "-")
    )
    options = [*upstream, dataset["id"], *downstream]
    chosen = st.selectbox("Buka detail node", options, index=options.index(dataset["id"]))
    if chosen != dataset["id"]:
        st.session_state["selected_dataset"] = chosen
        st.caption("Node dipilih. Buka tab **Dataset detail** untuk melihat metadata.")


def _render_quality(api: CatalogClient) -> None:
    st.subheader("Quality")
    quality = _quality(api)
    if not quality:
        st.info("Belum ada run kualitas yang tercatat.")
        return
    status = str(quality.get("status", "unknown"))
    run_ts = quality.get("run_ts") or quality.get("generated_at")
    col1, col2, col3 = st.columns(3)
    col1.metric("Status", status)
    col2.metric("Failure", len(quality.get("failures") or []))
    col3.metric("Run", str(run_ts)[:19] if run_ts else "-")
    failures = quality.get("failures") or []
    st.dataframe(failures, hide_index=True, use_container_width=True)
    st.markdown(f"GX Data Docs: [{DOCS_BASE}/gx/]({DOCS_BASE}/gx/)")
    st.divider()
    st.subheader("Freshness semua metrik")
    try:
        payload = api.freshness().get("data", [])
    except ApiError as exc:
        st.warning(f"Freshness tidak tersedia: {exc}")
        payload = []
    if payload:
        st.dataframe(payload, hide_index=True, use_container_width=True)
    else:
        st.info("Belum ada baris freshness.")


def _governance_gaps(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for row in rows:
        reasons: list[str] = []
        if not row.get("owner") or row.get("owner") == "unknown":
            reasons.append("owner kosong")
        if not row.get("description"):
            reasons.append("deskripsi kosong")
        if not row.get("classification"):
            reasons.append("klasifikasi kosong")
        expected = LAYER_RETENTION.get(str(row.get("layer")))
        if expected is not None and int(row.get("retention_days", 0)) != expected:
            reasons.append(f"retensi {row.get('retention_days')} != {expected}")
        if (row.get("status") or "active") != "active":
            reasons.append(f"status {row.get('status')}")
        if row.get("removal_date") and str(row["removal_date"]) < str(datetime.now(UTC).date()):
            reasons.append("removal date sudah lewat")
        if reasons:
            gaps.append({"id": row["id"], "owner": row.get("owner"), "masalah": "; ".join(reasons)})
    return gaps


def _render_governance(api: CatalogClient, rows: list[dict[str, Any]], role: str) -> None:
    st.subheader("Governance")
    st.caption(
        "Gap dihitung dari registry yang dibaca API. Workflow register/change/"
        "deprecate/delete dijalankan lewat `scripts/c3c_governance.py` dan "
        "meninggalkan satu baris `ops.audit_log` per aksi."
    )
    gaps = _governance_gaps(rows)
    col1, col2, col3 = st.columns(3)
    col1.metric("Dataset", len(rows))
    col2.metric("Gap", len(gaps))
    col3.metric("Tanpa owner", sum(1 for row in rows if not row.get("owner")))
    if gaps:
        st.dataframe(gaps, hide_index=True, use_container_width=True)
        st.download_button(
            "Unduh gap (CSV)",
            "\n".join(
                [
                    "id,owner,masalah",
                    *[f"{g['id']},{g['owner']},{g['masalah']}" for g in gaps],
                ]
            ),
            file_name="catalog-governance-gaps.csv",
            mime="text/csv",
        )
    else:
        st.success("Tidak ada gap governance pada registry saat ini.")
    st.markdown(
        "Dokumentasi tindakan: `docs/runbooks/catalog-governance.md`. "
        "Bukti uji: `evidence/catalog/metadata-test_*.txt`."
    )
    _admin_actions(api, role)


def _admin_actions(api: CatalogClient, role: str) -> None:
    if role not in {"operator", "admin"}:
        return
    st.divider()
    st.subheader("Aksi admin")
    if role == "admin" and st.button("Reload katalog dari ops.dataset_registry"):
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
        view = st.radio("View", VIEWS, index=0)
        filters = _filters(api)

    try:
        rows = _load_datasets(api, filters if view == "Search" else {})
    except ApiError as exc:
        st.error(f"Katalog tidak bisa dibaca: {exc}")
        return
    if not rows:
        st.info("Registry kosong atau API belum siap.")
        return

    if view == "Search":
        _render_search(api, filters)
    elif view == "Dataset detail":
        _render_detail(api, rows)
    elif view == "Lineage":
        _render_lineage(api, rows)
    elif view == "Quality":
        _render_quality(api)
    else:
        _render_governance(api, rows, role)


main()
