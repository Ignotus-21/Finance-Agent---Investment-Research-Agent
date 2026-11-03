"""
Streamlit Interactive Research Console for the IRA API.
Supports local development (`http://localhost:8080`), remote Cloud Run targets
via service account impersonation, and Cloud Run metadata server authentication.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

import httpx
import streamlit as st

DEFAULT_URL = os.environ.get("IRA_SERVICE_URL", "http://localhost:8080")
DEFAULT_IMPERSONATE = os.environ.get("IRA_IMPERSONATE_SA", "")
DEFAULT_AUDIENCE = os.environ.get("IRA_AUDIENCE", "")
ON_CLOUD_RUN = bool(os.environ.get("K_SERVICE"))
LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0")

FOCUS_AREA_OPTIONS = [
    "Operating_Margin",
    "Segment_Revenue",
    "Risk_Factors",
    "Services_Margin",
    "China_Headwinds",
    "Capital_Allocation",
    "Free_Cash_Flow",
]


def is_local(url: str) -> bool:
    return any(host in url for host in LOCAL_HOSTS)


def mint_identity_token(audience: str, impersonate: str) -> str:
    """Mint a Google OIDC ID token for `audience` by impersonating a service account."""
    cmd = [
        "gcloud",
        "auth",
        "print-identity-token",
        f"--impersonate-service-account={impersonate}",
        f"--audiences={audience}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gcloud failed with no output")
    return result.stdout.strip()


def fetch_metadata_identity_token(audience: str) -> str:
    """Mint a Google OIDC ID token for `audience` from the Cloud Run metadata server."""
    import google.auth.transport.requests
    import google.oauth2.id_token

    request = google.auth.transport.requests.Request()
    return str(google.oauth2.id_token.fetch_id_token(request, audience))


def build_headers(url: str, impersonate: str, audience: str) -> dict[str, str]:
    if is_local(url):
        return {"Authorization": "Bearer local-development-token"}

    if not audience:
        raise RuntimeError(
            "Audience is required for a remote target. Use the service's "
            "configured audience (e.g. `ira-service-production`)."
        )

    if ON_CLOUD_RUN:
        return {"Authorization": f"Bearer {fetch_metadata_identity_token(audience)}"}

    if not impersonate:
        raise RuntimeError(
            "A remote target requires a service account with roles/run.invoker "
            "to impersonate."
        )
    return {"Authorization": f"Bearer {mint_identity_token(audience, impersonate)}"}


def render_metrics(metrics: list[dict[str, Any]]) -> None:
    if not metrics:
        st.info(
            "No standardized operating margin metrics returned for this filer's GAAP taxonomy."
        )
        return

    for m in metrics:
        unit = m.get("unit", "")
        suffix = {"percentage": "%", "bps": " bps", "ratio_multiple": "x"}.get(unit, "")
        cols = st.columns([3, 2, 5])
        cols[0].markdown(f"**{m['display_name']}**")
        cols[1].markdown(f"### {m['value']}{suffix}")
        with cols[2]:
            st.caption(f"`{m.get('formula_applied', '')}`")
            prior, current = m.get("prior_period_value"), m.get("current_period_value")
            if prior is not None or current is not None:
                st.caption(f"prior: {prior}  ·  current: {current}")
            if not m.get("provenance_verified", False):
                st.warning("provenance NOT verified", icon="⚠️")
        st.divider()


def render_citations(citations: list[dict[str, Any]]) -> None:
    for c in citations:
        accession = c.get("filing_accession_number")
        title = f"{c['source_type']} · {c['document_period']} · {c['table_or_section_name']}"
        with st.expander(title):
            if accession:
                st.markdown(f"Accession `{accession}`")
            if c.get("row_item"):
                st.markdown(f"Row: **{c['row_item']}**  ·  Column: **{c.get('column_header', '—')}**")
            if c.get("verbatim_quote"):
                st.markdown(f"> {c['verbatim_quote']}")
            if c.get("source_url"):
                st.markdown(f"[Open source]({c['source_url']})")


def main() -> None:
    st.set_page_config(page_title="IRA Research Console", page_icon="📊", layout="wide")
    st.title("Investment Research Agent — Console")

    with st.sidebar:
        st.header("Target")
        url = st.text_input("Service URL", DEFAULT_URL).rstrip("/")
        impersonate = ""
        audience = ""
        if not is_local(url):
            audience = st.text_input(
                "Audience",
                DEFAULT_AUDIENCE,
                help="The Cloud Run service's custom OIDC audience.",
            ).strip()
            if ON_CLOUD_RUN:
                st.caption(
                    "🔐 Running on Cloud Run — signing requests with the runtime "
                    "service account via the metadata server."
                )
            else:
                impersonate = st.text_input(
                    "Impersonate service account",
                    DEFAULT_IMPERSONATE,
                    help="Service account holding roles/run.invoker on the target service.",
                ).strip()

        st.header("Request")
        ticker = st.text_input("Ticker", "AAPL").strip().upper()
        fiscal_year = st.number_input("Fiscal year", 2010, 2030, 2024, step=1)
        focus_areas = st.multiselect(
            "Focus areas", FOCUS_AREA_OPTIONS, default=["Operating_Margin", "Risk_Factors"]
        )
        include_macro = st.checkbox("Include macro context", value=True)
        submitted = st.button("Generate brief", type="primary", use_container_width=True)

    try:
        headers = build_headers(url, impersonate, audience)
    except RuntimeError as exc:
        st.info("**Configure target authentication in the sidebar to connect.**")
        st.warning(str(exc), icon="🔑")
        st.stop()

    try:
        ready = httpx.get(f"{url}/readyz", headers=headers, timeout=20).json()
        runtime = ready.get("runtime", {})
        offline = runtime.get("offline_mode")
        cols = st.columns(3)
        cols[0].metric("Environment", runtime.get("environment", "unknown"))
        cols[1].metric("Data path", "RECORDED CORPUS" if offline else "LIVE sec.gov")
        cols[2].metric("SEC circuit breaker", ready.get("dependencies", {}).get("circuit_breaker", "?"))
        if offline:
            st.info(
                "Serving the recorded FY2024 SEC EDGAR corpus (`OFFLINE_MODE=true`).",
                icon="📼",
            )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Cannot reach {url}/readyz — {exc}")
        st.stop()

    if not submitted:
        st.info("Configure a request in the sidebar and press **Generate brief**.")
        return

    payload = {
        "ticker": ticker,
        "fiscal_year": int(fiscal_year),
        "focus_areas": focus_areas,
        "include_macro_context": include_macro,
    }

    with st.spinner(f"Researching {ticker} FY{fiscal_year}…"):
        try:
            response = httpx.post(
                f"{url}/v1/research/equity",
                json=payload,
                headers=headers,
                timeout=180,
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Request failed: {exc}")
            return

    if response.status_code == 401:
        st.error("HTTP 401: Bearer token failed verification. Check the configured OIDC audience.")
        return
    if response.status_code == 403:
        st.error("HTTP 403: Caller lacks roles/run.invoker on the target Cloud Run service.")
        return
    if response.status_code != 200:
        st.error(f"HTTP {response.status_code}")
        st.code(response.text)
        return

    brief = response.json()

    st.header(f"{brief['company_name']} ({brief['ticker']}) — FY{brief['fiscal_year']}")
    st.caption(f"Brief `{brief['brief_id']}`")
    st.markdown(brief["executive_summary"])

    st.subheader("Verified metrics")
    render_metrics(brief.get("key_financial_metrics", []))

    synthesis = brief.get("qualitative_synthesis", {})
    tabs = st.tabs(["Executive commentary", "Analyst Q&A", "Macro context", "Risks", "Raw JSON"])
    tabs[0].markdown(synthesis.get("executive_commentary_analysis", "—"))
    tabs[1].markdown(synthesis.get("analyst_qa_highlights", "—"))
    tabs[2].markdown(synthesis.get("macro_market_context", "—"))
    with tabs[3]:
        for risk in brief.get("risk_matrices", []):
            st.markdown(f"**{risk['risk_category']}** — `{risk['severity']}`")
            st.markdown(risk["description"])
            st.caption(risk["source_disclosure"])
    tabs[4].code(json.dumps(brief, indent=2), language="json")

    st.subheader(f"Citations ({len(brief.get('citations', []))})")
    render_citations(brief.get("citations", []))

    meta = brief.get("metadata", {})
    st.caption(
        f"latency {meta.get('latency_ms')} ms · tokens {meta.get('total_tokens_consumed')} · "
        f"cache hit {meta.get('context_cache_hit')} · est. cost ${meta.get('estimated_cost_usd')}"
    )


if __name__ == "__main__":
    main()
