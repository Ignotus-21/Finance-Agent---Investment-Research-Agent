"""Streamlit console for exercising the IRA research API.

This is a test surface, not a product. `/docs` already gives you a working
OpenAPI form for the same endpoints; what this adds is a rendering of the brief
that makes the things worth checking visible at a glance - which data path the
revision is on, whether a metric's provenance was verified, and what the
citation actually points at.

Run it:

    make ui                    # against http://localhost:8080
    make ui URL=https://...    # against a deployed revision

Authentication follows whatever the target needs:

* **localhost** - the service accepts an unverified bearer credential, because
  `AUTH_ALLOWED_AUDIENCES` is empty outside production. The identity it records
  is prefixed `unverified-`, which is the intended, visible behaviour.
* **Cloud Run** - an ID token is required, and its audience must match. A user
  account cannot mint a token for an arbitrary audience (Google's own docs use
  `--impersonate-service-account` for exactly this), so the token comes from
  impersonating a service account that holds `roles/run.invoker`.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

import httpx
import streamlit as st

# `make ui URL=...` passes the target through the environment: Streamlit owns
# argv, so a command-line flag would have to be smuggled past `--`.
DEFAULT_URL = os.environ.get("IRA_SERVICE_URL", "http://localhost:8080")
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
    """Mint a Google ID token for `audience` by impersonating a service account.

    Shelling out to gcloud rather than using google-auth directly is deliberate:
    impersonation needs a source credential, a target principal and an audience,
    and gcloud already resolves all three from the active configuration. Doing it
    in-process would mean reimplementing that resolution to save a subprocess.
    """
    cmd = [
        "gcloud", "auth", "print-identity-token",
        f"--impersonate-service-account={impersonate}",
        f"--audiences={audience}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gcloud failed with no output")
    return result.stdout.strip()


def build_headers(url: str, impersonate: str, audience: str) -> dict[str, str]:
    if is_local(url):
        return {"Authorization": "Bearer local-development-token"}
    if not impersonate:
        raise RuntimeError(
            "A remote target needs a service account to impersonate. A user "
            "account cannot mint an ID token for a custom audience."
        )
    return {"Authorization": f"Bearer {mint_identity_token(audience or url, impersonate)}"}


def render_metrics(metrics: list[dict[str, Any]]) -> None:
    if not metrics:
        st.info("No metrics returned. For banks and much of pharma this is correct: "
                "they do not tag `OperatingIncomeLoss`, so margin is omitted rather than invented.")
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
    st.title("Investment Research Agent — test console")

    with st.sidebar:
        st.header("Target")
        url = st.text_input("Service URL", DEFAULT_URL).rstrip("/")
        impersonate = ""
        audience = ""
        if not is_local(url):
            impersonate = st.text_input(
                "Impersonate service account",
                help="Must hold roles/run.invoker. A user account cannot mint a "
                     "token for a custom audience.",
            )
            audience = st.text_input(
                "Audience",
                help="Leave blank to use the service URL. Set this if the service "
                     "has a Cloud Run custom audience configured.",
            )

        st.header("Request")
        ticker = st.text_input("Ticker", "AAPL").strip().upper()
        fiscal_year = st.number_input("Fiscal year", 2010, 2030, 2024, step=1)
        focus_areas = st.multiselect(
            "Focus areas", FOCUS_AREA_OPTIONS, default=["Operating_Margin", "Risk_Factors"]
        )
        include_macro = st.checkbox("Include macro context", value=True)
        submitted = st.button("Generate brief", type="primary", use_container_width=True)

    # Readiness banner. This is the first thing to check after any deploy:
    # offline and live responses are otherwise indistinguishable.
    try:
        ready = httpx.get(
            f"{url}/readyz", headers=build_headers(url, impersonate, audience), timeout=20
        ).json()
        runtime = ready.get("runtime", {})
        offline = runtime.get("offline_mode")
        cols = st.columns(3)
        cols[0].metric("Environment", runtime.get("environment", "unknown"))
        cols[1].metric("Data path", "RECORDED CORPUS" if offline else "LIVE sec.gov")
        cols[2].metric("SEC circuit breaker", ready.get("dependencies", {}).get("circuit_breaker", "?"))
        if offline:
            st.warning(
                "This revision serves the recorded FY2024 corpus. The arithmetic is "
                "right and the figures are a year old. Check `data_source` on any "
                "citation before quoting a number.",
                icon="📼",
            )
    except Exception as exc:  # noqa: BLE001 - surface anything, this is a console
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
                headers=build_headers(url, impersonate, audience),
                timeout=180,
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Request failed: {exc}")
            return

    if response.status_code == 401:
        st.error(
            "401 from the application. The token reached the service and failed "
            "verification — almost always the audience. Check the Cloud Run log "
            "for the rejected-claim line."
        )
        return
    if response.status_code == 403:
        st.error(
            "403 from Cloud Run IAM. The request never reached the container: the "
            "caller has no roles/run.invoker."
        )
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
    st.caption(
        "`estimated_cost_usd` and `context_cache_hit` are modelled, not measured — "
        "the cache is an in-process dict, not Vertex CachedContent (DEV-17)."
    )


if __name__ == "__main__":
    main()
